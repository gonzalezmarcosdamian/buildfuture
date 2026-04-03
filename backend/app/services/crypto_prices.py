"""
CoinGecko free API — precios y yield histórico de criptomonedas.
Sin API key requerida. Rate limit ~15 req/min en el tier público.
"""

import logging
import httpx
from decimal import Decimal

logger = logging.getLogger("buildfuture.crypto")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_HEADERS = {"Accept": "application/json", "User-Agent": "BuildFuture/0.9"}


def search_coins(query: str) -> list[dict]:
    """Busca monedas por nombre o símbolo. Retorna lista [{id, name, symbol, market_cap_rank}]."""
    try:
        r = httpx.get(
            f"{COINGECKO_BASE}/search",
            params={"query": query},
            headers=_HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        coins = r.json().get("coins", [])
        return [
            {
                "id": c["id"],
                "name": c["name"],
                "symbol": c["symbol"].upper(),
                "market_cap_rank": c.get("market_cap_rank"),
            }
            for c in coins[:10]
        ]
    except Exception as e:
        logger.warning("CoinGecko search falló: %s", e)
        return []


def get_price_usd(coingecko_id: str) -> float | None:
    """Precio actual en USD para el ID de CoinGecko dado."""
    try:
        r = httpx.get(
            f"{COINGECKO_BASE}/simple/price",
            params={"ids": coingecko_id, "vs_currencies": "usd"},
            headers=_HEADERS,
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()
        return data.get(coingecko_id, {}).get("usd")
    except Exception as e:
        logger.warning("CoinGecko price falló (%s): %s", coingecko_id, e)
        return None


def get_yield_30d(coingecko_id: str) -> float:
    """
    TNA implícita calculada de la variación de precio de los últimos 30 días.
    Formula: (1 + rendimiento_30d)^(365/30) - 1
    Retorna 0.0 si falla — el portafolio no se rompe.
    """
    try:
        r = httpx.get(
            f"{COINGECKO_BASE}/coins/{coingecko_id}/market_chart",
            params={"vs_currency": "usd", "days": "30", "interval": "daily"},
            headers=_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if len(prices) < 2:
            return 0.0
        price_start = prices[0][1]
        price_end = prices[-1][1]
        if price_start <= 0:
            return 0.0
        rendimiento_30d = (price_end - price_start) / price_start
        tna = (1 + rendimiento_30d) ** (365 / 30) - 1
        return round(float(tna), 4)
    except Exception as e:
        logger.warning("CoinGecko yield_30d falló (%s): %s", coingecko_id, e)
        return 0.0
