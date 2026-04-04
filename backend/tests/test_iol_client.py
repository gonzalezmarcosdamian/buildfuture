"""
Tests para iol_client.py — auth flow, normalización de tipos, cash balances, portfolio mapping.

Corre con: pytest backend/tests/test_iol_client.py -v
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import httpx

from app.services.iol_client import (
    IOLClient,
    IOLAuthError,
    IOLPosition,
    _normalize_asset_type,
    _TICKER_TYPE_OVERRIDES,
    DEFAULT_YIELDS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_resp(status: int, body: dict | list | str) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = str(body)
    if isinstance(body, (dict, list)):
        r.json.return_value = body
    else:
        r.json.side_effect = Exception("not json")
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"Error {status}", request=MagicMock(), response=r
        )
    return r


def _client():
    return IOLClient(username="test@example.com", password="secret")


# ── _normalize_asset_type ──────────────────────────────────────────────────────

class TestNormalizeAssetType:
    def test_fci_tipo(self):
        assert _normalize_asset_type("fci") == "FCI"

    def test_fondo_tipo(self):
        assert _normalize_asset_type("fondo comun") == "FCI"

    def test_cedear_tipo(self):
        assert _normalize_asset_type("cedear") == "CEDEAR"

    def test_accion_tipo_sin_override(self):
        # "accion" sin ticker override → CEDEAR (mapping)
        assert _normalize_asset_type("accion") == "CEDEAR"

    def test_letra_tipo(self):
        assert _normalize_asset_type("letra") == "LETRA"

    def test_bono_tipo_via_override(self):
        # "bono" contains "on" as substring → mapping matches "on" first → returns "ON".
        # BOND type is only reachable via ticker overrides (e.g. AL30, GD30).
        # This documents current behavior — fix pending in fix/fci-fuzzy-match branch.
        assert _normalize_asset_type("bono soberano") == "ON"

    def test_on_tipo(self):
        assert _normalize_asset_type("on corporativa") == "ON"

    def test_unknown_tipo_returns_stock(self):
        assert _normalize_asset_type("instrumento_raro") == "STOCK"

    def test_ticker_override_wins_over_tipo(self):
        # IOLCAMA con tipo "bono" → debe ser FCI por override de ticker
        assert _normalize_asset_type("bono", ticker="IOLCAMA") == "FCI"

    def test_ticker_override_al30(self):
        assert _normalize_asset_type("accion", ticker="AL30") == "BOND"

    def test_ticker_override_yca6o(self):
        assert _normalize_asset_type("cedear", ticker="YCA6O") == "ON"

    def test_ticker_override_case_insensitive(self):
        assert _normalize_asset_type("accion", ticker="al30") == "BOND"

    def test_all_overrides_present_in_map(self):
        for ticker in _TICKER_TYPE_OVERRIDES:
            result = _normalize_asset_type("unknown", ticker=ticker)
            assert result == _TICKER_TYPE_OVERRIDES[ticker]


# ── IOLClient.authenticate ─────────────────────────────────────────────────────

class TestAuthenticate:
    def test_stores_tokens_on_success(self):
        client = _client()
        resp = _mock_resp(200, {"access_token": "tok123", "refresh_token": "ref456"})
        with patch("app.services.iol_client.httpx.post", return_value=resp):
            client.authenticate()
        assert client._access_token == "tok123"
        assert client._refresh_token == "ref456"

    def test_raises_on_non_200(self):
        client = _client()
        resp = _mock_resp(401, {"error": "invalid_credentials"})
        with patch("app.services.iol_client.httpx.post", return_value=resp):
            with pytest.raises(IOLAuthError, match="401"):
                client.authenticate()

    def test_raises_on_missing_access_token(self):
        client = _client()
        resp = _mock_resp(200, {"refresh_token": "ref456"})  # no access_token
        with patch("app.services.iol_client.httpx.post", return_value=resp):
            with pytest.raises(IOLAuthError, match="access_token"):
                client.authenticate()

    def test_raises_on_timeout(self):
        client = _client()
        with patch("app.services.iol_client.httpx.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(IOLAuthError, match="Timeout"):
                client.authenticate()

    def test_raises_on_connect_error(self):
        client = _client()
        with patch("app.services.iol_client.httpx.post", side_effect=httpx.ConnectError("unreachable")):
            with pytest.raises(IOLAuthError, match="No se pudo conectar"):
                client.authenticate()

    def test_raises_on_non_json_response(self):
        client = _client()
        resp = _mock_resp(200, "not-json")
        with patch("app.services.iol_client.httpx.post", return_value=resp):
            with pytest.raises(IOLAuthError):
                client.authenticate()


# ── IOLClient.get_cash_balances ────────────────────────────────────────────────

class TestGetCashBalances:
    def _patched_client(self, account_data: dict) -> IOLClient:
        client = _client()
        client._access_token = "fake-token"
        client.get_account_balance = MagicMock(return_value=account_data)
        return client

    def test_ars_and_usd_from_cuentas_list(self):
        client = self._patched_client({
            "cuentas": [
                {"moneda": "peso_Argentino", "disponible": 100_000},
                {"moneda": "dolar_Estadounidense", "disponible": 500},
            ]
        })
        result = client.get_cash_balances()
        assert result["ars"] == Decimal("100000")
        assert result["usd"] == Decimal("500")

    def test_multiple_ars_cuentas_sum(self):
        client = self._patched_client({
            "cuentas": [
                {"moneda": "peso_Argentino", "disponible": 50_000},
                {"moneda": "pesos_ars", "disponible": 30_000},
            ]
        })
        result = client.get_cash_balances()
        assert result["ars"] == Decimal("80000")

    def test_empty_cuentas_falls_back_to_zero(self):
        client = self._patched_client({"cuentas": []})
        result = client.get_cash_balances()
        assert result["ars"] == Decimal("0")
        assert result["usd"] == Decimal("0")

    def test_flat_structure_ars(self):
        client = self._patched_client({"disponible": 75_000})
        result = client.get_cash_balances()
        assert result["ars"] == Decimal("75000")

    def test_returns_zero_on_exception(self):
        client = _client()
        client._access_token = "fake-token"
        client.get_account_balance = MagicMock(side_effect=RuntimeError("network error"))
        result = client.get_cash_balances()
        assert result["ars"] == Decimal("0")
        assert result["usd"] == Decimal("0")

    def test_cash_balance_ars_compat(self):
        client = self._patched_client({
            "cuentas": [{"moneda": "peso_Argentino", "disponible": 123_456}]
        })
        assert client.get_cash_balance_ars() == Decimal("123456")


# ── IOLClient.get_portfolio ────────────────────────────────────────────────────

class TestGetPortfolio:
    def _make_activo(self, simbolo="TEST", tipo="CEDEAR", cantidad=10, valorizado=15_000, ppc=1400):
        return {
            "titulo": {"simbolo": simbolo, "tipo": tipo, "descripcion": f"Desc {simbolo}"},
            "cantidad": cantidad,
            "valorizado": valorizado,
            "ppc": ppc,
        }

    def test_returns_positions_list(self):
        client = _client()
        client._access_token = "tok"
        client._get_mep = MagicMock(return_value=1430.0)
        client._get = MagicMock(return_value={
            "activos": [self._make_activo("MELI", "CEDEAR", 5, 50_000, 9000)]
        })
        positions = client.get_portfolio()
        assert len(positions) == 1
        assert isinstance(positions[0], IOLPosition)
        assert positions[0].ticker == "MELI"

    def test_skips_zero_quantity(self):
        client = _client()
        client._access_token = "tok"
        client._get_mep = MagicMock(return_value=1430.0)
        client._get = MagicMock(return_value={
            "activos": [
                self._make_activo("MELI", "CEDEAR", 0, 0, 0),  # should be skipped
                self._make_activo("QQQ",  "CEDEAR", 5, 50_000, 9000),
            ]
        })
        positions = client.get_portfolio()
        assert len(positions) == 1
        assert positions[0].ticker == "QQQ"

    def test_fci_ticker_override_assigns_fci_asset_type_and_yield(self):
        """Ticker override corrects asset_type AND yield for IOLCAMA.
        When IOL sends tipo='bono' for IOLCAMA, the ticker override ensures:
        - asset_type = FCI (not BOND/ON)
        - annual_yield_pct = DEFAULT_YIELDS['fci'] (not 'bono')
        """
        client = _client()
        client._access_token = "tok"
        client._get_mep = MagicMock(return_value=1430.0)
        client._get = MagicMock(return_value={
            "activos": [self._make_activo("IOLCAMA", "bono", 100, 100_000, 900)]
        })
        positions = client.get_portfolio()
        assert positions[0].asset_type == "FCI"
        assert positions[0].annual_yield_pct == DEFAULT_YIELDS["fci"]

    def test_letra_normalizes_ppc(self):
        """Para LETRAS, el ppc viene por cada 100 nominales → dividir por 100."""
        client = _client()
        client._access_token = "tok"
        mep = 1430.0
        client._get_mep = MagicMock(return_value=mep)
        ppc_raw = 990  # por 100 VN, como lo devuelve IOL
        valorizado = 9_900  # 10 títulos × 990 ARS
        client._get = MagicMock(return_value={
            "activos": [self._make_activo("S15Y6", "letra", 10, valorizado, ppc_raw)]
        })
        positions = client.get_portfolio()
        pos = positions[0]
        expected_avg_price_ars = Decimal(str(ppc_raw)) / Decimal("100")
        expected_avg_price_usd = expected_avg_price_ars / Decimal(str(mep))
        assert abs(pos.avg_price_usd - expected_avg_price_usd) < Decimal("0.0001")

    def test_empty_portfolio(self):
        client = _client()
        client._access_token = "tok"
        client._get_mep = MagicMock(return_value=1430.0)
        client._get = MagicMock(return_value={"activos": []})
        positions = client.get_portfolio()
        assert positions == []

    def test_current_price_usd_is_valorizado_over_qty_over_mep(self):
        client = _client()
        mep = 1430.0
        client._access_token = "tok"
        client._get_mep = MagicMock(return_value=mep)
        qty = 5
        valorizado = 71_500  # 5 × 14_300 ARS
        client._get = MagicMock(return_value={
            "activos": [self._make_activo("MELI", "CEDEAR", qty, valorizado, 12_000)]
        })
        positions = client.get_portfolio()
        expected_price_usd = Decimal(str(valorizado)) / Decimal(str(qty)) / Decimal(str(mep))
        assert abs(positions[0].current_price_usd - expected_price_usd) < Decimal("0.01")


# ── Token refresh logic ────────────────────────────────────────────────────────

class TestTokenRefresh:
    def test_401_triggers_refresh_and_retries(self):
        client = _client()
        client._access_token = "expired-tok"
        client._refresh_token = "ref-tok"

        call_count = [0]

        def fake_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _mock_resp(401, {"error": "token_expired"})
            return _mock_resp(200, {"activos": []})  # success on retry

        refresh_resp = _mock_resp(200, {"access_token": "new-tok", "refresh_token": "new-ref"})

        with patch("app.services.iol_client.httpx.get", side_effect=fake_get), \
             patch("app.services.iol_client.httpx.post", return_value=refresh_resp):
            client._get_mep = MagicMock(return_value=1430.0)
            positions = client.get_portfolio()

        assert client._access_token == "new-tok"
        assert call_count[0] == 2  # first call 401, second call 200
