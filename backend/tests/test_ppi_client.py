"""
Tests unitarios de PPIClient.
Usa unittest.mock para evitar llamadas reales a la API PPI.
Corre con: pytest backend/tests/test_ppi_client.py -v
"""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.ppi_client import (
    PPIClient,
    PPIAuthError,
    PPIPosition,
    _normalize_asset_type,
    _is_usd_instrument,
    DEFAULT_YIELDS,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _mock_response(status_code: int, body: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


AUTH_OK_RESPONSE = {
    "accessToken": "test-access-token-abc123",
    "refreshToken": "test-refresh-token-xyz789",
    "tokenType": "Bearer",
    "expirationDate": "2026-04-02T00:00:00Z",
}

PORTFOLIO_RESPONSE = {
    "groupedInstruments": [
        {
            "name": "CEDEARS",
            "instruments": [
                {
                    "ticker": "QQQ",
                    "name": "Invesco QQQ Trust",
                    "quantity": 5,
                    "price": 845000.0,   # ARS
                    "amount": 4225000.0, # ARS
                },
            ],
        },
        {
            "name": "BONOS",
            "instruments": [
                {
                    "ticker": "AL30",
                    "name": "Bono Argentino 2030",
                    "quantity": 100,
                    "price": 75.25,   # USD
                    "amount": 7525.0, # USD
                },
                {
                    "ticker": "S31G6",
                    "name": "LECAP Jun 2026",
                    "quantity": 500000,
                    "price": 102.50,    # ARS por 100 nominales
                    "amount": 512500.0, # ARS
                },
            ],
        },
        {
            "name": "ACCIONES",
            "instruments": [
                {
                    "ticker": "GGAL",
                    "name": "Grupo Galicia",
                    "quantity": 200,
                    "price": 4500.0,   # ARS
                    "amount": 900000.0,
                },
            ],
        },
        {
            "name": "FUTUROS",  # debe ser ignorado
            "instruments": [
                {
                    "ticker": "ROFEX",
                    "name": "Futuro Dólar",
                    "quantity": 10,
                    "price": 1450.0,
                    "amount": 14500.0,
                },
            ],
        },
    ]
}

BALANCE_RESPONSE = {
    "groupedAvailability": [
        {
            "name": "ABIERTA",
            "settlement": "INMEDIATA",
            "availability": [
                {"name": "ARS", "symbol": "$",   "amount": 50000.0},
                {"name": "USD", "symbol": "U$S", "amount": 1500.0},
            ],
        }
    ]
}

MOVEMENTS_RESPONSE = [
    {
        "date": "2026-03-15",
        "type": "COMPRA",
        "ticker": "QQQ",
        "quantity": 5,
        "price": 820000.0,
        "amount": 4100000.0,
    },
    {
        "date": "2026-02-10",
        "type": "COMPRA",
        "ticker": "AL30",
        "quantity": 100,
        "price": 72.0,
        "amount": 7200.0,
    },
    {
        "date": "2026-01-05",
        "type": "VENTA",
        "ticker": "GGAL",
        "quantity": 50,
        "price": 4200.0,
        "amount": 210000.0,
    },
]


# ── Tests de autenticación ─────────────────────────────────────────────────────

class TestPPIAuthentication:
    def test_authenticate_success_stores_tokens(self):
        client = PPIClient("pub-key-123", "priv-key-456")
        with patch("httpx.post", return_value=_mock_response(200, AUTH_OK_RESPONSE)):
            client.authenticate()

        assert client._access_token == "test-access-token-abc123"
        assert client._refresh_token == "test-refresh-token-xyz789"

    def test_authenticate_401_raises_ppi_auth_error(self):
        client = PPIClient("bad-key", "bad-secret")
        with patch("httpx.post", return_value=_mock_response(401, {"error": "Unauthorized"})):
            with pytest.raises(PPIAuthError, match="Status 401"):
                client.authenticate()

    def test_authenticate_connect_error_raises(self):
        import httpx as _httpx
        client = PPIClient("pub", "priv")
        with patch("httpx.post", side_effect=_httpx.ConnectError("connection refused")):
            with pytest.raises(PPIAuthError, match="No se pudo conectar"):
                client.authenticate()

    def test_authenticate_timeout_raises(self):
        import httpx as _httpx
        client = PPIClient("pub", "priv")
        with patch("httpx.post", side_effect=_httpx.TimeoutException("timeout")):
            with pytest.raises(PPIAuthError, match="Timeout"):
                client.authenticate()

    def test_headers_triggers_auth_if_no_token(self):
        client = PPIClient("pub", "priv")
        with patch.object(client, "authenticate") as mock_auth:
            mock_auth.side_effect = lambda: setattr(client, "_access_token", "tok")
            headers = client._headers()
        mock_auth.assert_called_once()
        assert headers["Authorization"] == "Bearer tok"

    def test_get_retries_on_401(self):
        client = PPIClient("pub", "priv")
        client._access_token = "old-token"
        client._refresh_token = "refresh"

        first  = _mock_response(401, {})
        second = _mock_response(200, {"data": "ok"})

        with patch("httpx.get", side_effect=[first, second]):
            with patch.object(client, "_refresh"):
                result = client._get("/api/v1/something")

        assert result == {"data": "ok"}

    def test_sandbox_uses_sandbox_base(self):
        from app.services.ppi_client import PPI_BASE_SANDBOX
        client = PPIClient("pub", "priv", sandbox=True)
        assert client._base == PPI_BASE_SANDBOX


# ── Tests de portafolio ────────────────────────────────────────────────────────

class TestPPIGetPortfolio:
    def _make_client(self) -> PPIClient:
        c = PPIClient("pub", "priv")
        c._access_token = "tok"
        return c

    def _patch_get(self, client, body=None):
        if body is None:
            body = PORTFOLIO_RESPONSE
        return patch.object(client, "_get", return_value=body)

    def _patch_mep(self, client, mep=1430.0):
        return patch.object(client, "_get_mep", return_value=mep)

    def test_returns_list_of_ppi_positions(self):
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client):
            positions = client.get_portfolio("12345")
        assert isinstance(positions, list)
        assert all(isinstance(p, PPIPosition) for p in positions)

    def test_futuros_excluded_from_portfolio(self):
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client):
            positions = client.get_portfolio("12345")
        tickers = [p.ticker for p in positions]
        assert "ROFEX" not in tickers

    def test_cedear_price_converted_from_ars(self):
        client = self._make_client()
        mep = 1430.0
        with self._patch_mep(client, mep), self._patch_get(client):
            positions = client.get_portfolio("12345")

        qqq = next(p for p in positions if p.ticker == "QQQ")
        expected_usd = Decimal("845000.0") / Decimal("1430.0")
        assert abs(qqq.current_price_usd - expected_usd) < Decimal("0.01")
        assert qqq.asset_type == "CEDEAR"

    def test_al30_price_not_converted_usd_passthrough(self):
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client):
            positions = client.get_portfolio("12345")

        al30 = next(p for p in positions if p.ticker == "AL30")
        assert al30.current_price_usd == Decimal("75.25")
        assert al30.asset_type == "BOND"

    def test_lecap_classified_as_letra(self):
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client):
            positions = client.get_portfolio("12345")

        s31g6 = next(p for p in positions if p.ticker == "S31G6")
        assert s31g6.asset_type == "LETRA"

    def test_accion_byma_classified_as_stock_ars_converted(self):
        client = self._make_client()
        mep = 1430.0
        with self._patch_mep(client, mep), self._patch_get(client):
            positions = client.get_portfolio("12345")

        ggal = next(p for p in positions if p.ticker == "GGAL")
        assert ggal.asset_type == "STOCK"
        expected_usd = Decimal("4500.0") / Decimal("1430.0")
        assert abs(ggal.current_price_usd - expected_usd) < Decimal("0.01")

    def test_zero_quantity_positions_excluded(self):
        body = {
            "groupedInstruments": [
                {
                    "name": "CEDEARS",
                    "instruments": [
                        {"ticker": "SPY", "name": "SPDR S&P 500",
                         "quantity": 0, "price": 550.0, "amount": 0.0},
                        {"ticker": "QQQ", "name": "QQQ",
                         "quantity": 3, "price": 550.0, "amount": 1650.0},
                    ],
                }
            ]
        }
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client, body):
            positions = client.get_portfolio("12345")

        assert len(positions) == 1
        assert positions[0].ticker == "QQQ"

    def test_annual_yield_assigned_by_asset_type(self):
        client = self._make_client()
        with self._patch_mep(client), self._patch_get(client):
            positions = client.get_portfolio("12345")

        qqq   = next(p for p in positions if p.ticker == "QQQ")
        s31g6 = next(p for p in positions if p.ticker == "S31G6")
        al30  = next(p for p in positions if p.ticker == "AL30")

        assert qqq.annual_yield_pct   == DEFAULT_YIELDS["cedear"]
        assert s31g6.annual_yield_pct == DEFAULT_YIELDS["letra"]
        assert al30.annual_yield_pct  == DEFAULT_YIELDS["bond"]


# ── Tests de saldo cash ────────────────────────────────────────────────────────

class TestPPICashBalance:
    def test_returns_ars_and_usd(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", return_value=BALANCE_RESPONSE):
            cash = client.get_cash_balance("12345")

        assert cash["ars"] == Decimal("50000.0")
        assert cash["usd"] == Decimal("1500.0")

    def test_returns_zeros_on_api_error(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", side_effect=Exception("network error")):
            cash = client.get_cash_balance("12345")

        assert cash["ars"] == Decimal("0")
        assert cash["usd"] == Decimal("0")

    def test_empty_availability_returns_zeros(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", return_value={"groupedAvailability": []}):
            cash = client.get_cash_balance("12345")

        assert cash["ars"] == Decimal("0")
        assert cash["usd"] == Decimal("0")


# ── Tests de operaciones ───────────────────────────────────────────────────────

class TestPPIOperations:
    def test_returns_list_of_operations(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", return_value=MOVEMENTS_RESPONSE):
            ops = client.get_operations("12345")

        assert isinstance(ops, list)
        assert len(ops) == 3

    def test_date_range_params_passed(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", return_value=[]) as mock_get:
            client.get_operations("12345", fecha_desde="2026-01-01", fecha_hasta="2026-03-31")

        mock_get.assert_called_once_with(
            "/api/v1/Account/GetMovements",
            params={"accountNumber": "12345", "dateFrom": "2026-01-01", "dateTo": "2026-03-31"},
        )

    def test_returns_empty_list_on_error(self):
        client = PPIClient("pub", "priv")
        client._access_token = "tok"
        with patch.object(client, "_get", side_effect=Exception("timeout")):
            ops = client.get_operations("12345")

        assert ops == []


# ── Tests de normalización de tipos ───────────────────────────────────────────

class TestNormalizeAssetType:
    def test_cedears_group_returns_cedear(self):
        assert _normalize_asset_type("CEDEARS", "QQQ") == "CEDEAR"

    def test_acciones_group_returns_stock(self):
        assert _normalize_asset_type("ACCIONES", "GGAL") == "STOCK"

    def test_etfs_group_returns_etf(self):
        assert _normalize_asset_type("ETFS", "SPY") == "ETF"

    def test_bonos_al30_returns_bond(self):
        assert _normalize_asset_type("BONOS", "AL30") == "BOND"

    def test_bonos_s31g6_returns_letra(self):
        assert _normalize_asset_type("BONOS", "S31G6") == "LETRA"

    def test_bonos_s15y6_returns_letra(self):
        assert _normalize_asset_type("BONOS", "S15Y6") == "LETRA"

    def test_bonos_s14n5_returns_letra(self):
        assert _normalize_asset_type("BONOS", "S14N5") == "LETRA"

    def test_cauciones_returns_caucion(self):
        assert _normalize_asset_type("CAUCIONES", "CAUC") == "CAUCION"

    def test_unknown_group_returns_stock(self):
        assert _normalize_asset_type("DESCONOCIDO", "XYZ") == "STOCK"


class TestIsUsdInstrument:
    def test_al30_is_usd(self):
        assert _is_usd_instrument("AL30", "BONOS") is True

    def test_gd35_is_usd(self):
        assert _is_usd_instrument("GD35", "BONOS") is True

    def test_ae38_is_usd(self):
        assert _is_usd_instrument("AE38", "BONOS") is True

    def test_lecap_s31g6_is_ars(self):
        assert _is_usd_instrument("S31G6", "BONOS") is False

    def test_cedear_qqq_is_ars(self):
        assert _is_usd_instrument("QQQ", "CEDEARS") is False

    def test_accion_ggal_is_ars(self):
        assert _is_usd_instrument("GGAL", "ACCIONES") is False


# ── Tests de FX helpers ────────────────────────────────────────────────────────

class TestPPIFxHelpers:
    def test_get_mep_returns_venta_price(self):
        client = PPIClient("pub", "priv")
        mock_resp = _mock_response(200, {"venta": 1435.50, "compra": 1430.0})
        with patch("httpx.get", return_value=mock_resp):
            mep = client._get_mep()
        assert mep == 1435.50

    def test_get_mep_fallback_on_error(self):
        client = PPIClient("pub", "priv")
        with patch("httpx.get", side_effect=Exception("network error")):
            mep = client._get_mep()
        assert mep == 1430.0

    def test_get_historical_mep_returns_average(self):
        client = PPIClient("pub", "priv")
        mock_resp = _mock_response(200, {
            "blue":     {"value_sell": 1440.0},
            "official": {"value_sell": 1050.0},
        })
        with patch("httpx.get", return_value=mock_resp):
            mep = client.get_historical_mep("2026-03-15")
        assert mep == pytest.approx(1245.0)  # (1440 + 1050) / 2

    def test_get_historical_mep_fallback_to_current(self):
        client = PPIClient("pub", "priv")
        with patch("httpx.get", side_effect=Exception("no data")):
            with patch.object(client, "_get_mep", return_value=1430.0):
                mep = client.get_historical_mep("2020-01-01")
        assert mep == 1430.0
