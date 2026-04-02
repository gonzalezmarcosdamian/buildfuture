"""
Tests unitarios de CocosClient.
Mockea pycocos.Cocos completo — sin llamadas reales a la API.
Corre con: pytest backend/tests/test_cocos_client.py -v
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.cocos_client import (
    CocosClient,
    CocosAuthError,
    CocosPosition,
    DEFAULT_YIELDS,
    _normalize_instrument_type,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_position(
    ticker="COCOSPPA",
    name="Cocos Pesos Plus",
    instrument_type="FCI",
    quantity=1000.0,
    last=1300.0,
    previous_price=1280.0,
    average_price=1200.0,
    result_percentage=0.083,
):
    return {
        "short_ticker": ticker,
        "instrument_short_name": name,
        "instrument_type": instrument_type,
        "quantity": quantity,
        "last": last,
        "previous_price": previous_price,
        "average_price": average_price,
        "result_percentage": result_percentage,
        "id_security": 140681840,
    }


def _make_buying_power(ars=5000.0, usd=100.0):
    return {
        "CI":   {"ars": ars, "usd": usd, "ext": 0},
        "24hs": {"ars": ars, "usd": usd, "ext": 0},
    }


def _make_cocos_app(positions=None, buying_power=None):
    """Crea un mock del objeto pycocos.Cocos."""
    app = MagicMock()
    app.historic_performance.return_value = [_make_position()] if positions is None else positions
    app.buying_power.return_value = _make_buying_power() if buying_power is None else buying_power
    return app


MEP = 1430.0


# ── Tests de autenticación ─────────────────────────────────────────────────────

class TestCocosAuth:

    def test_authenticate_with_totp_secret_uses_pycocos(self):
        """Con TOTP secret: pycocos.Cocos recibe topt_secret_key y autentica solo."""
        with patch("app.services.cocos_client.Cocos") as MockCocos:
            MockCocos.return_value = _make_cocos_app()
            client = CocosClient("user@test.com", "pass123", totp_secret="BASE32SECRET")
            client.authenticate()

        MockCocos.assert_called_once_with(
            email="user@test.com",
            password="pass123",
            topt_secret_key="BASE32SECRET",
        )

    def test_authenticate_with_manual_code_patches_input(self):
        """Sin TOTP secret: parchea builtins.input con el código provisto."""
        with patch("app.services.cocos_client.Cocos") as MockCocos:
            with patch("builtins.input", return_value="123456"):
                MockCocos.return_value = _make_cocos_app()
                client = CocosClient("user@test.com", "pass123")
                client.authenticate(code="123456")

        MockCocos.assert_called_once_with(
            email="user@test.com",
            password="pass123",
            topt_secret_key=None,
        )

    def test_authenticate_pycocos_exception_raises_cocos_auth_error(self):
        """Si pycocos falla al instanciar → CocosAuthError."""
        with patch("app.services.cocos_client.Cocos", side_effect=Exception("403 FORBIDDEN")):
            client = CocosClient("bad@test.com", "wrongpass")
            with pytest.raises(CocosAuthError, match="403"):
                client.authenticate(code="000000")

    def test_not_authenticated_raises_on_get_positions(self):
        """Llamar get_positions sin authenticate previo → CocosAuthError."""
        client = CocosClient("user@test.com", "pass")
        with pytest.raises(CocosAuthError, match="autenticado"):
            client.get_positions()

    def test_not_authenticated_raises_on_get_cash(self):
        """Llamar get_cash sin authenticate previo → CocosAuthError."""
        client = CocosClient("user@test.com", "pass")
        with pytest.raises(CocosAuthError, match="autenticado"):
            client.get_cash()


# ── Tests de posiciones ────────────────────────────────────────────────────────

class TestCocosGetPositions:

    def _client_with_app(self, app):
        client = CocosClient("u@t.com", "p")
        client._app = app
        return client

    def test_returns_list_of_cocos_positions(self):
        client = self._client_with_app(_make_cocos_app())
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert isinstance(positions, list)
        assert len(positions) == 1
        assert isinstance(positions[0], CocosPosition)

    def test_fci_fields_mapped_correctly(self):
        app = _make_cocos_app([_make_position(
            ticker="COCOSPPA",
            name="Cocos Pesos Plus",
            instrument_type="FCI",
            quantity=4862074.52,
            last=1320.813,
            average_price=1234.839,
        )])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        p = positions[0]
        assert p.ticker == "COCOSPPA"
        assert p.description == "Cocos Pesos Plus"
        assert p.asset_type == "FCI"
        assert p.quantity == Decimal("4862074.52")
        assert p.ppc_ars == Decimal("1234.839")
        # current_price_usd = last / mep
        expected_price = Decimal("1320.813") / Decimal(str(MEP))
        assert abs(p.current_price_usd - expected_price) < Decimal("0.000001")

    def test_last_none_uses_previous_price(self):
        """Si last es None (mercado cerrado) → usar previous_price."""
        app = _make_cocos_app([_make_position(last=None, previous_price=1280.0)])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert len(positions) == 1
        expected = Decimal("1280.0") / Decimal(str(MEP))
        assert abs(positions[0].current_price_usd - expected) < Decimal("0.000001")

    def test_both_prices_none_skips_position(self, caplog):
        """Si last y previous_price son None → posición excluida + warning."""
        import logging
        app = _make_cocos_app([_make_position(last=None, previous_price=None)])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            with caplog.at_level(logging.WARNING):
                positions = client.get_positions()

        assert positions == []
        assert any("COCOSPPA" in r.message for r in caplog.records)

    def test_zero_quantity_skips_position(self):
        """Posición con quantity=0 → excluida."""
        app = _make_cocos_app([_make_position(quantity=0)])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert positions == []

    def test_unknown_instrument_type_returns_none_asset_type_with_warning(self, caplog):
        """Tipo desconocido → asset_type=None + raw_instrument_type set + warning.
        La posición NO se skipea en el cliente — el sync layer decide qué hacer."""
        import logging
        app = _make_cocos_app([_make_position(instrument_type="OPCION")])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            with caplog.at_level(logging.WARNING):
                positions = client.get_positions()

        assert len(positions) == 1
        assert positions[0].asset_type is None
        assert positions[0].raw_instrument_type == "OPCION"
        assert any("OPCION" in r.message for r in caplog.records)

    def test_annual_yield_from_default_yields_not_result_pct(self):
        """annual_yield_pct viene de DEFAULT_YIELDS, no de result_percentage del PoC."""
        app = _make_cocos_app([_make_position(
            instrument_type="FCI",
            result_percentage=0.999,  # valor absurdo — no debe usarse
        )])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert positions[0].annual_yield_pct == DEFAULT_YIELDS["FCI"]
        assert positions[0].annual_yield_pct != Decimal("0.999")

    def test_multiple_positions_all_mapped(self):
        app = _make_cocos_app([
            _make_position(ticker="COCOSPPA", quantity=1000.0),
            _make_position(ticker="COCOSMMA", quantity=2000.0, name="Cocos Money Market"),
        ])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert len(positions) == 2
        tickers = [p.ticker for p in positions]
        assert "COCOSPPA" in tickers
        assert "COCOSMMA" in tickers

    def test_empty_portfolio_returns_empty_list(self):
        app = _make_cocos_app([])
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            positions = client.get_positions()

        assert positions == []

    def test_api_exception_raises_through(self):
        """Si historic_performance falla → la excepción sube (el caller decide)."""
        app = _make_cocos_app()
        app.historic_performance.side_effect = Exception("Cloudflare timeout")
        client = self._client_with_app(app)
        with patch.object(client, "_get_mep", return_value=MEP):
            with pytest.raises(Exception, match="Cloudflare"):
                client.get_positions()


# ── Tests de cash ──────────────────────────────────────────────────────────────

class TestCocosGetCash:

    def _client_with_app(self, app):
        client = CocosClient("u@t.com", "p")
        client._app = app
        return client

    def test_returns_ars_and_usd_from_buying_power_ci(self):
        app = _make_cocos_app(buying_power=_make_buying_power(ars=5000.0, usd=150.0))
        client = self._client_with_app(app)
        cash = client.get_cash()

        assert cash["ars"] == Decimal("5000.0")
        assert cash["usd"] == Decimal("150.0")

    def test_zero_cash_returns_zeros(self):
        app = _make_cocos_app(buying_power=_make_buying_power(ars=0, usd=0))
        client = self._client_with_app(app)
        cash = client.get_cash()

        assert cash["ars"] == Decimal("0")
        assert cash["usd"] == Decimal("0")

    def test_api_exception_returns_zeros(self):
        """Si buying_power falla → retorna ceros, no crash."""
        app = _make_cocos_app()
        app.buying_power.side_effect = Exception("timeout")
        client = self._client_with_app(app)
        cash = client.get_cash()

        assert cash["ars"] == Decimal("0")
        assert cash["usd"] == Decimal("0")

    def test_uses_ci_not_24hs(self):
        """Saldo disponible = CI (inmediato), no 24hs."""
        app = _make_cocos_app(buying_power={
            "CI":   {"ars": 9999.0, "usd": 50.0, "ext": 0},
            "24hs": {"ars": 1.0,    "usd": 1.0,  "ext": 0},
        })
        client = self._client_with_app(app)
        cash = client.get_cash()

        assert cash["ars"] == Decimal("9999.0")
        assert cash["usd"] == Decimal("50.0")


# ── Tests de MEP ───────────────────────────────────────────────────────────────

class TestCocosGetMep:

    def test_get_mep_returns_venta(self):
        client = CocosClient("u@t.com", "p")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"venta": 1435.5, "compra": 1430.0}
        with patch("httpx.get", return_value=mock_resp):
            mep = client._get_mep()
        assert mep == 1435.5

    def test_get_mep_fallback_on_error(self):
        client = CocosClient("u@t.com", "p")
        with patch("httpx.get", side_effect=Exception("network")):
            mep = client._get_mep()
        assert mep == 1430.0


# ── Tests de normalización de tipos ───────────────────────────────────────────

class TestNormalizeInstrumentType:

    def test_fci_maps_to_fci(self):
        assert _normalize_instrument_type("FCI") == "FCI"

    def test_unknown_maps_to_none(self):
        assert _normalize_instrument_type("OPCION") is None
        assert _normalize_instrument_type("FUTURO") is None
        assert _normalize_instrument_type("") is None

    def test_case_insensitive(self):
        assert _normalize_instrument_type("fci") == "FCI"
        assert _normalize_instrument_type("Fci") == "FCI"
