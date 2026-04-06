"""
Cliente Open BYMA Data — API pública gratuita, sin autenticación, 20 min delay.
Base URL: https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/

Patrón: cache in-memory TTL 5 min + fallback hardcodeado si BYMA falla.
Nunca lanzar excepción al caller — siempre retornar un valor utilizable.

Endpoints implementados:
  - get_lecap_tna() → TNA promedio ponderada de LECAPs vigentes
"""

import logging
import time
from datetime import date

import httpx

logger = logging.getLogger("buildfuture.byma")

# ── Constantes ─────────────────────────────────────────────────────────────────

BYMA_BASE = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free"
CACHE_TTL = 300  # 5 minutos

LECAP_TNA_FALLBACK: float = 55.0  # TNA % de respaldo si BYMA no responde

# ── Cache in-memory ────────────────────────────────────────────────────────────

_lecap_cache: dict = {"value": None, "ts": 0.0}


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
            logger.warning("BYMA short-term-bonds: HTTP %s → fallback", r.status_code)
            return LECAP_TNA_FALLBACK

        items = r.json()
        tna = _calc_weighted_tna(items)

        if tna is None:
            logger.warning("BYMA: sin LECAPs vigentes → fallback %.1f%%", LECAP_TNA_FALLBACK)
            return LECAP_TNA_FALLBACK

        _lecap_cache["value"] = tna
        _lecap_cache["ts"] = now
        logger.info("get_lecap_tna: BYMA → %.2f%%", tna)
        return tna

    except Exception as e:
        logger.warning("get_lecap_tna: BYMA falló (%s) → fallback %.1f%%", e, LECAP_TNA_FALLBACK)
        return LECAP_TNA_FALLBACK


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
