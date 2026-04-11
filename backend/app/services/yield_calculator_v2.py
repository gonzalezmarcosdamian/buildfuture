"""
Yield Calculator v2 — cálculo de yields desde datos propios almacenados.

Jerarquía de precisión (de mayor a menor):
  1. compute_position_actual_return()  — retorno real observado desde PositionSnapshot
     Captura todo: apreciación, devaluación, cupones reinvertidos.
     Requiere >= 7 días de snapshots con value_ars/mep para ARS, value_usd para USD.

  2. compute_lecap_tea()               — TEA desde precio almacenado + metadata estática
     Sin llamadas a BYMA en runtime. Requiere instrument_metadata + instrument_prices.

  3. compute_bond_yield()              — retorno observado desde precios históricos
     Elimina _BOND_YTM hardcodeado. Requiere >= 7 días en instrument_prices.

  4. compute_fci_yield()               — TNA desde VCP histórico propio
     Elimina ArgentinaDatos en runtime. Requiere >= 2 días de VCP.

Cuando retorna None → el caller usa el sistema actual (BYMA/ArgentinaDatos) como bootstrap.
yield_currency:
  'USD' → el yield ya está en términos USD reales (viene de retorno observado con MEP)
  'ARS' → yield nominal ARS (sistema actual — pendiente conversión a USD)
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger("buildfuture.yield_v2")

# Ventana de días para calcular retorno anualizado
DEFAULT_WINDOW_DAYS = 30
MIN_DAYS_REQUIRED = 7      # mínimo para que el cálculo sea confiable


def compute_position_actual_return(
    db,
    user_id: str,
    ticker: str,
    asset_type: str,
    days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[Decimal, str] | tuple[None, None]:
    """
    Retorno real anualizado desde el historial de PositionSnapshot del usuario.
    Para ARS (LECAP, FCI): usa value_ars/mep → captura efecto devaluación.
    Para USD (BOND, ON, CEDEAR): usa value_usd directamente.

    Retorna (yield_decimal, currency) donde currency es 'USD' si usó mep, 'ARS' si no.
    Retorna (None, None) si no hay datos suficientes.
    """
    from app.models import PositionSnapshot

    snaps = (
        db.query(PositionSnapshot)
        .filter(
            PositionSnapshot.user_id == user_id,
            PositionSnapshot.ticker == ticker,
        )
        .order_by(PositionSnapshot.snapshot_date.asc())
        .all()
    )

    if len(snaps) < 2:
        return None, None

    newest = snaps[-1]
    cutoff = newest.snapshot_date - timedelta(days=days)
    window = [s for s in snaps if s.snapshot_date >= cutoff]

    if len(window) < 2:
        window = snaps  # usar toda la historia disponible

    oldest = window[0]
    elapsed = (newest.snapshot_date - oldest.snapshot_date).days
    if elapsed < 3:
        return None, None

    # ARS instruments: SOLO usar si value_ars/mep están disponibles en ambos extremos.
    # NO usar value_usd como fallback — para ARS instruments value_usd = ars/mep_del_sync
    # y cambia con el MEP, no con el yield real del instrumento.
    if asset_type in ("LETRA", "FCI"):
        if (
            oldest.value_ars and newest.value_ars
            and oldest.mep and newest.mep
            and float(oldest.mep) > 0
        ):
            usd_old = float(oldest.value_ars) / float(oldest.mep)
            usd_new = float(newest.value_ars) / float(newest.mep)
            currency = "USD"
        else:
            # Sin value_ars/mep en snapshots viejos — no hay forma confiable de calcular
            return None, None
    else:
        usd_old = float(oldest.value_usd)
        usd_new = float(newest.value_usd)
        currency = "USD"  # value_usd siempre es USD

    if usd_old <= 0:
        return None, None

    raw = (usd_new / usd_old - 1) * (365 / elapsed)

    # Sanity: entre -50% y +200% anual
    if -0.5 <= raw <= 2.0:
        logger.info(
            "yield_v2 position_actual %s/%s: %.2f%% USD (%dd)",
            ticker, user_id[:8], raw * 100, elapsed,
        )
        return Decimal(str(round(raw, 4))), currency

    logger.warning("yield_v2 position_actual %s: raw=%.2f%% fuera de rango", ticker, raw * 100)
    return None, None


def compute_lecap_tea(
    ticker: str,
    price_date: date,
    db,
) -> tuple[Decimal, str] | tuple[None, None]:
    """
    TEA de mercado de una LECAP desde metadata estática + precio almacenado.
    Fórmula: VNV = 100 × (1+TEM)^meses_totales ; TEA = (VNV/vwap)^(365/días) - 1
    No llama a BYMA en runtime.

    Retorna (tea_decimal, 'ARS') o (None, None) si faltan datos.
    """
    from app.models import InstrumentMetadata, InstrumentPrice

    meta = db.get(InstrumentMetadata, ticker.upper())
    if not meta or not meta.tem or not meta.maturity_date or not meta.emision_date:
        return None, None

    # Precio: buscar en instrument_prices para la fecha pedida o el más reciente
    price_row = (
        db.query(InstrumentPrice)
        .filter(
            InstrumentPrice.ticker == ticker.upper(),
            InstrumentPrice.price_date <= price_date,
        )
        .order_by(InstrumentPrice.price_date.desc())
        .first()
    )

    if not price_row or not price_row.vwap or price_row.vwap <= 0:
        return None, None

    days = (meta.maturity_date - price_date).days
    if days <= 0:
        return Decimal("0"), "ARS"

    total_months = (meta.maturity_date - meta.emision_date).days / 30.4375
    vnv = Decimal("100") * (1 + meta.tem) ** Decimal(str(total_months))

    if vnv <= 0:
        return None, None

    tea = (vnv / price_row.vwap) ** (Decimal("365") / Decimal(str(days))) - 1
    tea_f = float(tea)

    if -0.1 <= tea_f <= 5.0:
        logger.info(
            "yield_v2 lecap_tea %s: vwap=%.4f TEA=%.2f%% (%dd restantes)",
            ticker, float(price_row.vwap), tea_f * 100, days,
        )
        return tea.quantize(Decimal("0.0001")), "ARS"

    logger.warning("yield_v2 lecap_tea %s: TEA=%.2f%% fuera de rango", ticker, tea_f * 100)
    return None, None


def compute_bond_yield(
    ticker: str,
    db,
    days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[Decimal, str] | tuple[None, None]:
    """
    Retorno anualizado observado de un BOND/ON desde sus precios históricos almacenados.
    Para bonos USD (ticker con D-suffix o GD/AL prefix): convierte ARS vwap a USD via mep.
    Elimina la tabla _BOND_YTM estática.

    Retorna (yield_decimal, 'USD') o (None, None) si faltan datos.
    """
    from app.models import InstrumentPrice, InstrumentMetadata

    prices = (
        db.query(InstrumentPrice)
        .filter(InstrumentPrice.ticker == ticker.upper())
        .order_by(InstrumentPrice.price_date.desc())
        .limit(days + 10)
        .all()
    )

    if len(prices) < 2:
        return None, None

    newest = prices[0]
    oldest = prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days

    if elapsed < MIN_DAYS_REQUIRED or not oldest.vwap or float(oldest.vwap) <= 0:
        return None, None

    # Determinar si es instrumento USD o ARS
    meta = db.get(InstrumentMetadata, ticker.upper())
    is_usd = meta.currency == "USD" if meta else (
        ticker.upper().endswith("D") or ticker.upper().startswith(("GD", "AL"))
    )

    if is_usd and newest.mep and oldest.mep and float(oldest.mep) > 0:
        usd_new = float(newest.vwap) / float(newest.mep)
        usd_old = float(oldest.vwap) / float(oldest.mep)
    else:
        usd_new = float(newest.vwap)
        usd_old = float(oldest.vwap)

    raw = (usd_new / usd_old - 1) * (365 / elapsed)

    # Bonos soberanos: -30% a +50% anual es razonable
    if -0.3 <= raw <= 0.5:
        logger.info(
            "yield_v2 bond %s: %.2f%% USD (%dd precio)",
            ticker, raw * 100, elapsed,
        )
        return Decimal(str(round(raw, 4))), "USD"

    logger.warning("yield_v2 bond %s: raw=%.2f%% fuera de rango", ticker, raw * 100)
    return None, None


def compute_fci_yield(
    ticker_fci: str,
    db,
    days: int = DEFAULT_WINDOW_DAYS,
) -> tuple[Decimal, str] | tuple[None, None]:
    """
    TNA real de un FCI desde el historial de VCP almacenado en instrument_prices.
    ticker_fci = "FCI:{nombre[:18]}" — mismo formato que usa price_collector.

    Retorna (tna_decimal, 'ARS') o (None, None) si faltan datos.
    """
    from app.models import InstrumentPrice

    prices = (
        db.query(InstrumentPrice)
        .filter(InstrumentPrice.ticker == ticker_fci)
        .order_by(InstrumentPrice.price_date.desc())
        .limit(days + 10)
        .all()
    )

    if len(prices) < 2:
        return None, None

    newest = prices[0]
    oldest = prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days

    if elapsed < 3 or not oldest.vwap or float(oldest.vwap) <= 0:
        return None, None

    tna = (float(newest.vwap) / float(oldest.vwap) - 1) * (365 / elapsed)

    if 0 < tna < 5.0:
        logger.info(
            "yield_v2 fci %s: TNA=%.2f%% (%dd VCP)",
            ticker_fci, tna * 100, elapsed,
        )
        return Decimal(str(round(tna, 4))), "ARS"

    logger.warning("yield_v2 fci %s: TNA=%.2f%% fuera de rango", ticker_fci, tna * 100)
    return None, None


def resolve_fci_ticker(pos) -> str:
    """
    Mapea una posición FCI al ticker usado en instrument_prices.
    Usa fondo_name de InstrumentMetadata si existe, si no usa external_id o ticker.
    """
    # El price_collector guarda FCI con ticker = "FCI:{nombre[:18]}"
    # Intentar matching por external_id o nombre conocido
    name = getattr(pos, "external_id", None) or pos.ticker
    return f"FCI:{name[:18]}"
