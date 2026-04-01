"""
ArgentinaDatos API — cuotapartes de FCI argentinos.
Fuente: https://api.argentinadatos.com/v1/finanzas/fci/{categoria}/{fecha}
Pública, sin API key. Cubre todos los fondos registrados en CAFCI.
"""
import logging
from functools import lru_cache
import httpx

logger = logging.getLogger("buildfuture.fci")

ARGDATA_BASE = "https://api.argentinadatos.com/v1/finanzas/fci"
_HEADERS = {"Accept": "application/json", "User-Agent": "BuildFuture/0.9"}

CATEGORIAS = ["mercadoDinero", "rentaFija", "rentaVariable", "rentaMixta", "otros"]


def search_fci(query: str) -> list[dict]:
    """
    Busca fondos por nombre en todas las categorías de ArgentinaDatos.
    Retorna lista [{fondo, categoria, vcp, fecha}].
    """
    query_lower = query.lower()
    results = []
    for cat in CATEGORIAS:
        try:
            r = httpx.get(f"{ARGDATA_BASE}/{cat}/ultimo",
                          headers=_HEADERS, timeout=10)
            if not r.is_success:
                continue
            fondos = r.json()
            for f in fondos:
                nombre = f.get("fondo", "")
                if query_lower in nombre.lower():
                    results.append({
                        "fondo": nombre,
                        "categoria": cat,
                        "vcp": f.get("vcp"),
                        "fecha": f.get("fecha"),
                        "horizonte": f.get("horizonte"),
                    })
        except Exception as e:
            logger.warning("ArgentinaDatos %s falló: %s", cat, e)
    # Deduplicar por nombre exacto — puede aparecer en varias categorías
    seen = set()
    deduped = []
    for r in results:
        key = r["fondo"]
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped[:15]


def get_vcp(fondo_name: str, categoria: str) -> float | None:
    """VCP (valor cuotaparte) actual para el fondo y categoría dados."""
    try:
        r = httpx.get(f"{ARGDATA_BASE}/{categoria}/ultimo",
                      headers=_HEADERS, timeout=10)
        r.raise_for_status()
        for f in r.json():
            if f.get("fondo", "").lower() == fondo_name.lower():
                return float(f["vcp"])
    except Exception as e:
        logger.warning("get_vcp falló (%s/%s): %s", categoria, fondo_name, e)
    return None


def get_yield_30d(fondo_name: str, categoria: str) -> float:
    """
    TNA implícita calculada de la variación de VCP en los últimos ~30 días.
    Usa el penúltimo dato vs el último (ambos disponibles en ArgentinaDatos).
    Para mayor precisión usa una fecha 30 días atrás si está disponible.
    """
    from datetime import date, timedelta
    try:
        vcp_hoy = get_vcp(fondo_name, categoria)
        if not vcp_hoy:
            return 0.0

        # Intentar fecha hace 30 días
        fecha_30d = (date.today() - timedelta(days=30)).strftime("%Y/%m/%d")
        r = httpx.get(f"{ARGDATA_BASE}/{categoria}/{fecha_30d}",
                      headers=_HEADERS, timeout=10)
        if r.is_success:
            for f in r.json():
                if f.get("fondo", "").lower() == fondo_name.lower():
                    vcp_30d = float(f["vcp"])
                    if vcp_30d > 0:
                        rendimiento_30d = (vcp_hoy - vcp_30d) / vcp_30d
                        tna = (1 + rendimiento_30d) ** (365 / 30) - 1
                        return round(float(tna), 4)

        # Fallback: penúltimo vs último (estimación menos precisa)
        r2 = httpx.get(f"{ARGDATA_BASE}/{categoria}/penultimo",
                       headers=_HEADERS, timeout=10)
        if r2.is_success:
            for f in r2.json():
                if f.get("fondo", "").lower() == fondo_name.lower():
                    vcp_prev = float(f["vcp"])
                    if vcp_prev > 0:
                        rendimiento_dia = (vcp_hoy - vcp_prev) / vcp_prev
                        tna = (1 + rendimiento_dia) ** 365 - 1
                        return round(float(tna), 4)
    except Exception as e:
        logger.warning("get_yield_30d FCI falló (%s): %s", fondo_name, e)
    return 0.0
