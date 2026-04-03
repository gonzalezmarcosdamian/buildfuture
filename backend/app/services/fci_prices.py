"""
ArgentinaDatos API — cuotapartes de FCI argentinos.
Fuente: https://api.argentinadatos.com/v1/finanzas/fci/{categoria}/{fecha}
Pública, sin API key. Cubre todos los fondos registrados en CAFCI.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

logger = logging.getLogger("buildfuture.fci")

ARGDATA_BASE = "https://api.argentinadatos.com/v1/finanzas/fci"
_HEADERS = {"Accept": "application/json", "User-Agent": "BuildFuture/0.9"}

CATEGORIAS = ["mercadoDinero", "rentaFija", "rentaVariable", "rentaMixta", "otros"]

# Cache en memoria: {categoria: (timestamp, [fondos])}
_CACHE: dict[str, tuple[float, list]] = {}
_CACHE_TTL = 900  # 15 minutos — VCP se actualiza una vez al día


def _fetch_categoria(cat: str) -> list[dict]:
    """Trae todos los fondos de una categoría. Usa cache con TTL."""
    now = time.monotonic()
    cached = _CACHE.get(cat)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        r = httpx.get(f"{ARGDATA_BASE}/{cat}/ultimo", headers=_HEADERS, timeout=10)
        if not r.is_success:
            return []
        fondos = [
            {
                "fondo": f.get("fondo", ""),
                "categoria": cat,
                "vcp": f.get("vcp"),
                "fecha": f.get("fecha"),
                "horizonte": f.get("horizonte"),
            }
            for f in r.json()
            if f.get("fondo") and f.get("vcp") is not None
        ]
        _CACHE[cat] = (now, fondos)
        return fondos
    except Exception as e:
        logger.warning("ArgentinaDatos %s falló: %s", cat, e)
        return cached[1] if cached else []


def _all_fondos() -> list[dict]:
    """Carga todas las categorías en paralelo y devuelve lista deduplicada."""
    all_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_fetch_categoria, cat): cat for cat in CATEGORIAS}
        for future in as_completed(futures):
            all_results.extend(future.result())

    seen: set[str] = set()
    deduped: list[dict] = []
    for item in all_results:
        key = item["fondo"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def search_fci(query: str) -> list[dict]:
    """
    Filtra fondos por nombre. Sin query devuelve todos.
    La carga paralela + cache hace que sea rápido desde la segunda llamada.
    """
    fondos = _all_fondos()
    if not query:
        return fondos
    q = query.lower()
    return [f for f in fondos if q in f["fondo"].lower()]


def get_vcp(fondo_name: str, categoria: str) -> float | None:
    """VCP (valor cuotaparte) actual para el fondo y categoría dados. Usa cache."""
    fondos = _fetch_categoria(categoria)
    name_lower = fondo_name.lower()
    for f in fondos:
        if f["fondo"].lower() == name_lower:
            return float(f["vcp"]) if f.get("vcp") else None
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
        r = httpx.get(
            f"{ARGDATA_BASE}/{categoria}/{fecha_30d}", headers=_HEADERS, timeout=10
        )
        if r.is_success:
            for f in r.json():
                if f.get("fondo", "").lower() == fondo_name.lower():
                    vcp_30d = float(f["vcp"])
                    if vcp_30d > 0:
                        rendimiento_30d = (vcp_hoy - vcp_30d) / vcp_30d
                        tna = (1 + rendimiento_30d) ** (365 / 30) - 1
                        return round(float(tna), 4)

        # Fallback: penúltimo vs último (estimación menos precisa)
        r2 = httpx.get(
            f"{ARGDATA_BASE}/{categoria}/penultimo", headers=_HEADERS, timeout=10
        )
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
