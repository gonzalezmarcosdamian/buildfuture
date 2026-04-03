"""
Binance client — integración read-only via API Key + Secret.
Auth: HMAC-SHA256 firmado por request. Sin sesión, sin 2FA interactivo.
auto_sync_enabled = True siempre.

Scope Iter 1:
- Balances spot (GET /api/v3/account)
- Precios actuales via CoinGecko (ya en stack)
- Yield real 30d via CoinGecko
- PPC desde myTrades
- Historial 30d via accountSnapshot
"""

import hashlib
import hmac as _hmac
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx

from app.services.crypto_prices import (
    get_price_usd,
    get_yield_30d,
)  # noqa: F401 — re-exported for mocking in tests

logger = logging.getLogger("buildfuture.binance")

_BASE = "https://api.binance.com"

# Mapping asset Binance → coingecko_id
_COINGECKO_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "MATIC": "matic-network",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOGE": "dogecoin",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "TRX": "tron",
}

_STABLECOINS: set[str] = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}
_SKIP_PREFIXES: tuple[str, ...] = ("LD",)  # Flexible Earn
_SKIP_ASSETS: set[str] = {"ARS", "BRL", "EUR", "GBP"}  # fiat


@dataclass
class BinancePosition:
    ticker: str
    asset_type: str  # siempre "CRYPTO"
    quantity: Decimal
    current_price_usd: Decimal
    avg_purchase_price_usd: Decimal  # PPC en USD desde myTrades (0 si no hay trades)
    ppc_ars: Decimal  # siempre 0 — Binance no maneja ARS
    annual_yield_pct: Decimal  # yield 30d anualizado de CoinGecko (0 para stablecoins)
    current_value_ars: Decimal  # 0 — sin MEP en esta capa; se calcula en sync
    raw_data: dict = field(default_factory=dict)


class BinanceAuthError(Exception):
    pass


class BinanceClient:
    def __init__(self, api_key: str, secret: str):
        self._api_key = api_key
        self._secret = secret

    def _signed_get(self, endpoint: str, params: dict | None = None) -> dict | list:
        """GET autenticado con firma HMAC-SHA256."""
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(p)
        signature = _hmac.new(
            self._secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        r = httpx.get(
            f"{_BASE}{endpoint}",
            params={**p, "signature": signature},
            headers={"X-MBX-APIKEY": self._api_key},
            timeout=10,
        )
        if r.status_code in (401, 403):
            raise BinanceAuthError(
                f"Binance API Key inválida o revocada (HTTP {r.status_code})"
            )
        r.raise_for_status()
        return r.json()

    def validate(self) -> bool:
        """Verifica que las credenciales son válidas. Lanza BinanceAuthError si no."""
        self._signed_get("/api/v3/account")
        return True

    def get_positions(self) -> list[BinancePosition]:
        """
        Trae balances spot y los convierte a BinancePosition.
        - Filtra LD* (Lending), ARS y otros fiat silenciosamente.
        - Stablecoins: precio $1.0, yield 0%.
        - Crypto conocida: precio + yield desde CoinGecko.
        - Desconocida: skip con logger.warning.
        """
        data = self._signed_get("/api/v3/account")
        balances = data.get("balances", []) if isinstance(data, dict) else []

        positions = []
        for b in balances:
            asset = b.get("asset", "")
            qty = Decimal(str(b.get("free", 0))) + Decimal(str(b.get("locked", 0)))

            if qty <= 0:
                continue
            if any(asset.startswith(p) for p in _SKIP_PREFIXES):
                continue
            if asset in _SKIP_ASSETS:
                continue

            if asset in _STABLECOINS:
                price = Decimal("1.0")
                yield_pct = Decimal("0")
            elif asset in _COINGECKO_ID:
                cg_id = _COINGECKO_ID[asset]
                raw_price = get_price_usd(cg_id)
                if raw_price is None:
                    logger.warning(
                        "BinanceClient: %s sin precio CoinGecko — skip", asset
                    )
                    continue
                price = Decimal(str(raw_price))
                raw_yield = get_yield_30d(cg_id)
                yield_pct = Decimal(str(raw_yield))
            else:
                logger.warning(
                    "BinanceClient: asset '%s' no mapeado en _COINGECKO_ID — skip",
                    asset,
                )
                continue

            positions.append(
                BinancePosition(
                    ticker=asset,
                    asset_type="CRYPTO",
                    quantity=qty,
                    current_price_usd=price,
                    avg_purchase_price_usd=Decimal(
                        "0"
                    ),  # se enriquece luego con _get_ppc_usd
                    ppc_ars=Decimal("0"),
                    annual_yield_pct=yield_pct,
                    current_value_ars=Decimal("0"),
                    raw_data=b,
                )
            )

        logger.info("BinanceClient: %d posiciones obtenidas", len(positions))
        return positions

    def _get_ppc_usd(self, asset: str, mep: float) -> float:
        """
        PPC en USD calculado desde myTrades.
        - Para crypto: par {asset}USDT → precio promedio ponderado.
        - Para USDT: par USDTARS → precio ARS promedio / mep.
        - Retorna 0.0 si no hay trades o par inválido.
        """
        # Intentar par directo contra USDT
        for symbol in [f"{asset}USDT"]:
            try:
                trades = self._signed_get(
                    "/api/v3/myTrades", {"symbol": symbol, "limit": 500}
                )
                if not isinstance(trades, list) or not trades:
                    continue
                buys = [t for t in trades if t.get("isBuyer")]
                if not buys:
                    continue
                total_qty = sum(float(t["qty"]) for t in buys)
                total_cost = sum(float(t["qty"]) * float(t["price"]) for t in buys)
                if total_qty > 0:
                    return total_cost / total_qty
            except Exception:
                continue

        # USDT comprado con ARS
        if asset == "USDT":
            try:
                trades = self._signed_get(
                    "/api/v3/myTrades", {"symbol": "USDTARS", "limit": 500}
                )
                if isinstance(trades, list):
                    buys = [t for t in trades if t.get("isBuyer")]
                    if buys:
                        total_qty = sum(float(t["qty"]) for t in buys)
                        total_ars = sum(
                            float(t["qty"]) * float(t["price"]) for t in buys
                        )
                        avg_ars = total_ars / total_qty
                        return avg_ars / mep if mep > 0 else 0.0
            except Exception:
                pass

        return 0.0

    def get_snapshot_history(self) -> list[dict]:
        """
        Retorna hasta 30 snapshots diarios de balance spot.
        Cada snapshot: {"date": date, "balances": {asset: float}}
        Filtra LD*, ARS y balances <= 0.
        """
        data = self._signed_get(
            "/sapi/v1/accountSnapshot", {"type": "SPOT", "limit": 30}
        )
        if isinstance(data, list):
            snap_list = data
        else:
            snap_list = data.get("snapshotVos", [])

        result = []
        for snap in snap_list:
            update_time = snap.get("updateTime", 0)
            snap_date = date.fromtimestamp(update_time / 1000)
            balances_raw = snap.get("data", {}).get("balances", [])

            balances: dict[str, float] = {}
            for b in balances_raw:
                asset = b.get("asset", "")
                qty = float(b.get("free", 0)) + float(b.get("locked", 0))
                if qty <= 0:
                    continue
                if any(asset.startswith(p) for p in _SKIP_PREFIXES):
                    continue
                if asset in _SKIP_ASSETS:
                    continue
                balances[asset] = qty

            if balances:
                result.append({"date": snap_date, "balances": balances})

        return result
