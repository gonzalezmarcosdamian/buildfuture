"""
Cliente Open BYMA Data — API pública gratuita, sin autenticación, 20 min delay.
Base URL: https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/

Patrón: cache in-memory TTL 5 min + fallback hardcodeado si BYMA falla.
Nunca lanzar excepción al caller — siempre retornar un valor utilizable.

Endpoints implementados:
  - get_lecap_tna()        → TNA promedio ponderada de LECAPs vigentes
  - get_cedear_price_ars() → precio spot en ARS de un CEDEAR (BYMA 2)
  - get_bond_tir()         → TIR % de un bono soberano (BYMA 3)
  - get_on_tir()           → TIR % de una ON corporativa (BYMA 3)
"""

import logging
import time
from datetime import date

import httpx

logger = logging.getLogger("buildfuture.byma")

# ── Constantes ─────────────────────────────────────────────────────────────────

BYMA_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
CACHE_TTL = 300  # 5 minutos

LECAP_TNA_FALLBACK: float = 32.0  # TNA % de respaldo si BYMA no responde (calibrado abril 2026)

# Caps de sanidad para TIR — valores extremos son anomalías de mercado (bono en default, etc.)
BOND_TIR_MAX: float = 50.0   # >50% TIR en bono soberano USD es sospechoso
ON_TIR_MAX: float = 30.0     # >30% TIR en ON corporativa USD es sospechoso
# Letras CER: TIR real puede ser negativa (debajo de inflación) o positiva.
# Rango válido: -30% a +30% real. Fuera de ese rango es anomalía o dato sucio.
CER_TIR_MIN: float = -30.0
CER_TIR_MAX: float = 30.0

# ── Cache in-memory ────────────────────────────────────────────────────────────

_lecap_cache: dict = {"value": None, "ts": 0.0}
# BYMA 2: {ticker: price_ars} para todos los CEDEARs (una sola request por TTL)
_cedear_cache: dict = {"data": {}, "ts": 0.0}
# BYMA 3: {ticker: tir_pct} para bonos soberanos y ONs (endpoints distintos)
_sovereign_cache: dict = {"data": {}, "ts": 0.0}
_on_cache: dict = {"data": {}, "ts": 0.0}
# BYMA 4: {ticker: tir_real_pct} para letras CER (X-prefix) — mismo endpoint que LECAPs
_cer_cache: dict = {"data": {}, "ts": 0.0}


# ── get_lecap_tna ──────────────────────────────────────────────────────────────

def get_lecap_tna() -> float:
    """
    Retorna la TNA promedio ponderada (por volumen) de las LECAPs vigentes
    operadas en BYMA.

    - Filtra instrumentos con securityType == "LETRA"
    - Descarta LECAPs con fecha de vencimiento pasada
    - Descarta items con impliedYield == 0
    - Pondera por volumen operado
    - Cache de 5 min para no martillar la API en cada request
    - Fallback a LECAP_TNA_FALLBACK si BYMA falla o no hay datos válidos
    """
    now = time.time()
    if _lecap_cache["value"] is not None and now - _lecap_cache["ts"] < CACHE_TTL:
        logger.debug("get_lecap_tna: cache hit → %.2f%%", _lecap_cache["value"])
        return _lecap_cache["value"]

    try:
        r = httpx.get(
            f"{BYMA_BASE}/short-term-government-bonds",
            timeout=8,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            logger.warning("BYMA short-term-bonds: HTTP %s → ArgentinaDatos", r.status_code)
            return _lecap_tna_argentinadatos_fallback()

        items = r.json()
        tna = _calc_weighted_tna(items)

        if tna is None:
            logger.warning("BYMA: sin LECAPs vigentes → ArgentinaDatos")
            return _lecap_tna_argentinadatos_fallback()

        _lecap_cache["value"] = tna
        _lecap_cache["ts"] = now
        logger.info("get_lecap_tna: BYMA → %.2f%%", tna)
        return tna

    except Exception as e:
        logger.warning("get_lecap_tna: BYMA falló (%s) → ArgentinaDatos", e)
        return _lecap_tna_argentinadatos_fallback()


def _lecap_tna_argentinadatos_fallback() -> float:
    """
    Segundo fallback para get_lecap_tna(): consulta ArgentinaDatos /letras.
    Si también falla, retorna LECAP_TNA_FALLBACK hardcodeado.
    """
    try:
        from app.services.fci_prices import get_lecap_market_tna
        tna = get_lecap_market_tna()
        if tna is not None:
            logger.info("get_lecap_tna: ArgentinaDatos → %.2f%%", tna)
            return tna
    except Exception as e:
        logger.warning("get_lecap_tna: ArgentinaDatos falló (%s) → hardcoded %.1f%%", e, LECAP_TNA_FALLBACK)
    logger.warning("get_lecap_tna: sin fuentes disponibles → hardcoded %.1f%%", LECAP_TNA_FALLBACK)
    return LECAP_TNA_FALLBACK


# ── get_cedear_price_ars ───────────────────────────────────────────────────────

def get_cedear_price_ars(ticker: str) -> float | None:
    """
    Retorna el precio spot en ARS del CEDEAR indicado (campo `last` de BYMA).

    - Descarga todos los CEDEARs de una vez y cachea el dict {ticker: price_ars}
    - Retorna None si BYMA falla, el ticker no existe, o el precio es 0
    - El caller (historical_reconstructor, iol_client) debe aplicar MEP para convertir a USD
    """
    now = time.time()
    if _cedear_cache["data"] and now - _cedear_cache["ts"] < CACHE_TTL:
        logger.debug("get_cedear_price_ars: cache hit para %s", ticker.upper())
        return _cedear_cache["data"].get(ticker.upper())

    try:
        r = httpx.get(
            f"{BYMA_BASE}/cedears",
            timeout=8,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            logger.warning("BYMA cedears: HTTP %s → None", r.status_code)
            return None

        items = r.json()
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            # BYMA usa "trade" (= closingPrice), no "last"
            price = float(item.get("trade") or item.get("closingPrice") or 0)
            if sym and price > 0:
                data[sym] = price

        _cedear_cache["data"] = data
        _cedear_cache["ts"] = now
        logger.info("get_cedear_price_ars: BYMA → %d CEDEARs cacheados", len(data))
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_cedear_price_ars: BYMA falló (%s) → None", e)
        return None


# ── get_bond_tir / get_on_tir ──────────────────────────────────────────────────

def get_bond_tir(ticker: str) -> float | None:
    """
    Retorna la TIR (%) del bono soberano indicado desde BYMA government-bonds.

    - Cachea todo el endpoint en _sovereign_cache; un call por TTL
    - Retorna None si BYMA falla, el ticker no existe, la TIR es negativa o > BOND_TIR_MAX
    - El caller convierte a decimal: annual_yield = tir_pct / 100
    """
    return _get_tir_from_cache(
        ticker=ticker,
        cache=_sovereign_cache,
        endpoint="government-bonds",
        tir_max=BOND_TIR_MAX,
        label="bond",
    )


def get_on_tir(ticker: str) -> float | None:
    """
    Retorna la TIR (%) de la ON corporativa indicada desde BYMA corporate-bonds.

    - Cachea todo el endpoint en _on_cache; un call por TTL
    - Retorna None si BYMA falla, el ticker no existe, la TIR es negativa o > ON_TIR_MAX
    """
    return _get_tir_from_cache(
        ticker=ticker,
        cache=_on_cache,
        endpoint="corporate-bonds",
        tir_max=ON_TIR_MAX,
        label="on",
    )


def get_cer_letter_tir(ticker: str) -> float | None:
    """
    Retorna la TIR real (%) de una letra ajustada por CER (prefijo X, ej: X29Y6).

    Las letras CER no pagan una TNA fija: ajustan su valor nominal diariamente
    por el índice CER (inflación) publicado por el BCRA. La métrica correcta es la
    TIR real = rendimiento anual POR ENCIMA del CER. Un valor negativo (ej: -12%)
    significa que rendís CER - 12% anual — comprás más caro que el CER acumulado.

    Fuente: BYMA short-term-government-bonds, campo `impliedYield`.
    BYMA ya calcula la TIR real para letras CER — es el mismo valor que muestran
    Rava, Cocos e IOL (benchmarks: X29Y6 ≈ -12%, X18E7 ≈ -9% a abril 2026).

    Rango válido: CER_TIR_MIN (-30%) a CER_TIR_MAX (+30%).
    Retorna None si BYMA falla, el ticker no está en la respuesta, o el valor
    está fuera del rango de sanidad — el caller debe usar fallback=0.
    """
    now = time.time()
    if _cer_cache["data"] and now - _cer_cache["ts"] < CACHE_TTL:
        logger.debug("get_cer_letter_tir: cache hit para %s", ticker.upper())
        return _cer_cache["data"].get(ticker.upper())

    try:
        r = httpx.get(
            f"{BYMA_BASE}/short-term-government-bonds",
            timeout=8,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            logger.warning("BYMA short-term-bonds (CER): HTTP %s → None", r.status_code)
            return None

        items = r.json()
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            if not sym.startswith("X"):
                continue
            tir = float(item.get("impliedYield") or 0)
            if CER_TIR_MIN <= tir <= CER_TIR_MAX:
                data[sym] = tir

        _cer_cache["data"] = data
        _cer_cache["ts"] = now
        logger.info(
            "get_cer_letter_tir: BYMA → %d letras CER cacheadas: %s",
            len(data),
            list(data.keys())[:5],
        )
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_cer_letter_tir: BYMA falló (%s) → None", e)
        return None


def _get_tir_from_cache(
    ticker: str,
    cache: dict,
    endpoint: str,
    tir_max: float,
    label: str,
) -> float | None:
    """Implementación compartida para get_bond_tir y get_on_tir."""
    now = time.time()
    if cache["data"] and now - cache["ts"] < CACHE_TTL:
        logger.debug("get_%s_tir: cache hit para %s", label, ticker.upper())
        return cache["data"].get(ticker.upper())

    try:
        r = httpx.get(
            f"{BYMA_BASE}/{endpoint}",
            timeout=8,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            logger.warning("BYMA %s: HTTP %s → None", endpoint, r.status_code)
            return None

        items = r.json()
        data: dict[str, float] = {}
        for item in items:
            sym = str(item.get("symbol") or "").upper()
            tir = float(item.get("impliedYield") or 0)
            # Descartar TIRs inválidas (negativas o anómalas)
            if sym and 0 < tir <= tir_max:
                data[sym] = tir

        cache["data"] = data
        cache["ts"] = now
        logger.info("get_%s_tir: BYMA → %d instrumentos cacheados", label, len(data))
        return data.get(ticker.upper())

    except Exception as e:
        logger.warning("get_%s_tir: BYMA falló (%s) → None", label, e)
        return None


def _calc_weighted_tna(items: list[dict]) -> float | None:
    """
    Calcula la TNA promedio ponderada por volumen de las LECAPs válidas.
    Retorna None si no hay items válidos.
    """
    today = date.today()
    total_volume = 0.0
    weighted_sum = 0.0

    for item in items:
        # Solo LETRA
        if item.get("securityType", "").upper() != "LETRA":
            continue

        # yield válido
        implied_yield = item.get("impliedYield") or 0.0
        if implied_yield <= 0:
            continue

        # No vencida
        maturity_str = item.get("maturity", "")
        try:
            maturity = date.fromisoformat(maturity_str[:10])
            if maturity <= today:
                continue
        except (ValueError, TypeError):
            continue

        volume = float(item.get("volume") or 0)
        if volume <= 0:
            volume = 1.0  # peso mínimo si no hay volumen informado

        weighted_sum += implied_yield * volume
        total_volume += volume

    if total_volume == 0:
        return None

    return round(weighted_sum / total_volume, 2)
