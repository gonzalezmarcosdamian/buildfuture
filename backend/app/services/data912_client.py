"""
data912.com — Open data argentina para precios de mercado.
Sin autenticación. CORS libre. Sin rate limit documentado.
Docs: https://data912.com (Swagger UI)

Provee precios live y OHLC histórico para:
- Bonos soberanos ARG (arg_bonds): GD30, AL35, AE38, GD35...
- ONs corporativas (arg_corp): +573 instrumentos
- CEDEARs (arg_cedears): +822
- Acciones ARG (arg_stocks): +95
- ADRs USA (usa_adrs): +207
- MEP implícito por CEDEAR (mep): bid/ask MEP + CCL
- OHLC histórico: /historical/bonds/{ticker}, /historical/cedears/{ticker}, /historical/stocks/{ticker}

Campos live: symbol, px_bid, px_ask, c (close), pct_change, v (volumen), q_bid, q_ask, q_op
Nota: NO expone YTM/TIR directamente. Se usa el precio para cálculos propios o como input.
"""

import logging
import time
from decimal import Decimal

import httpx

logger = logging.getLogger("buildfuture.data912")

_BASE = "https://data912.com"
_HEADERS = {"Accept": "application/json", "User-Agent": "BuildFuture/0.15"}
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0)

# ── Caches en memoria ─────────────────────────────────────────────────────────
_CACHE_TTL = 5 * 60  # 5 minutos

_bonds_cache: list[dict] = []
_bonds_ts: float = 0.0

_corp_cache: list[dict] = []
_corp_ts: float = 0.0

_cedears_cache: list[dict] = []
_cedears_ts: float = 0.0

_stocks_cache: list[dict] = []
_stocks_ts: float = 0.0

_mep_cache: list[dict] = []
_mep_ts: float = 0.0

_ccl_cache: list[dict] = []
_ccl_ts: float = 0.0


def _fetch_panel(path: str) -> list[dict]:
    """GET genérico con manejo de timeout."""
    try:
        r = httpx.get(f"{_BASE}{path}", headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning("data912 %s falló: %s", path, e)
        return []


def _get_bonds() -> list[dict]:
    global _bonds_cache, _bonds_ts
    if time.time() - _bonds_ts > _CACHE_TTL:
        data = _fetch_panel("/live/arg_bonds")
        if data:
            _bonds_cache = data
            _bonds_ts = time.time()
            logger.debug("data912 bonds: %d instrumentos cargados", len(data))
    return _bonds_cache


def _get_corp() -> list[dict]:
    global _corp_cache, _corp_ts
    if time.time() - _corp_ts > _CACHE_TTL:
        data = _fetch_panel("/live/arg_corp")
        if data:
            _corp_cache = data
            _corp_ts = time.time()
            logger.debug("data912 corp: %d ONs cargadas", len(data))
    return _corp_cache


def _get_cedears() -> list[dict]:
    global _cedears_cache, _cedears_ts
    if time.time() - _cedears_ts > _CACHE_TTL:
        data = _fetch_panel("/live/arg_cedears")
        if data:
            _cedears_cache = data
            _cedears_ts = time.time()
    return _cedears_cache


def _get_mep() -> list[dict]:
    global _mep_cache, _mep_ts
    if time.time() - _mep_ts > _CACHE_TTL:
        data = _fetch_panel("/live/mep")
        if data:
            _mep_cache = data
            _mep_ts = time.time()
    return _mep_cache


def _get_ccl() -> list[dict]:
    global _ccl_cache, _ccl_ts
    if time.time() - _ccl_ts > _CACHE_TTL:
        data = _fetch_panel("/live/ccl")
        if data:
            _ccl_cache = data
            _ccl_ts = time.time()
    return _ccl_cache


# ── API pública ───────────────────────────────────────────────────────────────

def get_bond_price(ticker: str) -> dict | None:
    """
    Precio live de un bono soberano ARG.
    Retorna: {symbol, px_bid, px_ask, close, pct_change, volume}
    o None si no está en el panel.

    Uso principal: byma_client.get_bond_tir() falla → calcular YTM desde precio.
    Precios en ARS por VN 100 para AL/GD; en USD/100 para GD-D (dólar-linked).
    """
    ticker = ticker.upper()
    for item in _get_bonds():
        if item.get("symbol", "").upper() == ticker:
            return {
                "symbol": ticker,
                "px_bid": item.get("px_bid"),
                "px_ask": item.get("px_ask"),
                "close": item.get("c"),
                "pct_change": item.get("pct_change"),
                "volume": item.get("v"),
            }
    return None


def get_on_price(ticker: str) -> dict | None:
    """
    Precio live de una ON corporativa.
    Retorna: {symbol, px_bid, px_ask, close, pct_change, volume}
    o None si no está en el panel (+573 ONs disponibles).
    """
    ticker = ticker.upper()
    for item in _get_corp():
        if item.get("symbol", "").upper() == ticker:
            return {
                "symbol": ticker,
                "px_bid": item.get("px_bid"),
                "px_ask": item.get("px_ask"),
                "close": item.get("c"),
                "pct_change": item.get("pct_change"),
                "volume": item.get("v"),
            }
    return None


def get_cedear_price(ticker: str) -> dict | None:
    """
    Precio live de un CEDEAR desde data912 (822 tickers).
    Alternativa/complemento a BYMA btnCedears.
    Retorna: {symbol, px_bid, px_ask, close, pct_change}
    """
    ticker = ticker.upper()
    for item in _get_cedears():
        if item.get("symbol", "").upper() == ticker:
            return {
                "symbol": ticker,
                "px_bid": item.get("px_bid"),
                "px_ask": item.get("px_ask"),
                "close": item.get("c"),
                "pct_change": item.get("pct_change"),
            }
    return None


def get_mep_by_cedear(ticker: str) -> dict | None:
    """
    MEP implícito para un CEDEAR específico.
    Retorna: {ticker, mep_bid, mep_ask, mep_mark, ars_bid, ars_ask, usd_bid, usd_ask}
    Útil para ver dispersión del MEP entre CEDEARs (AAL vs AAPL vs YPF).
    """
    ticker = ticker.upper()
    for item in _get_mep():
        if item.get("ticker", "").upper() == ticker:
            return {
                "ticker": ticker,
                "mep_bid": item.get("bid"),
                "mep_ask": item.get("ask"),
                "mep_mark": item.get("mark"),
                "mep_close": item.get("close"),
                "ars_bid": item.get("ars_bid"),
                "ars_ask": item.get("ars_ask"),
                "usd_bid": item.get("usd_bid"),
                "usd_ask": item.get("usd_ask"),
                "panel": item.get("panel"),
            }
    return None


def get_ccl_by_ticker(ticker_ar: str) -> dict | None:
    """
    CCL implícito para un par ARG/USA (ej: YPFD/YPF).
    Retorna: {ticker_usa, ticker_ar, ccl_bid, ccl_ask, ccl_mark}
    """
    ticker_ar = ticker_ar.upper()
    for item in _get_ccl():
        if item.get("ticker_ar", "").upper() == ticker_ar:
            return {
                "ticker_usa": item.get("ticker_usa"),
                "ticker_ar": ticker_ar,
                "ccl_bid": item.get("CCL_bid"),
                "ccl_ask": item.get("CCL_ask"),
                "ccl_mark": item.get("CCL_mark"),
                "ccl_close": item.get("CCL_close"),
                "ars_volume": item.get("ars_volume"),
            }
    return None


def get_bond_history(ticker: str, limit: int = 365) -> list[dict]:
    """
    OHLC histórico de un bono soberano.
    GD30 tiene datos desde 2021 (1112 puntos).
    Retorna: [{date, open, high, low, close, volume}]
    """
    try:
        r = httpx.get(
            f"{_BASE}/historical/bonds/{ticker.upper()}",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        result = [
            {
                "date": item["date"],
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
                "daily_return": item.get("dr"),
            }
            for item in data[-limit:]  # últimos N días
            if item.get("c") is not None
        ]
        return result
    except Exception as e:
        logger.warning("data912 historical/bonds/%s falló: %s", ticker, e)
        return []


def get_cedear_history(ticker: str, limit: int = 365) -> list[dict]:
    """
    OHLC histórico de un CEDEAR.
    AAPL tiene datos desde 2012 (3255 puntos).
    """
    try:
        r = httpx.get(
            f"{_BASE}/historical/cedears/{ticker.upper()}",
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            {
                "date": item["date"],
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
            }
            for item in data[-limit:]
            if item.get("c") is not None
        ]
    except Exception as e:
        logger.warning("data912 historical/cedears/%s falló: %s", ticker, e)
        return []


def get_bond_ytm_proxy(ticker: str, nominal_value: float = 100.0) -> Decimal | None:
    """
    Proxy de YTM para BOND/ON a partir del precio live de data912.
    LIMITACIÓN: sin cashflow schedule → no es YTM real.
    Fórmula aproximada: si precio ~ par (100) → YTM ≈ cupón/precio
    Útil solo como señal de dirección, no como valor exacto.

    Para YTM real se necesita: cupón, frecuencia, vencimiento.
    TODO: integrar con ficha técnica BYMA para bonos.
    Retorna None si no hay precio o instrumento no encontrado.
    """
    bond_data = get_bond_price(ticker) or get_on_price(ticker)
    if not bond_data or bond_data.get("close") is None:
        return None

    close = float(bond_data["close"])
    if close <= 0:
        return None

    # Proxy burdo: descuento de precio sobre nominal
    # Si precio = 91.5 → descuento = 8.5% sobre nominal.
    # No es YTM real pero sirve para ordenar por riesgo relativo.
    if close > 1000:
        # Precio en ARS (bonos dollar-linked o en pesos) — no podemos calcular YTM en USD
        return None

    if close <= nominal_value:
        discount = (nominal_value - close) / nominal_value
        return Decimal(str(round(discount, 4)))

    return None
