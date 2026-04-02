"""
Fetchers de precios e índices históricos para la reconstrucción de portfolio.

Estrategia de fuentes:
- CEDEAR / ETF / CRYPTO : Yahoo Finance  (1 call por ticker → 2 años de diarios)
- MEP histórico         : bluelytics.com.ar (1 call por mes-inicio, interpolación lineal)
- LETRA                 : capitalización diaria desde ppc_ars (sin llamadas externas)
- BOND / ON             : interpolación lineal ppc→precio_actual (sin llamadas externas)
- FCI                   : precio actual como proxy (sin llamadas externas)
"""
import logging
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx

logger = logging.getLogger("buildfuture.historical_prices")

_YF_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BuildFuture/1.0)"}
_BLUELYTICS_BASE = "https://api.bluelytics.com.ar/v2"


# ── Yahoo Finance ─────────────────────────────────────────────────────────────

def fetch_yahoo_daily(ticker: str, days: int = 730) -> dict[date, float]:
    """
    Descarga el historial diario de cierre en USD para un ticker de Yahoo Finance.
    Un solo HTTP call devuelve hasta `days` días de historia.
    Retorna {date: close_price_usd}. Dict vacío si el ticker no existe.
    """
    range_str = "2y" if days >= 730 else ("1y" if days >= 365 else "6mo")
    try:
        r = httpx.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker.upper()}",
            params={"interval": "1d", "range": range_str},
            headers=_YF_HEADERS,
            timeout=12,
        )
        if not r.is_success:
            logger.debug("Yahoo %s: HTTP %s", ticker, r.status_code)
            return {}

        data = r.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return {}

        chart = result[0]
        timestamps = chart.get("timestamp", [])
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])

        out: dict[date, float] = {}
        for ts, close in zip(timestamps, closes):
            if close is None or close <= 0:
                continue
            d = date.fromtimestamp(ts)
            out[d] = float(close)

        logger.info("Yahoo %s: %d cierres (%s → %s)",
                    ticker, len(out),
                    min(out) if out else "-", max(out) if out else "-")
        return out
    except Exception as e:
        logger.warning("Yahoo fetch_daily falló (%s): %s", ticker, e)
        return {}


def fetch_yahoo_batch(tickers: list[str], days: int = 730) -> dict[str, dict[date, float]]:
    """Descarga historial para una lista de tickers con rate limiting 200ms."""
    result: dict[str, dict[date, float]] = {}
    for ticker in tickers:
        result[ticker] = fetch_yahoo_daily(ticker, days)
        time.sleep(0.2)
    return result


def lookup_price(history: dict[date, float], target: date) -> float | None:
    """Precio más cercano hacia atrás (tolera hasta 5 días por feriados/fines de semana)."""
    for delta in range(6):
        d = target - timedelta(days=delta)
        if d in history:
            return history[d]
    return None


# ── Bluelytics MEP ────────────────────────────────────────────────────────────

_mep_cache: dict[date, float] = {}


def fetch_bluelytics_range(start: date, end: date, fallback_mep: float = 1430.0) -> dict[date, float]:
    """
    MEP histórico por día via bluelytics (mensual) + interpolación lineal.
    Máximo ~24 llamadas HTTP para 2 años de historia.
    """
    month_starts: list[date] = []
    cur = start.replace(day=1)
    while cur <= end:
        month_starts.append(cur)
        cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)

    for ms in month_starts:
        if ms in _mep_cache:
            continue
        _mep_cache[ms] = _fetch_bluelytics_day(str(ms), fallback_mep)
        time.sleep(0.15)

    anchors = sorted((d, v) for d, v in _mep_cache.items()
                     if start <= d <= end + timedelta(days=31))
    if not anchors:
        return {start + timedelta(days=i): fallback_mep
                for i in range((end - start).days + 1)}

    result: dict[date, float] = {}
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        result[d] = _interpolate_mep(anchors, d, fallback_mep)
    return result


def _fetch_bluelytics_day(fecha_str: str, fallback: float) -> float:
    try:
        r = httpx.get(f"{_BLUELYTICS_BASE}/historical?day={fecha_str}", timeout=8)
        if r.status_code == 200:
            data = r.json()
            blue = data.get("blue", {}).get("value_sell", 0)
            oficial = data.get("official", {}).get("value_sell", 0)
            if blue and oficial:
                return float((blue + oficial) / 2)
    except Exception as e:
        logger.debug("Bluelytics %s: %s", fecha_str, e)
    return fallback


def _interpolate_mep(anchors: list[tuple[date, float]], target: date, fallback: float) -> float:
    before = [(d, v) for d, v in anchors if d <= target]
    after  = [(d, v) for d, v in anchors if d > target]
    if not before:
        return after[0][1] if after else fallback
    if not after:
        return before[-1][1]
    d0, v0 = before[-1]
    d1, v1 = after[0]
    span = (d1 - d0).days
    if span == 0:
        return v0
    return v0 + (v1 - v0) * (target - d0).days / span


# ── Precios sin fuente externa ────────────────────────────────────────────────

def letra_price_usd_at(ppc_ars: float, annual_yield: float,
                        purchase_date: date, target_date: date, mep: float) -> float:
    """Precio estimado de LECAP en USD: capitalización diaria desde ppc_ars."""
    if mep <= 0:
        return 0.0
    days = max(0, (target_date - purchase_date).days)
    daily_rate = (1 + annual_yield) ** (1 / 365) - 1
    return ppc_ars * ((1 + daily_rate) ** days) / mep


def bond_price_usd_at(ppc_usd: float, current_usd: float,
                       purchase_date: date, current_date: date, target_date: date) -> float:
    """Precio estimado de BOND/ON: interpolación lineal ppc_usd → precio_actual."""
    total_days = max(1, (current_date - purchase_date).days)
    frac = min(1.0, max(0.0, (target_date - purchase_date).days / total_days))
    return ppc_usd + frac * (current_usd - ppc_usd)
