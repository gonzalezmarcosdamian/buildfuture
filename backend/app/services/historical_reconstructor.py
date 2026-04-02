"""
Reconstrucción histórica de portfolio desde operaciones IOL.

Flujo:
1. Traer todas las operaciones (hasta 2 años atrás)
2. Construir timeline de holdings: {ticker: [(date, qty_acumulada)]}
3. Descargar precios históricos en batch (Yahoo para CEDEAR/CRYPTO)
4. Descargar MEP histórico en batch (bluelytics, mensual + interpolación)
5. Para cada día lunes-viernes desde la primera operación hasta hoy:
   - Skip si ya existe PortfolioSnapshot para ese día
   - Calcular qty por ticker en ese día
   - Valorizar en USD
   - Crear PortfolioSnapshot
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session
from app.models import Position, PortfolioSnapshot
from app.services.historical_prices import (
    fetch_yahoo_batch,
    fetch_bluelytics_range,
    lookup_price,
    letra_price_usd_at,
    bond_price_usd_at,
)

logger = logging.getLogger("buildfuture.reconstructor")

_CRYPTO_YAHOO_MAP = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "BNB": "BNB-USD",
    "SOL": "SOL-USD", "ADA": "ADA-USD", "XRP": "XRP-USD",
    "USDT": None, "USDC": None,
}

HISTORY_DAYS = 730


def _existing_snapshot_dates(db: Session, user_id: str) -> set[date]:
    rows = db.query(PortfolioSnapshot.snapshot_date).filter(
        PortfolioSnapshot.user_id == user_id
    ).all()
    return {r[0] for r in rows}


def _parse_operations(ops: list[dict]) -> list[tuple[date, str, float, str]]:
    parsed = []
    for op in ops:
        raw = op.get("fechaOrden") or op.get("fecha") or ""
        if not raw:
            continue
        try:
            op_date = date.fromisoformat(raw[:10])
        except ValueError:
            continue
        ticker = (op.get("simbolo") or op.get("ticker") or "").upper()
        if not ticker:
            continue
        qty = float(op.get("cantidad") or 0)
        tipo = str(op.get("tipo", "")).lower()
        if qty <= 0:
            continue
        parsed.append((op_date, ticker, qty, tipo))
    return sorted(parsed, key=lambda x: x[0])


def _build_holdings_timeline(parsed: list[tuple[date, str, float, str]]) -> dict[str, list[tuple[date, float]]]:
    current: dict[str, float] = defaultdict(float)
    timeline: dict[str, list[tuple[date, float]]] = defaultdict(list)

    for op_date, ticker, qty, tipo in parsed:
        if "compra" in tipo or "suscripcion" in tipo:
            current[ticker] += qty
        elif "venta" in tipo or "rescate" in tipo:
            current[ticker] = max(0.0, current[ticker] - qty)
        else:
            continue

        tl = timeline[ticker]
        if tl and tl[-1][0] == op_date:
            tl[-1] = (op_date, current[ticker])
        else:
            tl.append((op_date, current[ticker]))

    return dict(timeline)


def _qty_at(tl: list[tuple[date, float]], target: date) -> float:
    qty = 0.0
    for ev_date, ev_qty in tl:
        if ev_date <= target:
            qty = ev_qty
        else:
            break
    return qty


def _yahoo_ticker(iol_ticker: str, asset_type: str) -> str | None:
    if asset_type == "CRYPTO":
        return _CRYPTO_YAHOO_MAP.get(iol_ticker)
    if asset_type in ("CEDEAR", "ETF"):
        return iol_ticker
    return None


def reconstruct_portfolio_history(client, db: Session, user_id: str, current_positions: list) -> int:
    """
    Crea PortfolioSnapshots históricos desde operaciones IOL.
    Idempotente: solo llena fechas faltantes.
    Retorna cantidad de snapshots creados.
    """
    if not current_positions:
        return 0

    fecha_desde = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    try:
        raw_ops = client.get_operations(fecha_desde=fecha_desde)
    except Exception as e:
        logger.warning("Reconstructor: no se pudieron traer operaciones: %s", e)
        return 0

    if not raw_ops:
        return 0

    parsed = _parse_operations(raw_ops)
    if not parsed:
        return 0

    first_date = parsed[0][0]
    today = date.today()
    logger.info("Reconstructor: %d ops desde %s → reconstruyendo historial", len(parsed), first_date)

    holdings_tl = _build_holdings_timeline(parsed)

    # Info de cada ticker desde posiciones actuales
    pos_info: dict[str, dict] = {}
    for p in current_positions:
        pos_info[p.ticker.upper()] = {
            "asset_type":    p.asset_type.upper(),
            "ppc_ars":       float(p.ppc_ars or 0),
            "ppc_usd":       float(p.avg_purchase_price_usd or 0),
            "current_usd":   float(p.current_price_usd or 0),
            "annual_yield":  float(p.annual_yield_pct or 0),
            "purchase_date": p.snapshot_date or today,
        }

    # Tickers que necesitan Yahoo
    yahoo_map: dict[str, str] = {}
    for ticker in holdings_tl:
        info = pos_info.get(ticker)
        if not info:
            continue
        yt = _yahoo_ticker(ticker, info["asset_type"])
        if yt:
            yahoo_map[ticker] = yt

    logger.info("Reconstructor: descargando Yahoo para %d tickers", len(yahoo_map))
    raw_yahoo = fetch_yahoo_batch(list(yahoo_map.values())) if yahoo_map else {}
    # Re-mapear yahoo_ticker → iol_ticker
    yahoo_prices: dict[str, dict[date, float]] = {
        iol_t: raw_yahoo.get(yah_t, {})
        for iol_t, yah_t in yahoo_map.items()
    }

    logger.info("Reconstructor: descargando MEP histórico")
    current_mep = float(client._get_mep())
    mep_by_date = fetch_bluelytics_range(first_date, today, fallback_mep=current_mep)

    existing = _existing_snapshot_dates(db, user_id)
    dates_needed = [
        first_date + timedelta(days=i)
        for i in range((today - first_date).days)
        if (first_date + timedelta(days=i)).weekday() < 5       # lun-vie
        and (first_date + timedelta(days=i)) not in existing
    ]

    if not dates_needed:
        logger.info("Reconstructor: todos los snapshots ya existen")
        return 0

    logger.info("Reconstructor: %d fechas a generar", len(dates_needed))
    batch: list[PortfolioSnapshot] = []
    created = 0

    for target in dates_needed:
        mep = mep_by_date.get(target, current_mep)
        total_usd = 0.0
        n_pos = 0

        for ticker, tl in holdings_tl.items():
            qty = _qty_at(tl, target)
            if qty <= 0:
                continue
            info = pos_info.get(ticker)
            if not info:
                continue

            at = info["asset_type"]
            price: float | None = None

            if at in ("CEDEAR", "ETF", "CRYPTO"):
                price = lookup_price(yahoo_prices.get(ticker, {}), target) or info["current_usd"]
            elif at == "LETRA":
                price = letra_price_usd_at(
                    ppc_ars=info["ppc_ars"], annual_yield=info["annual_yield"],
                    purchase_date=info["purchase_date"], target_date=target, mep=mep,
                )
            elif at in ("BOND", "ON"):
                price = bond_price_usd_at(
                    ppc_usd=info["ppc_usd"], current_usd=info["current_usd"],
                    purchase_date=info["purchase_date"], current_date=today, target_date=target,
                )
            elif at == "FCI":
                price = info["current_usd"]

            if price and price > 0:
                total_usd += qty * price
                n_pos += 1

        if total_usd <= 0:
            continue

        batch.append(PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=target,
            total_usd=Decimal(str(round(total_usd, 2))),
            monthly_return_usd=Decimal(str(round(total_usd * 0.008, 2))),
            positions_count=n_pos,
            fx_mep=Decimal(str(round(mep, 2))),
            cost_basis_usd=Decimal("0"),
        ))
        created += 1

        if len(batch) >= 100:
            db.add_all(batch)
            db.flush()
            batch = []

    if batch:
        db.add_all(batch)
        db.flush()

    logger.info("Reconstructor: %d snapshots creados para user=%s", created, user_id)
    return created
