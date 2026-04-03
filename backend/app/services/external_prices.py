"""
Precios de ETFs y acciones internacionales vía Yahoo Finance.
Reutiliza la misma lógica que usa iol_client para CEDEARs.
"""

import logging
import httpx

logger = logging.getLogger("buildfuture.external")

_YF_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def validate_ticker(ticker: str) -> dict | None:
    """
    Valida que el ticker existe en Yahoo Finance y retorna info básica.
    Retorna None si no se encuentra.
    """
    try:
        r = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}",
            params={"interval": "1d", "range": "5d"},
            headers=_YF_HEADERS,
            timeout=10,
        )
        if not r.is_success:
            return None
        result = r.json()["chart"]["result"]
        if not result:
            return None
        meta = result[0]["meta"]
        price = meta.get("regularMarketPrice")
        if not price:
            return None
        return {
            "ticker": ticker.upper(),
            "name": meta.get("longName") or meta.get("shortName") or ticker.upper(),
            "price_usd": float(price),
            "currency": meta.get("currency", "USD"),
            "exchange": meta.get("exchangeName", ""),
        }
    except Exception as e:
        logger.warning("Yahoo validate_ticker falló (%s): %s", ticker, e)
        return None


def get_price_usd(ticker: str) -> float | None:
    """Precio actual en USD para el ticker dado."""
    info = validate_ticker(ticker)
    return info["price_usd"] if info else None


def get_yield_30d(ticker: str) -> float:
    """
    TNA implícita de la variación de precio de los últimos 30 días.
    Formula: (1 + rendimiento_30d)^(365/30) - 1
    """
    try:
        r = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}",
            params={"interval": "1d", "range": "1mo"},
            headers=_YF_HEADERS,
            timeout=10,
        )
        if not r.is_success:
            return 0.0
        result = r.json()["chart"]["result"]
        if not result:
            return 0.0
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return 0.0
        price_start = closes[0]
        price_end = closes[-1]
        if price_start <= 0:
            return 0.0
        rendimiento_30d = (price_end - price_start) / price_start
        tna = (1 + rendimiento_30d) ** (365 / 30) - 1
        return round(float(tna), 4)
    except Exception as e:
        logger.warning("Yahoo yield_30d falló (%s): %s", ticker, e)
        return 0.0
