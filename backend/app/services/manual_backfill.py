"""
Retropolado de historial para posiciones manuales.

Cuando el usuario declara una fecha de compra al cargar una posición manual,
generamos PositionSnapshots desde esa fecha hasta ayer (hoy ya lo cubre el flujo
de snapshot normal tras crear la posición):

- CASH / REAL_ESTATE / OTRO: valor plano — no tienen precio de mercado histórico
  relevante (el cash no varía, la valuación del inmueble es la estimación del usuario).
- CRYPTO: valor = quantity × precio_del_día (CoinGecko); si no hay historia se cae
  al valor plano actual.

El backfill es idempotente: nunca pisa un snapshot existente para (user, ticker, día).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import PositionSnapshot
from app.services import crypto_prices
from app.services.historical_prices import lookup_price

logger = logging.getLogger("buildfuture.manual_backfill")

# Cota de retropolado: el tier público de CoinGecko da granularidad diaria hasta
# ~365 días, y limita el costo de generar snapshots.
MAX_BACKFILL_DAYS = 366


def _daterange(start: date, end: date):
    """Itera días desde start hasta end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def build_manual_value_series(
    position,
    purchase_date: date,
    today: date,
    crypto_history: dict[date, float] | None = None,
) -> dict[date, Decimal]:
    """Calcula el valor USD por día en [purchase_date, ayer].

    Función pura — no toca la DB. ``crypto_history`` es ``{date: price_usd}`` y solo
    se usa para CRYPTO; si está vacío se cae al valor plano actual.
    """
    end = today - timedelta(days=1)
    if purchase_date > end:
        return {}

    quantity = Decimal(str(position.quantity))
    series: dict[date, Decimal] = {}

    if position.asset_type == "CRYPTO" and crypto_history:
        for d in _daterange(purchase_date, end):
            price = lookup_price(crypto_history, d)
            if price is None:
                continue
            series[d] = quantity * Decimal(str(price))
    else:
        flat_value = Decimal(str(position.current_value_usd))
        for d in _daterange(purchase_date, end):
            series[d] = flat_value
    return series


def backfill_manual_history(db: Session, position, purchase_date: date) -> int:
    """Crea PositionSnapshots retroactivos para una posición manual.

    Devuelve cuántos snapshots creó. Idempotente y tolerante a fallos de red
    (cae al valor plano). No lanza — loguea y devuelve 0 ante error inesperado.
    """
    today = date.today()
    if not purchase_date or purchase_date >= today:
        return 0

    earliest = today - timedelta(days=MAX_BACKFILL_DAYS)
    if purchase_date < earliest:
        purchase_date = earliest

    crypto_history: dict[date, float] | None = None
    if position.asset_type == "CRYPTO" and position.external_id:
        days = (today - purchase_date).days + 1
        crypto_history = crypto_prices.get_price_history(position.external_id, days)

    series = build_manual_value_series(position, purchase_date, today, crypto_history)
    if not series:
        return 0

    try:
        existing = {
            row.snapshot_date
            for row in db.query(PositionSnapshot.snapshot_date).filter(
                PositionSnapshot.user_id == position.user_id,
                PositionSnapshot.ticker == position.ticker,
            )
        }
        quantity = Decimal(str(position.quantity))
        fallback_price = Decimal(str(position.current_price_usd))
        created = 0
        for d, value in series.items():
            if d in existing:
                continue
            price_usd = (value / quantity) if quantity else fallback_price
            db.add(
                PositionSnapshot(
                    user_id=position.user_id,
                    ticker=position.ticker,
                    snapshot_date=d,
                    value_usd=value,
                    price_usd=price_usd,
                    quantity=quantity,
                    asset_type=position.asset_type,
                    source=position.source or "MANUAL",
                    value_ars=None,
                    mep=None,
                )
            )
            created += 1
        db.commit()
        logger.info(
            "Backfill manual %s (user %s): %d snapshots desde %s",
            position.ticker,
            position.user_id,
            created,
            purchase_date,
        )
        return created
    except Exception as e:
        db.rollback()
        logger.warning("Backfill manual falló (%s): %s", position.ticker, e)
        return 0
