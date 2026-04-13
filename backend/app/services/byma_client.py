"""
Cliente Open BYMA Data — API pública gratuita, sin autenticación, 20 min delay.
Base URL: https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/

Contrato real (descubierto 2026-04-10 via ingeniería inversa del JS del front):
  Todos los endpoints de mercado son POST /get-market-data con un body JSON que
  incluye el "panel" como clave booleana:
    {"excludeZeroPxAndQty": false, "T0": true, "page_number": 1, "page_size": 500,
     "btnLetras": true}
  Paneles disponibles: btnLetras, btnTitPublicos, btnObligNegociables, btnCedears,
                       btnLideres, btnGeneral

  Los endpoints GET viejos (short-term-government-bonds, government-bonds, etc.)
  están DEPRECADOS y retornan HTTP 400 siempre.

  La ficha técnica de un instrumento se obtiene via:
    POST /bnown/fichatecnica/especies/general  body={"symbol": "S31G6"}
  Retorna fechaEmision, fechaVencimiento, interes (TEM contractual), etc.

  LIMITACION: el campo `impliedYield` viene null en /get-market-data.
  Para LECAPs capitalizables se calcula la TEA de mercado combinando:
    - precio BYMA (vwap) del panel btnLetras
    - TEM contractual + fechaEmision de fichatecnica/especies/general
    - Formula: TEA = (VNV/precio)^(365/dias) - 1
      donde VNV = 100 * (1+TEM)^meses_totales_emision_a_vto

  Para letras CER (X-prefix): TIR real calculada desde precio BYMA + UVA
  (ArgentinaDatos) como proxy del CER.

Patrón: cache in-memory TTL 5 min + fallback ArgentinaDatos + hardcodeado.
Nunca lanzar excepción al caller — siempre retornar un valor utilizable.

Funciones públicas:
  - get_lecap_tna()            → TEA promedio de mercado de LECAPs vigentes (%)
  - get_lecap_tea_by_ticker()  → TEA de mercado para un ticker específico (%)
  - get_cer_letter_tir()       → TIR real de una letra CER (X-prefix) (%)
  - get_cedear_price_ars()     → precio spot ARS de un CEDEAR
  - get_bond_tir()             → TIR de un bono soberano (%)
  - get_on_tir()               → TIR de una ON corporativa (%)
"""

import logging
import re
import time
from datetime import date

import httpx

logger = logging.getLogger("buildfuture.byma")

# ── Constantes ─────────────────────────────────────────────────────────────────

BYMA_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
BYMA_HEADERS = {
    "Origin": "https://open.bymadata.com.ar",
    "Referer": "https://open.bymadata.com.ar/",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
CACHE_TTL = 300  # 5 minutos

LECAP_TNA_FALLBACK: float = 32.0  # TEA% de respaldo si todas las fuentes fallan (abril 2026)

# Caps de sanidad para TIR
BOND_TIR_MAX: float = 50.0
ON_TIR_MAX: float = 30.0
CER_TIR_MIN: float = -30.0
CER_TIR_MAX: float = 30.0

# ── Cache in-memory ────────────────────────────────────────────────────────────

_lecap_cache: dict = {"value": None, "ts": 0.0}
# {ticker: {vwap, tem, emision, vto}} para todas las letras
_letras_market_cache: dict = {"data": {}, "ts": 0.0}
_cedear_cache: dict = {"data": {}, "ts": 0.0}       # {ticker: price_ars}
_cedear_full_cache: dict = {"data": {}, "ts": 0.0}  # {ticker: {price, prev_close, high, low}}
_stock_cache: dict = {"data": {}, "ts": 0.0}
_sovereign_cache: dict = {"data": {}, "ts": 0.0}
_on_cache: dict = {"data": {}, "ts": 0.0}
_cer_cache: dict = {"data": {}, "ts": 0.0}
# {ticker: {tem, emision, vto}} — ficha técnica de cada letra
_ficha_cache: dict = {"data": {}, "ts": 0.0}


# ── Helpers internos ────────────────────────────────────────────────────────────

def _post_market_data(panel_key: str, page_size: int = 500, t0: bool = True) -> list[dict]:
    """
    POST /get-market-data con el panel indicado.
    Retorna la lista de instrumentos o [] si falla.
    """
    body = {
        "excludeZeroPxAndQty": False,
        "T0": t0,
        "page_number": 1,
        "page_size": page_size,
        panel_key: True,
    }
    r = httpx.post(
        f"{BYMA_BASE}/get-market-data",
        json=body,
        headers=BYMA_HEADERS,
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        verify=False,
    )
    if r.status_code != 200:
        logger.warning("BYMA get-market-data [%s]: HTTP %s", panel_key, r.status_code)
        return []
    return r.json().get("data", [])


def _get_ficha_tecnica(ticker: str) -> dict | None:
    """
    POST /bnown/fichatecnica/especies/general para obtener TEM contractual y fechas.
    Retorna el primer item de data, o None si falla.
    Cachea por ticker con TTL 1h (los datos de ficha no cambian durante el día).
    """
    ticker_upper = ticker.upper()
    now = time.time()
    cached = _ficha_cache["data"].get(ticker_upper)
    if cached and now - cached.get("_ts", 0) < 3600:
        return cached

    try:
        r = httpx.post(
            f"{BYMA_BASE}/bnown/fichatecnica/especies/general",
            json={"symbol": ticker_upper},
            headers=BYMA_HEADERS,
            timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0),
            verify=False,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None
        item = data[0]
        item["_ts"] = now
        _ficha_cache["data"][ticker_upper] = item
        return item
    except Exception as e:
        logger.warning("BYMA fichatecnica %s: %s", ticker, e)
        return None


def _parse_tem_from_interes(interes_str: str) -> float | None:
    """
    Extrae la TEM (%) del campo 'interes' de la ficha técnica.
    Ejemplos: "tasa efectiva mensual: 2,60 %" → 0.026
              "Tasa efectiva mensual del 2.5%" → 0.025
    Retorna None si no encuentra el patrón.
    """
    if not interes_str:
        return None
    # Normalizar coma decimal
    norm = interes_str.replace(",", ".")
    match = re.search(r"(\d+\.?\d*)\s*%", norm, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 100
    return None


def _parse_date(date_str: str) -> date | None:
    """Parsea 'YYYY-MM-DD HH:MM:SS.S' o 'YYYY-MM-DD' a date."""
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except (ValueError, TypeError):
        return None


def _calc_lecap_tea_from_price(
    vwap: float, tem: float, emision: date, vto: date, today: date
) -> float | None:
    """
    Calcula la TEA de mercado de una LECAP capitalizable desde su precio BYMA.

    Formula:
      VNV = 100 * (1 + TEM)^meses_totales   [valor nominal al vencimiento]
      TEA = (VNV / precio)^(365 / dias_restantes) - 1

    Retorna None si precio <= 0, dias <= 0, o la TEA resultante es inválida.
    """
    if vwap <= 0:
        return None
    dias_totales = (vto - emision).days
    dias_restantes = (vto - today).days
    if dias_restantes <= 0 or dias_totales <= 0:
        return None
    meses_totales = dias_totales / 30.4375
    vnv = 100 * (1 + tem) ** meses_totales
    if vnv <= 0:
        return None
    tea = (vnv / vwap) ** (365 / dias_restantes) - 1
    tea_pct = round(tea * 100, 2)
    # Sanidad: TEA fuera de -10% a +500% es anómala (mercado argentino puede superar 100% nominal)
    if -10.0 <= tea_pct <= 500.0:
        return tea_pct
    return None


# ── get_lecap_tna / get_lecap_tea_by_ticker ────────────────────────────────────

def get_lecap_tna() -> float:
    """
    Retorna la TEA promedio ponderada (por volumen) de las LECAPs vigentes.

    Fuente: BYMA POST /get-market-data con btnLetras + fichatecnica/especies/general
    para obtener TEM contractual y fechas de emisión/vencimiento.
    Si BYMA falla: ArgentinaDatos → fallback 32%.
    """
    now = time.time()
    if _lecap_cache["value"] is not None and now - _lecap_cache["ts"] < CACHE_TTL:
        logger.debug("get_lecap_tna: cache hit → %.2f%%", _lecap_cache["value"])
        return _lecap_cache["value"]

    try:
        tea = _calc_lecap_market_avg()
        if tea is not None:
            _lecap_cache["value"] = tea
            _lecap_cache["ts"] = now
            logger.info("get_lecap_tna: BYMA → TEA %.2f%%", tea)
            return tea
    except Exception as e:
        logger.warning("get_lecap_tna: BYMA falló (%s)", e)

    return _lecap_tna_argentinadatos_fallback()


def _calc_lecap_market_avg() -> float | None:
    """
    Descarga todas las letras de BYMA (btnLetras), obtiene ficha técnica de cada
    una con volumen, y calcula la TEA promedio ponderada por volumen.
    Solo S-prefix (nominales, no CER).
    """
    today = date.today()
    items = _post_market_data("btnLetras", page_size=500, t0=True)
    if not items:
        # Con T0=False captura letras que no operaron hoy
        items = _post_market_data("btnLetras", page_size=500, t0=False)
    if not items:
        return None

    total_volume = 0.0
    weighted_sum = 0.0

    for item in items:
        sym = str(item.get("symbol") or "").upper()
        if not sym.startswith("S"):
            continue  # excluir CER y otros

        vwap = float(item.get("vwap") or 0)
        volume = float(item.get("tradeVolume") or 0)
        if vwap <= 0:
            continue

        ficha = _get_ficha_tecnica(sym)
        if not ficha:
            continue

        tem = _parse_tem_from_interes(ficha.get("interes", ""))
        emision = _parse_date(ficha.get("fechaEmision", ""))
        vto = _parse_date(ficha.get("fechaVencimiento", ""))
        if tem is None or emision is None or vto is None:
            continue

        tea_pct = _calc_lecap_tea_from_price(vwap, tem, emision, vto, today)
        if tea_pct is None or tea_pct <= 0:
            continue

        weight = volume if volume > 0 else 1.0
        weighted_sum += tea_pct * weight
        total_volume += weight

    if total_volume == 0:
        return None
    return round(weighted_sum / total_volume, 2)


def _lecap_tna_argentinadatos_fallback() -> float:
    """ArgentinaDatos como segundo fallback, luego hardcodeado."""
    try:
        from app.services.fci_prices import get_lecap_market_tna
        tna = get_lecap_market_tna()
        if tna is not None:
            logger.info("get_lecap_tna: ArgentinaDatos → %.2f%%", tna)
            return tna
    except Exception as e:
        logger.warning("get_lecap_tna: ArgentinaDatos falló (%s) → %.1f%%", e, LECAP_TNA_FALLBACK)
    logger.warning("get_lecap_tna: sin fuentes → hardcoded %.1f%%", LECAP_TNA_FALLBACK)
    return LECAP_TNA_FALLBACK


def get_lecap_tea_by_ticker(ticker: str) -> float | None:
    """
    TEA de mercado para una LECAP capitalizable específica (S-prefix).
    Combina precio BYMA + TEM contractual de fichatecnica.
    Retorna None si BYMA no tiene el dato o el cálculo es inválido.
    """
    today = date.today()
    ticker_upper = ticker.upper()

    # Asegurar que el cache de letras está fresco
    now = time.time()
    if not _letras_market_cache["data"] or now - _letras_market_cache["ts"] >= CACHE_TTL:
        try:
            items = _post_market_data("btnLetras", page_size=500, t0=True)
            if not items:
                items = _post_market_data("btnLetras", page_size=500, t0=False)
            data: dict[str, float] = {}
            for item in items:
                sym = str(item.get("symbol") or "").upper()
                vwap = float(item.get("vwap") or 0)
                if sym and vwap > 0:
                    data[sym] = vwap
            _letras_market_cache["data"] = data
            _letras_market_cache["ts"] = now
        except Exception as e:
            logger.warning("get_lecap_tea_by_ticker: fetch letras falló (%s)", e)

    vwap = _letras_market_cache["data"].get(ticker_upper)
    if not vwap:
        return None

    ficha = _get_ficha_tecnica(ticker_upper)
    if not ficha:
        return None

    tem = _parse_tem_from_interes(ficha.get("interes", ""))
    emision = _parse_date(ficha.get("fechaEmision", ""))
    vto = _parse_date(ficha.get("fechaVencimiento", ""))
    if tem is None or emision is None or vto is None:
        return None

    tea_pct = _calc_lecap_tea_from_price(vwap, tem, emision, vto, today)
    if tea_pct is not None:
        logger.info(
            "get_lecap_tea_by_ticker: %s vwap=%.4f TEM=%.2f%% TEA_mercado=%.2f%%",
            ticker_upper, vwap, tem * 100, tea_pct,
        )
    return tea_pct


# ── get_cer_letter_tir ─────────────────────────────────────────────────────────

def get_cer_letter_tir(ticker: str) -> float | None:
    """
    TIR real (%) de una letra CER (prefijo X, ej: X29Y6).

    Cálculo:
      1. Precio de mercado: BYMA btnLetras → vwap
      2. Ratio CER: ArgentinaDatos UVA como proxy
         ratio = UVA_hoy / UVA_emision
      3. VN ajustado a vto (estimando inflación 2.5%/mes hacia adelante):
         VN_vto = 100 * ratio_hoy * (1 + 0.025)^meses_restantes
      4. TIR nominal = (VN_vto / precio)^(365/dias) - 1
      5. TIR real = (1 + TIR_nominal) / (1 + TEA_inflacion) - 1
         donde TEA_inflacion = (1+0.025)^12 - 1 ≈ 34.5%

    Benchmarks confirmados (2026-04-10): X29Y6 ≈ -11.6% TIR real.
    Rango válido: CER_TIR_MIN (-30%) a CER_TIR_MAX (+30%).
    Retorna None si alguna fuente falla.
    """
    ticker_upper = ticker.upper()
    now = time.time()
    if _cer_cache["data"] and now - _cer_cache["ts"] < CACHE_TTL:
        logger.debug("get_cer_letter_tir: cache hit para %s", ticker_upper)
        return _cer_cache["data"].get(ticker_upper)

    try:
        result = _calc_cer_tir_for_all()
        _cer_cache["data"] = result
        _cer_cache["ts"] = now
        logger.info(
            "get_cer_letter_tir: calculadas %d letras CER: %s",
            len(result), list(result.keys())[:5],
        )
        return result.get(ticker_upper)
    except Exception as e:
        logger.warning("get_cer_letter_tir: falló (%s) → None", e)
        return None


def _calc_cer_tir_for_all() -> dict[str, float]:
    """
    Calcula TIR real para todas las letras CER (X-prefix) con precio en BYMA.
    Usa UVA de ArgentinaDatos como proxy del CER.
    """
    from app.services.fci_prices import get_uva_ratio_for_cer

    today = date.today()
    items = _post_market_data("btnLetras", page_size=500, t0=True)
    if not items:
        items = _post_market_data("btnLetras", page_size=500, t0=False)

    result: dict[str, float] = {}
    # TEM mensual inflacion estimada para proyectar CER hasta vencimiento
    TEM_INFLACION = 0.025
    TEA_INFLACION = (1 + TEM_INFLACION) ** 12 - 1

    for item in items:
        sym = str(item.get("symbol") or "").upper()
        if not sym.startswith("X"):
            continue

        vwap = float(item.get("vwap") or 0)
        if vwap <= 0:
            continue

        ficha = _get_ficha_tecnica(sym)
        if not ficha:
            continue

        emision = _parse_date(ficha.get("fechaEmision", ""))
        vto = _parse_date(ficha.get("fechaVencimiento", ""))
        if not emision or not vto:
            continue

        dias_restantes = (vto - today).days
        if dias_restantes <= 0:
            continue

        # Ratio CER acumulado desde emision a hoy (via UVA como proxy)
        ratio_hoy = get_uva_ratio_for_cer(emision, today)
        if ratio_hoy is None:
            continue

        meses_restantes = dias_restantes / 30.4375
        # VN ajustado al vencimiento (proyectando inflacion 2.5%/mes)
        vn_vto = 100 * ratio_hoy * (1 + TEM_INFLACION) ** meses_restantes

        tir_nominal = (vn_vto / vwap) ** (365 / dias_restantes) - 1
        tir_real = (1 + tir_nominal) / (1 + TEA_INFLACION) - 1
        tir_real_pct = round(tir_real * 100, 2)

        if CER_TIR_MIN <= tir_real_pct <= CER_TIR_MAX:
            result[sym] = tir_real_pct
            logger.debug(
                "CER %s: vwap=%.2f ratio_cer=%.4f vn_vto=%.2f TIR_real=%.2f%%",
                sym, vwap, ratio_hoy, vn_vto, tir_real_pct,
            )

    return result


# ── get_cedear_price_ars ───────────────────────────────────────────────────────

def get_cedear_price_ars(ticker: str) -> float | None:
    """
    Precio spot ARS del CEDEAR indicado desde BYMA POST /get-market-data.
    Usa panel btnCedears. Cache TTL 5 min.
    Retorna None si BYMA falla, el ticker no existe, o el precio es 0.
    """
    now = time.time()
    if _cedear_cache["data"] and now - _cedear_cache["ts"] < CACHE_TTL:
        logger.debug("get_cedear_price_ars: cache hit para %s", ticker.upper())
        return _cedear_cache["data"].get(ticker.upper())

    try:
        items = _post_market_data("btnCedears", page_size=1000)
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            price = float(item.get("vwap") or item.get("previousSettlementPrice") or 0)
            if sym and price > 0:
                data[sym] = price

        _cedear_cache["data"] = data
        _cedear_cache["ts"] = now
        logger.info("get_cedear_price_ars: BYMA → %d CEDEARs cacheados", len(data))
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_cedear_price_ars: BYMA falló (%s) → None", e)
        return None


# ── get_cedear_market_data ─────────────────────────────────────────────────────

def get_cedear_market_data(ticker: str) -> dict | None:
    """
    Datos de mercado extendidos para un CEDEAR desde BYMA btnCedears.
    Retorna dict con:
      price_ars        — precio spot (vwap o previousSettlementPrice)
      prev_close_ars   — cierre anterior (previousClosingPrice)
      high_ars         — máximo del día (tradingHighPrice)
      low_ars          — mínimo del día (tradingLowPrice)
      variation_pct    — variación diaria (%) calculada desde prev_close
    Retorna None si BYMA falla o el ticker no existe.
    Cache TTL 5 min compartido con _cedear_full_cache.
    """
    ticker_upper = ticker.upper()
    now = time.time()
    if _cedear_full_cache["data"] and now - _cedear_full_cache["ts"] < CACHE_TTL:
        logger.debug("get_cedear_market_data: cache hit para %s", ticker_upper)
        return _cedear_full_cache["data"].get(ticker_upper)

    try:
        items = _post_market_data("btnCedears", page_size=1000)
        data: dict[str, dict] = {}
        prices: dict[str, float] = {}

        for item in items:
            sym = str(item.get("symbol") or "").upper()
            if not sym:
                continue

            price = float(item.get("vwap") or item.get("previousSettlementPrice") or 0)
            prev_close = float(item.get("previousClosingPrice") or 0)
            high = float(item.get("tradingHighPrice") or 0)
            low = float(item.get("tradingLowPrice") or 0)

            if price <= 0:
                continue

            variation_pct: float | None = None
            if prev_close > 0:
                variation_pct = round((price - prev_close) / prev_close * 100, 2)

            data[sym] = {
                "price_ars": price,
                "prev_close_ars": prev_close if prev_close > 0 else None,
                "high_ars": high if high > 0 else None,
                "low_ars": low if low > 0 else None,
                "variation_pct": variation_pct,
            }
            prices[sym] = price

        _cedear_full_cache["data"] = data
        _cedear_full_cache["ts"] = now
        # Sync price-only cache for get_cedear_price_ars
        _cedear_cache["data"] = prices
        _cedear_cache["ts"] = now
        logger.info("get_cedear_market_data: BYMA → %d CEDEARs cacheados", len(data))
        return data.get(ticker_upper)

    except Exception as e:
        logger.warning("get_cedear_market_data: BYMA falló (%s) → None", e)
        return None


# ── get_stock_price_ars ────────────────────────────────────────────────────────

def get_stock_price_ars(ticker: str) -> float | None:
    """
    Precio spot ARS de una acción del panel Merval (blue chips) desde BYMA btnLideres.
    Solo cubre los ~24 líderes del panel principal. STOCKs fuera del panel → None.
    Cache TTL 5 min. Retorna None si BYMA falla, el ticker no existe o el precio es 0.
    """
    now = time.time()
    if _stock_cache["data"] and now - _stock_cache["ts"] < CACHE_TTL:
        logger.debug("get_stock_price_ars: cache hit para %s", ticker.upper())
        return _stock_cache["data"].get(ticker.upper())

    try:
        items = _post_market_data("btnLideres", page_size=100)
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            price = float(item.get("vwap") or item.get("previousSettlementPrice") or 0)
            if sym and price > 0:
                data[sym] = price

        _stock_cache["data"] = data
        _stock_cache["ts"] = now
        logger.info("get_stock_price_ars: BYMA → %d acciones líderes cacheadas", len(data))
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_stock_price_ars: BYMA falló (%s) → None", e)
        return None


# ── get_bond_tir / get_on_tir ──────────────────────────────────────────────────

def get_bond_tir(ticker: str) -> float | None:
    """
    TIR (%) del bono soberano desde BYMA btnTitPublicos.
    impliedYield viene null en el nuevo endpoint → retorna None hasta que BYMA
    exponga el campo. El caller usa la tabla _BOND_YTM como fallback.
    """
    return _get_price_from_panel(
        ticker=ticker,
        cache=_sovereign_cache,
        panel="btnTitPublicos",
        tir_max=BOND_TIR_MAX,
        label="bond",
    )


def get_on_tir(ticker: str) -> float | None:
    """
    TIR (%) de la ON corporativa desde BYMA btnObligNegociables.
    impliedYield viene null → retorna None, caller usa tabla.
    """
    return _get_price_from_panel(
        ticker=ticker,
        cache=_on_cache,
        panel="btnObligNegociables",
        tir_max=ON_TIR_MAX,
        label="on",
    )


def _get_price_from_panel(
    ticker: str, cache: dict, panel: str, tir_max: float, label: str
) -> float | None:
    """
    Intenta obtener impliedYield del panel BYMA indicado.
    Como el campo viene null en la API actual, siempre retorna None.
    Mantiene el cache de precios para futura extensión cuando BYMA lo exponga.
    """
    now = time.time()
    if cache["ts"] > 0 and now - cache["ts"] < CACHE_TTL:
        logger.debug("get_%s_tir: cache hit para %s", label, ticker.upper())
        return cache["data"].get(ticker.upper())

    try:
        items = _post_market_data(panel, page_size=500)
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            # impliedYield actualmente null en BYMA — guardamos el precio de referencia
            # para cuando lo exponga en el futuro
            tir = item.get("impliedYield")
            if sym and tir is not None:
                tir_f = float(tir)
                if 0 < tir_f <= tir_max:
                    data[sym] = tir_f

        cache["data"] = data
        cache["ts"] = now
        logger.info("get_%s_tir: BYMA → %d con impliedYield (actualmente 0)", label, len(data))
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_%s_tir: BYMA falló (%s) → None", label, e)
        return None
