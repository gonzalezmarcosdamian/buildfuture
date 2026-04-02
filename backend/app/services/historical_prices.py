"""
Fetchers de precios e índices históricos con caché en DB.

Estrategia de caché (compartida entre todos los usuarios):
  price_history  — ticker + fecha + precio USD (Yahoo Finance)
  mep_history    — fecha + MEP ARS/USD (bluelytics)

Flujo por ticker:
  1. Consultar DB: ¿qué fechas ya están cacheadas?
  2. Calcular fechas faltantes
  3. Fetch Yahoo solo para lo que falta → INSERT en price_history
  4. Devolver el historial completo desde DB

Esto hace que el segundo usuario que sincroniza IOL con los mismos
tickers (GGAL, AL30...) no pague ningún costo de red.
"""
import logging
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import PriceHistory, MepHistory

logger = logging.getLogger("buildfuture.historical_prices")

_YF_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BuildFuture/1.0)"}
_BLUELYTICS_BASE = "https://api.bluelytics.com.ar/v2"

HISTORY_DAYS = 730


# ── Yahoo Finance ─────────────────────────────────────────────────────────────

def get_prices_cached(
    db: Session,
    ticker: str,
    start: date,
    end: date,
) -> dict[date, float]:
    """
    Devuelve {date: price_usd} para el ticker en [start, end].
    Consulta primero price_history en DB; solo llama a Yahoo para lo que falta.
    """
    # 1. Qué fechas laborables necesitamos
    needed = {
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < 5
    }

    # 2. Qué ya está en la DB
    cached_rows = db.query(PriceHistory).filter(
        PriceHistory.ticker == ticker,
        PriceHistory.price_date >= start,
        PriceHistory.price_date <= end,
    ).all()
    cached: dict[date, float] = {r.price_date: float(r.price_usd) for r in cached_rows}

    # 3. Fechas que faltan
    missing_dates = needed - set(cached.keys())

    if missing_dates:
        logger.info("PriceCache: %s — %d fechas en DB, %d a descargar",
                    ticker, len(cached), len(missing_dates))
        fetched = _fetch_yahoo_range(ticker, min(missing_dates), max(missing_dates))

        # INSERT solo las que realmente trajo Yahoo (puede no tener todas las laborables)
        new_rows = []
        for d, price in fetched.items():
            if d not in cached:
                new_rows.append(PriceHistory(
                    ticker=ticker,
                    price_date=d,
                    price_usd=Decimal(str(round(price, 4))),
                    source="YAHOO",
                ))
                cached[d] = price

        if new_rows:
            # INSERT OR IGNORE equivalente — usamos merge para manejar duplicados
            for row in new_rows:
                try:
                    db.merge(row)
                except Exception:
                    pass
            try:
                db.flush()
                logger.info("PriceCache: %s — %d nuevos precios guardados", ticker, len(new_rows))
            except Exception as e:
                db.rollback()
                logger.warning("PriceCache flush falló (%s): %s", ticker, e)
    else:
        logger.debug("PriceCache: %s — todo cacheado (%d fechas)", ticker, len(cached))

    return cached


def get_prices_batch_cached(
    db: Session,
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, dict[date, float]]:
    """
    Versión batch de get_prices_cached con rate limiting entre tickers.
    Retorna {ticker: {date: price_usd}}.
    """
    result: dict[str, dict[date, float]] = {}
    for ticker in tickers:
        result[ticker] = get_prices_cached(db, ticker, start, end)
        time.sleep(0.15)  # rate limit gentil entre tickers
    return result


def lookup_price(history: dict[date, float], target: date) -> float | None:
    """Precio más cercano hacia atrás (tolera hasta 5 días por feriados/fin de semana)."""
    for delta in range(6):
        d = target - timedelta(days=delta)
        if d in history:
            return history[d]
    return None


def _fetch_yahoo_range(ticker: str, start: date, end: date) -> dict[date, float]:
    """
    Descarga precios diarios de Yahoo Finance para el rango [start, end].
    Un solo HTTP call (range=2y cubre hasta 2 años).
    """
    days = (end - start).days
    range_str = "2y" if days >= 700 else ("1y" if days >= 350 else "6mo")
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

        result = r.json().get("chart", {}).get("result")
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
            if start <= d <= end:
                out[d] = float(close)

        logger.info("Yahoo %s: %d cierres descargados", ticker, len(out))
        return out
    except Exception as e:
        logger.warning("Yahoo _fetch_range falló (%s): %s", ticker, e)
        return {}


# ── MEP histórico ─────────────────────────────────────────────────────────────

def get_mep_cached(
    db: Session,
    start: date,
    end: date,
    fallback_mep: float = 1430.0,
) -> dict[date, float]:
    """
    Devuelve {date: mep_float} para cada día en [start, end].
    Caché en mep_history. Solo llama a bluelytics para meses faltantes.
    Interpola linealmente entre puntos mensuales para obtener valores diarios.
    """
    # 1. Identificar meses que necesitamos como anchors
    month_starts = _month_starts_between(start, end)

    # 2. Qué meses ya están en DB
    cached_mep = db.query(MepHistory).filter(
        MepHistory.price_date >= start.replace(day=1),
        MepHistory.price_date <= end,
    ).all()
    anchors: dict[date, float] = {r.price_date: float(r.mep_rate) for r in cached_mep}

    # 3. Fetch meses faltantes
    missing_months = [ms for ms in month_starts if ms not in anchors]
    if missing_months:
        logger.info("MepCache: %d meses a descargar de bluelytics", len(missing_months))
        for ms in missing_months:
            rate = _fetch_bluelytics_day(str(ms), fallback_mep)
            anchors[ms] = rate
            try:
                db.merge(MepHistory(
                    price_date=ms,
                    mep_rate=Decimal(str(round(rate, 2))),
                    source="BLUELYTICS",
                ))
            except Exception:
                pass
            time.sleep(0.15)
        try:
            db.flush()
        except Exception as e:
            db.rollback()
            logger.warning("MepCache flush falló: %s", e)

    # 4. Interpolar linealmente para cada día en [start, end]
    sorted_anchors = sorted(anchors.items())
    result: dict[date, float] = {}
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        result[d] = _interpolate(sorted_anchors, d, fallback_mep)
    return result


def _month_starts_between(start: date, end: date) -> list[date]:
    months = []
    cur = start.replace(day=1)
    while cur <= end:
        months.append(cur)
        cur = cur.replace(month=cur.month + 1) if cur.month < 12 else cur.replace(year=cur.year + 1, month=1)
    return months


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


def _interpolate(anchors: list[tuple[date, float]], target: date, fallback: float) -> float:
    before = [(d, v) for d, v in anchors if d <= target]
    after  = [(d, v) for d, v in anchors if d > target]
    if not before:
        return after[0][1] if after else fallback
    if not after:
        return before[-1][1]
    d0, v0 = before[-1]
    d1, v1 = after[0]
    span = (d1 - d0).days
    return v0 if span == 0 else v0 + (v1 - v0) * (target - d0).days / span


# ── Precios estimados sin fuente externa ──────────────────────────────────────

def letra_price_usd_at(ppc_ars: float, annual_yield: float,
                        purchase_date: date, target_date: date, mep: float) -> float:
    if mep <= 0:
        return 0.0
    days = max(0, (target_date - purchase_date).days)
    daily_rate = (1 + annual_yield) ** (1 / 365) - 1
    return ppc_ars * ((1 + daily_rate) ** days) / mep


def bond_price_usd_at(ppc_usd: float, current_usd: float,
                       purchase_date: date, current_date: date, target_date: date) -> float:
    total_days = max(1, (current_date - purchase_date).days)
    frac = min(1.0, max(0.0, (target_date - purchase_date).days / total_days))
    return ppc_usd + frac * (current_usd - ppc_usd)
