"""
ArgentinaDatos API — cuotapartes de FCI argentinos y letras del Tesoro.
Fuente: https://api.argentinadatos.com/v1/finanzas/fci/{categoria}/{fecha}
         https://api.argentinadatos.com/v1/finanzas/letras
Pública, sin API key. Cubre todos los fondos registrados en CAFCI y LECAPs vigentes.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import httpx

logger = logging.getLogger("buildfuture.fci")

ARGDATA_BASE = "https://api.argentinadatos.com/v1/finanzas/fci"
ARGDATA_LETRAS_URL = "https://api.argentinadatos.com/v1/finanzas/letras"
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


# ── LECAPs via ArgentinaDatos ──────────────────────────────────────────────────

_letras_cache: dict = {"data": {}, "ts": 0.0}
_LETRAS_CACHE_TTL = 600  # 10 minutos


def _fetch_letras() -> dict[str, dict]:
    """
    Descarga todas las letras de ArgentinaDatos y devuelve un dict {ticker: {vpv, vencimiento}}.
    Cache de 10 min. Usado como fallback cuando BYMA devuelve 400.
    """
    now = time.time()
    if _letras_cache["data"] and now - _letras_cache["ts"] < _LETRAS_CACHE_TTL:
        return _letras_cache["data"]

    try:
        r = httpx.get(ARGDATA_LETRAS_URL, headers=_HEADERS, timeout=10)
        if not r.is_success:
            logger.warning("ArgentinaDatos letras: HTTP %s", r.status_code)
            return _letras_cache["data"]  # devolver cache anterior si hay

        data: dict[str, dict] = {}
        for item in r.json():
            ticker = str(item.get("ticker") or "").upper()
            vpv = item.get("vpv")
            vto = item.get("fechaVencimiento") or item.get("vencimiento") or ""
            if ticker and vpv and vpv > 0 and vto:
                data[ticker] = {"vpv": float(vpv), "vencimiento": vto[:10]}

        _letras_cache["data"] = data
        _letras_cache["ts"] = now
        logger.info("ArgentinaDatos letras: %d letras cacheadas: %s", len(data), list(data.keys())[:5])
        return data

    except Exception as e:
        logger.warning("ArgentinaDatos letras falló (%s)", e)
        return _letras_cache["data"]


def get_lecap_tna_by_ticker(ticker: str) -> float | None:
    """
    Retorna la TNA (en %, ej: 32.5) de una LECAP específica usando ArgentinaDatos.

    Calcula TNA desde precio de mercado (vpv) y vencimiento:
      TNA = (100 / vpv - 1) × (365 / días_al_vto) × 100

    Retorna None si:
    - ArgentinaDatos no responde
    - El ticker no está en la respuesta
    - vpv >= 100 (precio sobre la par — fórmula inválida, igual que en yield_updater)
    - días al vencimiento <= 0

    El caller debe usar un fallback (ej: promedio de mercado get_lecap_tna() o 32% hardcodeado).
    """
    letras = _fetch_letras()
    item = letras.get(ticker.upper())
    if not item:
        logger.debug("get_lecap_tna_by_ticker: %s no encontrado en ArgentinaDatos", ticker)
        return None

    vpv = item["vpv"]
    if vpv >= 100:
        # precio sobre la par: la fórmula de descuento no aplica
        logger.debug("get_lecap_tna_by_ticker: %s vpv=%.4f >= 100, fórmula no aplica", ticker, vpv)
        return None

    try:
        vto = date.fromisoformat(item["vencimiento"])
        days = (vto - date.today()).days
        if days <= 0:
            logger.debug("get_lecap_tna_by_ticker: %s ya venció o vence hoy", ticker)
            return None

        tna_pct = (100 / vpv - 1) * (365 / days) * 100
        logger.info(
            "get_lecap_tna_by_ticker: %s vpv=%.4f días=%d TNA=%.2f%%",
            ticker, vpv, days, tna_pct,
        )
        return round(tna_pct, 2)

    except Exception as e:
        logger.warning("get_lecap_tna_by_ticker: error calculando TNA para %s: %s", ticker, e)
        return None


def get_lecap_market_tna() -> float | None:
    """
    Retorna la TNA promedio ponderada (por vpv) de todas las LECAPs vigentes en ArgentinaDatos.
    Solo incluye letras con ticker S-prefix (nominales, no CER).
    Retorna None si no hay datos válidos.
    Usado como fallback de get_lecap_tna() cuando BYMA devuelve 400.
    """
    letras = _fetch_letras()
    if not letras:
        return None

    today = date.today()
    total_weight = 0.0
    weighted_sum = 0.0

    for ticker, item in letras.items():
        if not ticker.startswith("S"):
            continue  # excluir CER (X-prefix) y otros
        vpv = item["vpv"]
        if vpv <= 0 or vpv >= 100:
            continue
        try:
            vto = date.fromisoformat(item["vencimiento"])
            days = (vto - today).days
            if days <= 0:
                continue
            tna = (100 / vpv - 1) * (365 / days)
            weight = 1 / vpv  # peso inversamente proporcional al precio (más barato = más activo)
            weighted_sum += tna * weight
            total_weight += weight
        except Exception:
            continue

    if total_weight == 0:
        return None

    return round(weighted_sum / total_weight * 100, 2)
