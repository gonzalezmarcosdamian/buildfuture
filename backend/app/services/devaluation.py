"""
Estimación dinámica de la devaluación ARS/USD (MEP) esperada a 12 meses.

Reemplaza el DEVALUATION_PROXY = 0.15 hardcodeado en freedom_calculator.py.

Jerarquía de fuentes (de mayor a menor precisión):
  1. ROFEX — futuros ARS/USD a 360d (API pública, sin auth)
     Devaluación implícita directa: (futuro/spot)^(365/días) - 1
  2. Paridad LECAP TEA vs ON USD (BYMA ya autenticado)
     (1 + tea_lecap) / (1 + tir_on_usd) - 1
  3. MEP trend 60 días desde DB (MepHistory via bluelytics)
     (mep_hoy / mep_60d_ago)^(365/60) - 1
  4. Crawling peg oficial + spread histórico buffer
     Fallback: 0.20 (20% anual — conservador pero más real que el 15%)

Cache in-memory TTL 4 horas (la devaluación implícita no cambia intraday).

Uso:
  from app.services.devaluation import get_expected_devaluation
  deval = get_expected_devaluation(db=db)  # Decimal, ej: Decimal("0.27")
"""

import logging
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx

logger = logging.getLogger("buildfuture.devaluation")

# ── Sanity bounds ───────────────────────────────────────────────────────────────
DEVALUATION_MIN = 0.08   # 8% — piso: crawling peg mínimo posible
DEVALUATION_MAX = 0.80   # 80% — techo: si da más, dato corrupto
DEVALUATION_FALLBACK = Decimal("0.20")  # 20% — más realista que el 15% previo

# Cache in-memory: (value: Decimal | None, ts: float, source: str)
_cache: dict = {"value": None, "ts": 0.0, "source": "none"}
CACHE_TTL = 4 * 3600  # 4 horas


# ── TIR de ONs USD — tabla fallback mientras BYMA no expone impliedYield ────────
# ONs corporativas hard-dollar, vencimiento 2026-2027, spread investment grade ARG.
# Fuente: IAMC / Refinitiv estimado (actualizar trimestralmente).
_ON_USD_TIR_TABLE: dict[str, float] = {
    "YCA6O": 8.5,    # YPF 2026
    "YMCHO": 8.2,    # YPF 2027
    "RPC2O": 7.8,    # Raghsa 2026
    "TLC5O": 9.0,    # Telecom 2025
    "PDVCO": 9.5,    # default — proxy genérico investment grade ARG
}
_ON_USD_TIR_GENERIC = 9.0  # % — proxy si no hay ticker específico


# ── Fuente 1: ROFEX futuros ─────────────────────────────────────────────────────

def _from_rofex(mep_spot: float) -> float | None:
    """
    Consulta la API pública de ROFEX/MatbaRofex para el futuro ARS/USD más largo
    disponible (target: ~360 días). Sin autenticación requerida.

    Endpoint descubierto via ingeniería inversa del front de ROFEX:
      GET https://api.rofex.com.ar/api/DOLAR_BILLETE_BAJA  (no requiere auth)
    También probamos el endpoint de Matba:
      GET https://api.matbarofex.com.ar/v1/derivatives/futures/DOLBT_NEAR_ND

    Retorna devaluación anual implícita como float (ej: 0.27) o None si falla.
    """
    endpoints = [
        # Endpoint 1: API pública Matba-Rofex (confirmado acceso público 2025)
        "https://api.matbarofex.com.ar/v1/derivatives/futures",
        # Endpoint 2: datos de mercado en tiempo real (panel público)
        "https://www.rofex.com.ar/api/futuros/dolar",
    ]

    for url in endpoints:
        try:
            r = httpx.get(
                url,
                timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0),
                headers={"User-Agent": "Mozilla/5.0 (compatible; BuildFuture/1.0)"},
                follow_redirects=True,
            )
            if r.status_code != 200:
                continue

            data = r.json()
            # Parsear según estructura de cada API — adaptable
            quotes = data if isinstance(data, list) else data.get("data", data.get("quotes", []))
            if not quotes:
                continue

            today = date.today()
            best_dias = 0
            best_precio = None

            for item in quotes:
                # Distintos campos según el endpoint
                maturity_str = (
                    item.get("maturityDate") or item.get("expirationDate")
                    or item.get("fechaVencimiento") or ""
                )
                precio = (
                    item.get("settlementPrice") or item.get("lastPrice")
                    or item.get("precio") or item.get("close") or 0
                )

                if not maturity_str or not precio:
                    continue

                try:
                    mat = date.fromisoformat(str(maturity_str)[:10])
                except (ValueError, TypeError):
                    continue

                dias = (mat - today).days
                # Buscar el contrato más cercano a 365 días (entre 90 y 400)
                if 90 <= dias <= 400 and dias > best_dias:
                    best_dias = dias
                    best_precio = float(precio)

            if best_precio and best_dias > 0 and mep_spot > 0:
                deval = (best_precio / mep_spot) ** (365 / best_dias) - 1
                logger.info(
                    "devaluation ROFEX: futuro=%.2f spot=%.2f días=%d → %.2f%%",
                    best_precio, mep_spot, best_dias, deval * 100,
                )
                return deval

        except Exception as e:
            logger.debug("devaluation ROFEX %s falló: %s", url, e)

    return None


# ── Fuente 2: Paridad LECAP TEA vs ON USD ──────────────────────────────────────

def _from_lecap_on_parity() -> float | None:
    """
    Calcula la devaluación implícita via Interest Rate Parity:
      devaluation = (1 + TEA_ARS) / (1 + TIR_USD) - 1

    Usa get_lecap_tna() (ya implementado en byma_client) como TEA_ARS.
    Usa tabla fallback para TIR_USD mientras BYMA no expone impliedYield.

    Este método refleja exactamente lo que el mercado descuenta porque
    los ALYCs arbitran continuamente entre LECAPs y ONs USD.
    """
    try:
        from app.services.byma_client import get_lecap_tna, get_on_tir

        tea_lecap_pct = get_lecap_tna()  # ej: 38.5 (porcentaje)
        if not tea_lecap_pct or tea_lecap_pct <= 0:
            return None
        tea_lecap = tea_lecap_pct / 100  # → decimal 0.385

        # Intentar TIR de ON desde BYMA (actualmente retorna None — impliedYield null)
        tir_on_pct = None
        for on_ticker in _ON_USD_TIR_TABLE:
            tir_on_pct = get_on_tir(on_ticker)
            if tir_on_pct:
                break

        # Usar tabla fallback si BYMA no expone TIR
        if not tir_on_pct:
            tir_on_pct = _ON_USD_TIR_GENERIC
            logger.debug("devaluation paridad: usando TIR ON fallback %.1f%%", tir_on_pct)

        tir_on = tir_on_pct / 100  # → decimal 0.09

        deval = (1 + tea_lecap) / (1 + tir_on) - 1
        logger.info(
            "devaluation paridad LECAP/ON: TEA_ARS=%.2f%% TIR_USD=%.2f%% → deval=%.2f%%",
            tea_lecap_pct, tir_on_pct, deval * 100,
        )
        return deval

    except Exception as e:
        logger.warning("devaluation paridad falló: %s", e)
        return None


# ── Fuente 3: MEP trend 60 días desde DB ───────────────────────────────────────

def _from_mep_trend(db) -> float | None:
    """
    Anualiza la depreciación observada del MEP en los últimos 60 días.
    Usa MepHistory almacenada en DB (ya se llena via bluelytics en historical_prices).

    60 días da suficiente señal sin ser ruidoso (30d) ni demasiado rezagado (90d).
    """
    if db is None:
        return None
    try:
        from app.models import MepHistory

        today = date.today()
        cutoff = today - timedelta(days=70)  # buscar desde 70d para asegurar 60d de datos

        rows = (
            db.query(MepHistory)
            .filter(MepHistory.price_date >= cutoff)
            .order_by(MepHistory.price_date.asc())
            .all()
        )

        if len(rows) < 10:  # necesitamos al menos 10 puntos para que sea confiable
            logger.debug("devaluation MEP trend: solo %d filas — insuficiente", len(rows))
            return None

        oldest = rows[0]
        newest = rows[-1]
        elapsed = (newest.price_date - oldest.price_date).days

        if elapsed < 20 or float(oldest.mep_value) <= 0:
            return None

        deval = (float(newest.mep_value) / float(oldest.mep_value)) ** (365 / elapsed) - 1
        logger.info(
            "devaluation MEP trend: %.2f → %.2f en %dd → %.2f%% anual",
            float(oldest.mep_value), float(newest.mep_value), elapsed, deval * 100,
        )
        return deval

    except Exception as e:
        logger.warning("devaluation MEP trend falló: %s", e)
        return None


# ── API pública ─────────────────────────────────────────────────────────────────

def get_expected_devaluation(db=None) -> Decimal:
    """
    Retorna la devaluación ARS/USD (MEP) esperada a 12 meses como Decimal.
    Ej: Decimal("0.27") = 27% anual.

    Jerarquía:
      1. ROFEX futuros a 360d
      2. Paridad LECAP TEA / ON USD
      3. MEP trend 60 días (requiere db)
      4. Fallback conservador 20%

    Cache TTL 4 horas — la devaluación implícita no cambia intraday.
    Nunca retorna fuera de [DEVALUATION_MIN, DEVALUATION_MAX].
    """
    now = time.time()
    if _cache["value"] is not None and now - _cache["ts"] < CACHE_TTL:
        logger.debug(
            "devaluation: cache hit → %.2f%% (fuente: %s)",
            float(_cache["value"]) * 100, _cache["source"],
        )
        return _cache["value"]

    # Necesitamos MEP spot para ROFEX
    mep_spot = 0.0
    try:
        from app.services.mep import get_mep
        mep_spot = float(get_mep())
    except Exception:
        pass

    # Intentar fuentes en orden
    deval_raw: float | None = None
    source = "fallback"

    # Fuente 1: ROFEX
    deval_raw = _from_rofex(mep_spot)
    if deval_raw is not None:
        source = "rofex"

    # Fuente 2: Paridad LECAP/ON
    if deval_raw is None:
        deval_raw = _from_lecap_on_parity()
        if deval_raw is not None:
            source = "lecap_on_parity"

    # Fuente 3: MEP trend
    if deval_raw is None:
        deval_raw = _from_mep_trend(db)
        if deval_raw is not None:
            source = "mep_trend_60d"

    # Aplicar sanity bounds
    if deval_raw is not None and DEVALUATION_MIN <= deval_raw <= DEVALUATION_MAX:
        result = Decimal(str(round(deval_raw, 4)))
    else:
        if deval_raw is not None:
            logger.warning(
                "devaluation: valor %.2f%% fuera de bounds [%.0f%%, %.0f%%] — usando fallback",
                deval_raw * 100, DEVALUATION_MIN * 100, DEVALUATION_MAX * 100,
            )
        result = DEVALUATION_FALLBACK
        source = "fallback"

    _cache["value"] = result
    _cache["ts"] = now
    _cache["source"] = source

    logger.info(
        "devaluation expected: %.2f%% anual (fuente: %s)", float(result) * 100, source
    )
    return result


def invalidate_cache() -> None:
    """Fuerza refresco en la próxima llamada. Útil para tests y admin endpoints."""
    _cache["value"] = None
    _cache["ts"] = 0.0
    _cache["source"] = "none"
