"""
Tests TDD para BinanceClient.
Escritos ANTES de la implementación — deben fallar en RED hasta que binance_client.py exista.
"""
import hashlib
import hmac
import time
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.binance_client import BinanceAuthError, BinanceClient, BinancePosition


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return BinanceClient(api_key="test_api_key", secret="test_secret")


def _mock_account(balances: list[dict]) -> dict:
    return {
        "accountType": "SPOT",
        "permissions": ["SPOT"],
        "balances": balances,
    }


def _mock_ticker(prices: dict[str, str]) -> list[dict]:
    return [{"symbol": k, "price": v} for k, v in prices.items()]


# ── Auth / firma ───────────────────────────────────────────────────────────────

def test_hmac_signature_present(client):
    """El request debe incluir signature y X-MBX-APIKEY."""
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account([])
        mock_get.return_value = mock_resp

        client.validate()

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        params = call_kwargs.kwargs.get("params", {})
        assert headers.get("X-MBX-APIKEY") == "test_api_key"
        assert "signature" in params


def test_auth_error_on_401(client):
    """HTTP 401 debe lanzar BinanceAuthError."""
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"code": -2014, "msg": "API-key format invalid."}
        mock_get.return_value = mock_resp

        with pytest.raises(BinanceAuthError):
            client.validate()


def test_auth_error_on_403(client):
    """HTTP 403 debe lanzar BinanceAuthError."""
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        with pytest.raises(BinanceAuthError):
            client.validate()


# ── Filtros de assets ──────────────────────────────────────────────────────────

def test_ld_asset_filtered(client):
    """Assets con prefijo LD (Lending) deben ser ignorados silenciosamente."""
    balances = [
        {"asset": "LDBNB", "free": "0.5", "locked": "0.0"},
        {"asset": "LDBTC", "free": "0.001", "locked": "0.0"},
    ]
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        positions = client.get_positions()
        assert positions == []


def test_ars_asset_filtered(client):
    """ARS (pesos argentinos en Binance) debe ser ignorado."""
    balances = [{"asset": "ARS", "free": "646.0", "locked": "0.0"}]
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        positions = client.get_positions()
        assert positions == []


def test_zero_balance_skipped(client):
    """Assets con free=0 y locked=0 deben ser ignorados."""
    balances = [{"asset": "BTC", "free": "0.0", "locked": "0.0"}]
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        positions = client.get_positions()
        assert positions == []


def test_unknown_asset_skips_with_warning(client, caplog):
    """Asset desconocido (no en _COINGECKO_ID) debe hacer skip con logger.warning."""
    balances = [{"asset": "SHIB2049", "free": "1000000.0", "locked": "0.0"}]
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        import logging
        with caplog.at_level(logging.WARNING, logger="buildfuture.binance"):
            positions = client.get_positions()

        assert positions == []
        assert any("SHIB2049" in r.message for r in caplog.records)


# ── Stablecoins ────────────────────────────────────────────────────────────────

def test_stablecoin_price_fixed(client):
    """USDT debe tener price_usd=$1.0 sin llamar a ningún ticker externo."""
    balances = [{"asset": "USDT", "free": "19.98", "locked": "0.0"}]

    call_count = {"n": 0}

    def mock_get(url, **kwargs):
        call_count["n"] += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        return mock_resp

    with patch("app.services.binance_client.httpx.get", side_effect=mock_get):
        positions = client.get_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.ticker == "USDT"
    assert p.current_price_usd == Decimal("1.0")
    assert p.annual_yield_pct == Decimal("0")
    assert p.asset_type == "CRYPTO"
    # Solo 1 call (el de account), no llama a ticker
    assert call_count["n"] == 1


def test_usdc_stablecoin(client):
    """USDC también es stablecoin con precio $1.0."""
    balances = [{"asset": "USDC", "free": "5.0", "locked": "0.0"}]
    with patch("app.services.binance_client.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        positions = client.get_positions()
        assert len(positions) == 1
        assert positions[0].current_price_usd == Decimal("1.0")


# ── Posiciones crypto ──────────────────────────────────────────────────────────

def test_get_positions_btc_ok(client):
    """BTC con balance > 0 y precio de CoinGecko → BinancePosition correcta."""
    balances = [{"asset": "BTC", "free": "0.001", "locked": "0.0"}]

    with patch("app.services.binance_client.httpx.get") as mock_account_get, \
         patch("app.services.binance_client.get_price_usd", return_value=84000.0), \
         patch("app.services.binance_client.get_yield_30d", return_value=0.25):

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_account_get.return_value = mock_resp

        positions = client.get_positions()

    assert len(positions) == 1
    p = positions[0]
    assert p.ticker == "BTC"
    assert p.asset_type == "CRYPTO"
    assert p.quantity == Decimal("0.001")
    assert p.current_price_usd == Decimal("84000.0")
    assert p.annual_yield_pct == Decimal("0.25")
    assert p.ppc_ars == Decimal("0")


def test_get_positions_free_plus_locked(client):
    """quantity = free + locked."""
    balances = [{"asset": "BTC", "free": "0.5", "locked": "0.1"}]

    with patch("app.services.binance_client.httpx.get") as mock_get, \
         patch("app.services.binance_client.get_price_usd", return_value=84000.0), \
         patch("app.services.binance_client.get_yield_30d", return_value=0.0):

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_account(balances)
        mock_get.return_value = mock_resp

        positions = client.get_positions()

    assert positions[0].quantity == Decimal("0.6")


# ── PPC desde myTrades ─────────────────────────────────────────────────────────

def test_ppc_from_usdt_trades(client):
    """USDT comprado con ARS: PPC en USD = precio_ars / mep."""
    trades = [
        {"isBuyer": True, "qty": "20.0", "price": "1500.0", "quoteQty": "30000.0"},
        {"isBuyer": True, "qty": "10.0", "price": "1400.0", "quoteQty": "14000.0"},
    ]
    # PPC_ARS = (20*1500 + 10*1400) / 30 = 44000/30 = 1466.67
    # PPC_USD = 1466.67 / 1430 = ~1.026

    def mock_signed_get(endpoint, params=None):
        # USDTUSDT no existe — simular error para que caiga en USDTARS
        if params and params.get("symbol") == "USDTUSDT":
            raise Exception("Invalid symbol")
        return trades

    with patch.object(client, "_signed_get", side_effect=mock_signed_get):
        ppc = client._get_ppc_usd("USDT", mep=1430.0)

    expected_ars = (20 * 1500 + 10 * 1400) / 30
    expected_usd = expected_ars / 1430.0
    assert abs(float(ppc) - expected_usd) < 0.001


def test_ppc_no_trades_returns_zero(client):
    """Sin trades para el asset, retorna 0.0."""
    with patch.object(client, "_signed_get", return_value=[]):
        ppc = client._get_ppc_usd("ETH", mep=1430.0)
    assert ppc == 0.0


# ── Snapshot history ───────────────────────────────────────────────────────────

def test_snapshot_history_filters_ld(client):
    """Los snapshots no deben incluir assets LD* ni ARS."""
    import time as _time
    snap_data = {
        "code": 200,
        "snapshotVos": [
            {
                "updateTime": int(_time.time() * 1000),
                "data": {
                    "balances": [
                        {"asset": "USDT", "free": "20.0", "locked": "0"},
                        {"asset": "LDBNB", "free": "0.5", "locked": "0"},
                        {"asset": "ARS", "free": "646.0", "locked": "0"},
                    ]
                }
            }
        ]
    }
    with patch.object(client, "_signed_get", return_value=snap_data):
        history = client.get_snapshot_history()

    assert len(history) == 1
    snap = history[0]
    assert "USDT" in snap["balances"]
    assert "LDBNB" not in snap["balances"]
    assert "ARS" not in snap["balances"]


def test_snapshot_history_empty_balances_skipped(client):
    """Snapshots sin balances con saldo > 0 no deben aparecer."""
    import time as _time
    snap_data = {
        "code": 200,
        "snapshotVos": [
            {
                "updateTime": int(_time.time() * 1000),
                "data": {
                    "balances": [
                        {"asset": "BTC", "free": "0.0", "locked": "0.0"},
                    ]
                }
            }
        ]
    }
    with patch.object(client, "_signed_get", return_value=snap_data):
        history = client.get_snapshot_history()

    assert history == []
