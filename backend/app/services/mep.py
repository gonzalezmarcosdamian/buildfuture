"""
Resolución del tipo de cambio MEP (dólar bolsa).

Orden de prioridad:
  1. Budget del usuario (ya disponible en memoria, sin llamada HTTP)
  2. dolarapi.com — precio de venta del dólar bolsa
  3. Fallback hardcoded 1430

Usar get_mep() en todos los lugares que crean PortfolioSnapshot
para garantizar que fx_mep nunca queda en 0.
"""

from decimal import Decimal
import logging
import time

logger = logging.getLogger("buildfuture.mep")

MEP_FALLBACK = Decimal("1430")

# Cache in-process del MEP de dolarapi — el dólar bolsa no cambia segundo a
# segundo. Evita un HTTP call (timeout 5s) por cada request que llama get_mep()
# sin budget. TTL 15 min.
_mep_cache: dict = {"value": None, "ts": 0.0}
_MEP_TTL = 15 * 60


def get_mep(budget=None) -> Decimal:
    """
    Retorna el MEP actual como Decimal.
    Nunca retorna 0 — el fallback es 1430.

    Prioridad: budget del usuario (en memoria) > cache dolarapi (15 min) >
    fetch dolarapi > último valor cacheado > fallback 1430.
    """
    if budget and getattr(budget, "fx_rate", None) and budget.fx_rate > 0:
        return Decimal(str(budget.fx_rate))

    now = time.time()
    if _mep_cache["value"] is not None and now - _mep_cache["ts"] < _MEP_TTL:
        return _mep_cache["value"]

    try:
        import httpx

        r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if r.status_code == 200:
            data = r.json()
            venta = data.get("venta") or data.get("compra")
            if venta:
                mep = Decimal(str(venta))
                _mep_cache["value"] = mep
                _mep_cache["ts"] = now
                logger.info("MEP dolarapi: %.2f (cache %dm)", float(mep), _MEP_TTL // 60)
                return mep
    except Exception as e:
        logger.warning(
            "get_mep: dolarapi.com falló (%s) — usando fallback %s", e, MEP_FALLBACK
        )

    # Si el fetch falló pero teníamos un valor cacheado (aunque vencido), úsalo
    # antes que el fallback hardcodeado.
    if _mep_cache["value"] is not None:
        return _mep_cache["value"]
    return MEP_FALLBACK
