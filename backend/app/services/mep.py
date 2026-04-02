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

logger = logging.getLogger("buildfuture.mep")

MEP_FALLBACK = Decimal("1430")


def get_mep(budget=None) -> Decimal:
    """
    Retorna el MEP actual como Decimal.
    Nunca retorna 0 — el fallback es 1430.
    """
    if budget and getattr(budget, "fx_rate", None) and budget.fx_rate > 0:
        return Decimal(str(budget.fx_rate))

    try:
        import httpx
        r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if r.status_code == 200:
            data = r.json()
            venta = data.get("venta") or data.get("compra")
            if venta:
                mep = Decimal(str(venta))
                logger.info("MEP dolarapi: %.2f", float(mep))
                return mep
    except Exception as e:
        logger.warning("get_mep: dolarapi.com falló (%s) — usando fallback %s", e, MEP_FALLBACK)

    return MEP_FALLBACK
