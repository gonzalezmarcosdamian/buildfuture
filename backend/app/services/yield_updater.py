"""
Actualiza annual_yield_pct y current_price_usd de posiciones activas con datos reales.
Se llama desde el daily close job (después de los syncs, antes del snapshot).

LETRA (LECAP/LETE):
  TIR calculada desde precio actual en DB + fecha de vencimiento decodificada
  del ticker (ej: S31G6 → 31/ago/2026).  No requiere llamadas externas.
  current_price_usd se recalcula con el MEP del día (evita precio congelado al sync).

BOND / ON (soberanos USD):
  Tabla de YTM aproximadas por ticker, calibradas con precios actuales de mercado.
  Fase futura: reemplazar con data912 o IOL live TIR.

FCI:
  annual_yield_pct: promedio del rendimiento real de fondos mercadoDinero (ArgentinaDatos).
  Si la posición tiene external_id + fci_categoria, usa el yield exacto del fondo.
  current_price_usd se recalcula con MEP del día.
"""

import logging
import re
import calendar
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger("buildfuture.yields")

# ── Parseo de fecha de vencimiento desde ticker LECAP ─────────────────────────
# Formato: S[DD][M][Y]  donde M = letra inicial del mes en español,
#          Y = dígito del año (5→2025, 6→2026, 7→2027, …)
# Ejemplos: S31G6 → 31/ago/2026 | S28F6 → 28/feb/2026 | S30J6 → 30/jun/2026
_MONTH_MAP: dict[str, int] = {
    "E": 1,  # Enero
    "F": 2,  # Febrero
    "M": 3,  # Marzo
    "A": 4,  # Abril
    "Y": 5,  # maYo
    "J": 6,  # Junio
    "L": 7,  # juLio
    "G": 8,  # aGosto
    "S": 9,  # Septiembre
    "O": 10,  # Octubre
    "N": 11,  # Noviembre
    "D": 12,  # Diciembre
}
_LECAP_RE = re.compile(r"^S(\d{2})([A-Z])(\d)$")


def _parse_lecap_maturity(ticker: str) -> date | None:
    """
    Decodifica la fecha de vencimiento desde el nombre del ticker.
    S31G6  → date(2026, 8, 31)
    S28F7  → date(2027, 2, 28)
    Retorna None si el ticker no sigue el patrón.
    """
    m = _LECAP_RE.match(ticker.upper())
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTH_MAP.get(m.group(2))
    year = 2020 + int(m.group(3))
    if not month:
        return None
    # Ajustar si el día supera el último día del mes (ej: S31F6 → 28/feb)
    last = calendar.monthrange(year, month)[1]
    try:
        return date(year, month, min(day, last))
    except ValueError:
        return None


def _lecap_tir(price_per_100: Decimal, days: int) -> Decimal:
    """
    TIR anualizada (TNA) de una LECAP zero-coupon en ARS.
    price_per_100 : precio de mercado cada 100 nominales (ej: 96.5)
    days          : días hasta el vencimiento
    """
    if price_per_100 <= 0 or days <= 0:
        return Decimal("0.40")  # fallback conservador si faltan datos
    tir = (Decimal("100") / price_per_100 - Decimal("1")) * (
        Decimal("365") / Decimal(str(days))
    )
    return max(tir, Decimal("0"))


# ── YTM de bonos soberanos USD (tabla calibrada) ──────────────────────────────
# Aproximaciones basadas en precios de mercado a abril 2026.
# Actualizar cuando haya cambios estructurales de precios (±5% en precio).
# Fase 3B: reemplazar con data912 para YTM calculada desde flujos reales.
_BOND_YTM: dict[str, Decimal] = {
    # ── Soberanos ─────────────────────────────────────────────────────────────
    # Corto plazo (vto. < 2030)
    "AL29": Decimal("0.16"),
    "AL29D": Decimal("0.16"),
    "GD29": Decimal("0.14"),
    # Mediano plazo (2030–2035)
    "AL30": Decimal("0.17"),
    "AL30D": Decimal("0.17"),
    "GD30": Decimal("0.16"),
    "AL35": Decimal("0.16"),
    "AL35D": Decimal("0.16"),
    "GD35": Decimal("0.15"),
    # Largo plazo (> 2035)
    "GD38": Decimal("0.15"),
    "AE38": Decimal("0.15"),
    "AE38D": Decimal("0.15"),
    "AL41": Decimal("0.15"),
    "AL41D": Decimal("0.15"),
    "GD41": Decimal("0.15"),
    "GD46": Decimal("0.14"),
    # Bopreales
    "BPY26": Decimal("0.12"),
    "BPJ25": Decimal("0.10"),
    "BPA7": Decimal("0.11"),
    # ── ONs corporativas USD (calibradas abril 2026) ───────────────────────────
    # Precios observados en IOL. YTM estimada desde precio de mercado.
    # Fórmula proxy: si precio ≈ par (1.0), YTM ≈ cupón. Ajustar ±5% si cambia el precio.
    #
    # Telecom Argentina (TLCMO ~1.11, TLCPO ~1.11, TLCTO ~1.07) — investment grade corp
    "TLCMO": Decimal("0.07"),
    "TLCPO": Decimal("0.07"),
    "TLCTO": Decimal("0.08"),
    # Arcor (ARC1O ~1.08) — food corp, sólido
    "ARC1O": Decimal("0.07"),
    # DNC series (DNC5O ~1.06, DNC7O ~1.09) — corporativa mediana
    "DNC5O": Decimal("0.08"),
    "DNC7O": Decimal("0.07"),
    # LOC6O ~1.03 — cerca de par, plazo medio
    "LOC6O": Decimal("0.09"),
    # MR39O ~0.66 — precio con descuento significativo, mayor duration o riesgo
    "MR39O": Decimal("0.12"),
    # RUCDO ~1.07
    "RUCDO": Decimal("0.08"),
    # Vista Oil & Gas (VSCVO ~1.12) — energía, buen crédito
    "VSCVO": Decimal("0.07"),
    # YPF Metrogas series (YM34O ~1.08, YM39O ~1.12, YMCJO ~1.04)
    "YM34O": Decimal("0.08"),
    "YM39O": Decimal("0.07"),
    "YMCJO": Decimal("0.09"),
}


# ── FCI: promedio mercadoDinero como proxy ────────────────────────────────────


def _fci_market_avg_yield() -> Decimal:
    """
    Promedio TNA de fondos mercadoDinero ARS desde ArgentinaDatos.
    Proxy para FCIs sin external_id — refleja el mercado real.
    Fallback: 0.38 si la API no responde.
    """
    try:
        from app.services.fci_prices import _fetch_categoria
        import httpx
        from datetime import timedelta

        fondos = _fetch_categoria("mercadoDinero")
        if not fondos:
            return Decimal("0.38")

        # Filtrar fondos ARS (excluir USD/dolar)
        ars_fondos = [
            f
            for f in fondos
            if "dolar" not in f["fondo"].lower()
            and "usd" not in f["fondo"].lower()
            and f.get("vcp")
            and f["vcp"] > 0
        ]
        if not ars_fondos:
            return Decimal("0.38")

        # Calcular yield 30d para cada fondo — usar VCP hace 30 días
        fecha_30d = (date.today() - timedelta(days=30)).strftime("%Y/%m/%d")
        try:
            r = httpx.get(
                f"https://api.argentinadatos.com/v1/finanzas/fci/mercadoDinero/{fecha_30d}",
                headers={"Accept": "application/json", "User-Agent": "BuildFuture/1.0"},
                timeout=8,
            )
            if not r.is_success:
                return Decimal("0.38")

            prev_by_name = {
                f["fondo"].lower(): float(f["vcp"]) for f in r.json() if f.get("vcp")
            }
        except Exception:
            return Decimal("0.38")

        yields = []
        for f in ars_fondos:
            name_lower = f["fondo"].lower()
            vcp_prev = prev_by_name.get(name_lower)
            if vcp_prev and vcp_prev > 0:
                ret_30d = (f["vcp"] - vcp_prev) / vcp_prev
                tna = (1 + ret_30d) ** (365 / 30) - 1
                if 0 < tna < 5:  # filtrar outliers
                    yields.append(tna)

        if not yields:
            return Decimal("0.38")

        avg = sum(yields) / len(yields)
        logger.info(
            "FCI market avg yield: %.2f%% TNA (%d fondos)", avg * 100, len(yields)
        )
        return Decimal(str(round(avg, 4)))
    except Exception as e:
        logger.warning("_fci_market_avg_yield falló: %s", e)
        return Decimal("0.38")


# ── Punto de entrada ──────────────────────────────────────────────────────────


def update_yields(db, mep: Decimal | None = None) -> int:
    """
    Recorre todas las posiciones activas de tipo LETRA, BOND, ON y FCI,
    calcula el yield real y actualiza annual_yield_pct en la DB.
    Si se provee mep, también actualiza current_price_usd para posiciones
    denominadas en ARS (LETRA, FCI) usando el MEP del día.
    Retorna el número de posiciones actualizadas.
    """
    from app.models import Position

    today = date.today()

    # FCI market average calculado una sola vez para todo el batch
    _fci_avg: Decimal | None = None

    positions = (
        db.query(Position)
        .filter(
            Position.is_active == True,
            Position.asset_type.in_(["LETRA", "BOND", "ON", "FCI"]),
        )
        .all()
    )

    if not positions:
        return 0

    updated = 0
    for pos in positions:
        try:
            # ── Reconstruir current_value_ars si es 0 y tenemos MEP ───────
            # Posiciones antiguas (antes del campo) o syncs parciales pueden
            # tener current_value_ars=0. Si tenemos MEP del día, lo estimamos.
            if (
                mep
                and mep > 0
                and pos.asset_type in ("LETRA", "FCI")
                and (pos.current_value_ars is None or pos.current_value_ars <= 0)
                and pos.quantity > 0
                and pos.current_price_usd > 0
            ):
                pos.current_value_ars = pos.quantity * pos.current_price_usd * mep
                logger.info(
                    "yield_updater %s %s: current_value_ars reconstruido = %.2f ARS (desde price_usd × mep)",
                    pos.asset_type,
                    pos.ticker,
                    float(pos.current_value_ars),
                )

            # ── yield ──────────────────────────────────────────────────────
            if pos.asset_type == "FCI":
                if _fci_avg is None:
                    _fci_avg = _fci_market_avg_yield()
                new_yield = _yield_fci(pos, _fci_avg)
            else:
                new_yield = _compute_yield(pos, today)

            changed = False
            if new_yield is not None and new_yield != pos.annual_yield_pct:
                old = float(pos.annual_yield_pct) * 100
                pos.annual_yield_pct = new_yield
                logger.info(
                    "yield_updater %s %s: %.1f%% → %.1f%%",
                    pos.asset_type,
                    pos.ticker,
                    old,
                    float(new_yield) * 100,
                )
                changed = True

            # ── current_price_usd con MEP del día (LETRA y FCI en ARS) ───
            if mep and mep > 0 and pos.asset_type in ("LETRA", "FCI"):
                if pos.quantity > 0 and pos.current_value_ars > 0:
                    new_price_usd = pos.current_value_ars / (pos.quantity * mep)
                    if abs(new_price_usd - pos.current_price_usd) > Decimal("0.000001"):
                        pos.current_price_usd = new_price_usd
                        changed = True

            if changed:
                updated += 1
        except Exception as e:
            logger.warning(
                "yield_updater error en %s %s: %s", pos.asset_type, pos.ticker, e
            )

    if updated:
        db.commit()
    logger.info("yield_updater: %d/%d posiciones actualizadas", updated, len(positions))
    return updated


def _compute_yield(pos, today: date) -> Decimal | None:
    """Despacha el cálculo según tipo de activo (no-FCI)."""
    if pos.asset_type == "LETRA":
        return _yield_lecap(pos, today)
    if pos.asset_type in ("BOND", "ON"):
        return _yield_bond(pos)
    return None


def _yield_lecap(pos, today: date) -> Decimal | None:
    """
    TIR real de una LECAP de descuento (prefijo S):
      1. Decodifica vencimiento desde el ticker.
      2. Calcula precio por 100 nominales usando current_value_ars / quantity.
      3. Devuelve TNA = (100/precio - 1) × (365/días).

    Letras CER (prefijo X, ej: X29Y6): ajustan VN diariamente por índice CER.
    La fórmula de descuento es incorrecta para ellas — la métrica correcta es TIR real
    (rendimiento por encima del CER), que requiere el índice BCRA.
    Quick fix: retornar Decimal("0") para que no aparezca un 68% inventado.
    Fix definitivo pendiente en backlog: implementar CER client + TIR real.
    """
    ticker_upper = pos.ticker.upper()
    if ticker_upper.startswith("X"):
        logger.info(
            "LETRA CER %s: prefijo X detectado — yield=0 (TIR real pendiente de implementar)",
            pos.ticker,
        )
        return Decimal("0")

    maturity = _parse_lecap_maturity(pos.ticker)
    if maturity is None:
        logger.debug("LECAP %s: ticker no parseble — sin actualización", pos.ticker)
        return None

    days = (maturity - today).days
    if days <= 1:
        # Vencida o vence hoy: yield 0
        return Decimal("0")

    if pos.quantity <= 0 or pos.current_value_ars <= 0:
        return None

    # IOL valora LECAPs por nominal; current_value_ars = cantidad_nominales × precio_ars_por_nominal
    # precio por 100 nominales = (current_value_ars / quantity) × 100
    price_per_100 = (pos.current_value_ars / pos.quantity) * Decimal("100")

    # Las LECAPs argentinas capitalizan diariamente: el "precio técnico" en el portafolio de
    # IOL incluye los intereses acumulados desde la emisión y puede superar 100.
    # La fórmula (100/precio - 1) asume madurez = 100, lo que da TIR negativa → 0 (incorrecto).
    # Cuando precio >= 100 la TIR real solo se puede calcular desde el precio de cotización
    # (endpoint IOL distinto, VN=1000). Devolvemos el DEFAULT TNA conocido de mercado (~68%)
    # para que la posición no quede en 0% si el updater corrió antes de esta corrección.
    _LECAP_DEFAULT_TNA = Decimal("0.68")
    if price_per_100 >= Decimal("100"):
        if pos.annual_yield_pct != _LECAP_DEFAULT_TNA:
            logger.info(
                "LECAP %s: precio/100=%.2f >= par (técnico acumulado) → restaurando TNA default %.0f%%",
                pos.ticker,
                float(price_per_100),
                float(_LECAP_DEFAULT_TNA) * 100,
            )
            return _LECAP_DEFAULT_TNA
        return None

    tir = _lecap_tir(price_per_100, days)
    logger.info(
        "LECAP %s: vto=%s días=%d precio/100=%.4f TIR=%.2f%%",
        pos.ticker,
        maturity,
        days,
        float(price_per_100),
        float(tir) * 100,
    )
    return tir


def _yield_bond(pos) -> Decimal | None:
    """YTM del bono desde la tabla calibrada. None si el ticker no es conocido."""
    ytm = _BOND_YTM.get(pos.ticker.upper())
    if ytm is not None:
        logger.info("BOND/ON %s: YTM=%.2f%% (tabla)", pos.ticker, float(ytm) * 100)
    return ytm


def _yield_fci(pos, market_avg: Decimal) -> Decimal | None:
    """
    TNA real de un FCI:
    1. Si tiene external_id + fci_categoria → yield exacto del fondo (ArgentinaDatos).
    2. Si no → promedio mercadoDinero ARS ya calculado.
    """
    if pos.external_id and pos.fci_categoria:
        try:
            from app.services.fci_prices import get_yield_30d

            y = get_yield_30d(pos.external_id, pos.fci_categoria)
            # Sanity: TNA > 150% sugiere match incorrecto o dato corrupto en ArgentinaDatos.
            # Los fondos mercadoDinero ARS nunca superan ~80% TNA real; 150% es el límite extremo.
            if 0 < y < 1.5:
                result = Decimal(str(round(y, 4)))
                logger.info(
                    "FCI %s: TNA=%.2f%% (ArgentinaDatos)",
                    pos.ticker,
                    float(result) * 100,
                )
                return result
            if y >= 1.5:
                logger.warning(
                    "FCI %s: TNA=%.2f%% fuera de rango → usando promedio",
                    pos.ticker,
                    y * 100,
                )
        except Exception as e:
            logger.debug(
                "FCI %s: ArgentinaDatos falló (%s) → usando promedio", pos.ticker, e
            )

    logger.info(
        "FCI %s: TNA=%.2f%% (promedio mercado)", pos.ticker, float(market_avg) * 100
    )
    return market_avg
