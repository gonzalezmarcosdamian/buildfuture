"""
Reconstrucción histórica de portfolio desde operaciones IOL.
Usa price_history y mep_history como caché compartido entre usuarios.

Flujo:
1. Traer operaciones IOL (hasta 2 años atrás)
2. Construir timeline de holdings: {ticker: [(date, qty_acumulada)]}
3. Precios desde caché DB (Yahoo solo para lo que falta)
4. MEP desde caché DB (bluelytics solo para meses faltantes)
5. Crear PortfolioSnapshot para cada día lunes-viernes faltante
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Position, PortfolioSnapshot
from app.services.historical_prices import (
    get_prices_batch_cached,
    get_mep_cached,
    lookup_price,
    letra_price_usd_at,
    bond_price_usd_at,
    HISTORY_DAYS,
)

logger = logging.getLogger("buildfuture.reconstructor")

_CRYPTO_YAHOO_MAP: dict[str, str | None] = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "BNB": "BNB-USD",
    "SOL": "SOL-USD", "ADA": "ADA-USD", "XRP": "XRP-USD",
    "USDT": None, "USDC": None,   # stablecoins — precio fijo $1
}


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
        qty = float(op.get("cantidad") or 0)
        tipo = str(op.get("tipo", "")).lower()
        if not ticker or qty <= 0:
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
            continue  # cauciones, opciones, etc.

        tl = timeline[ticker]
        if tl and tl[-1][0] == op_date:
            tl[-1] = (op_date, current[ticker])  # mismo día: actualizar
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


def _yahoo_ticker_for(iol_ticker: str, asset_type: str) -> str | None:
    if asset_type == "CRYPTO":
        return _CRYPTO_YAHOO_MAP.get(iol_ticker)   # puede ser None
    if asset_type in ("CEDEAR", "ETF"):
        return iol_ticker
    return None  # LETRA, BOND, ON, FCI, CASH — sin Yahoo


def reconstruct_portfolio_history(
    client,
    db: Session,
    user_id: str,
    current_positions: list,
) -> int:
    """
    Crea PortfolioSnapshots históricos desde operaciones IOL.
    Los precios y MEP se leen desde caché DB (price_history / mep_history);
    solo se llama a APIs externas para lo que realmente falta.
    Idempotente: solo crea fechas que no existen en portfolio_snapshots.
    Retorna cantidad de snapshots creados.
    """
    if not current_positions:
        return 0

    # ── 1. Operaciones IOL ────────────────────────────────────────────────────
    fecha_desde = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    try:
        raw_ops = client.get_operations(fecha_desde=fecha_desde)
    except Exception as e:
        logger.warning("Reconstructor: operaciones fallaron: %s", e)
        return 0

    if not raw_ops:
        return 0

    parsed = _parse_operations(raw_ops)
    if not parsed:
        return 0

    first_date = parsed[0][0]
    today = date.today()
    logger.info("Reconstructor: %d ops desde %s", len(parsed), first_date)

    # ── 2. Timeline de holdings ───────────────────────────────────────────────
    holdings_tl = _build_holdings_timeline(parsed)

    # Info por ticker desde posiciones actuales
    pos_info: dict[str, dict] = {
        p.ticker.upper(): {
            "asset_type":    p.asset_type.upper(),
            "ppc_ars":       float(p.ppc_ars or 0),
            "ppc_usd":       float(p.avg_purchase_price_usd or 0),
            "current_usd":   float(p.current_price_usd or 0),
            "annual_yield":  float(p.annual_yield_pct or 0),
            "purchase_date": p.snapshot_date or today,
        }
        for p in current_positions
    }

    # ── 3. Precios históricos desde caché DB (Yahoo para CEDEAR/CRYPTO) ───────
    yahoo_map: dict[str, str] = {}
    for ticker in holdings_tl:
        info = pos_info.get(ticker)
        if not info:
            continue
        yt = _yahoo_ticker_for(ticker, info["asset_type"])
        if yt:
            yahoo_map[ticker] = yt

    # get_prices_batch_cached: lee DB primero, llama Yahoo solo para lo que falta
    yahoo_prices: dict[str, dict[date, float]] = {}
    if yahoo_map:
        # Descargamos con el ticker de Yahoo, luego re-mapeamos al ticker de IOL
        unique_yahoo = list(set(yahoo_map.values()))
        logger.info("Reconstructor: %d tickers Yahoo (algunos desde caché DB)", len(unique_yahoo))
        raw = get_prices_batch_cached(db, unique_yahoo, first_date, today)
        for iol_t, yah_t in yahoo_map.items():
            yahoo_prices[iol_t] = raw.get(yah_t, {})

    # ── 4. MEP histórico desde caché DB (bluelytics para meses faltantes) ────
    current_mep = float(client._get_mep())
    logger.info("Reconstructor: cargando MEP histórico desde caché")
    mep_by_date = get_mep_cached(db, first_date, today, fallback_mep=current_mep)

    # ── 5. Determinar fechas faltantes ────────────────────────────────────────
    existing = _existing_snapshot_dates(db, user_id)
    dates_needed = [
        first_date + timedelta(days=i)
        for i in range((today - first_date).days)
        if (first_date + timedelta(days=i)).weekday() < 5       # lun-vie
        and (first_date + timedelta(days=i)) not in existing
    ]

    if not dates_needed:
        logger.info("Reconstructor: todos los snapshots ya existen para user=%s", user_id)
        return 0

    logger.info("Reconstructor: %d snapshots a generar para user=%s", len(dates_needed), user_id)

    # ── 6. Crear snapshots ────────────────────────────────────────────────────
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
                price = lookup_price(yahoo_prices.get(ticker, {}), target)
                if price is None:
                    price = info["current_usd"]   # fallback al precio actual
            elif at == "LETRA":
                price = letra_price_usd_at(
                    ppc_ars=info["ppc_ars"],
                    annual_yield=info["annual_yield"],
                    purchase_date=info["purchase_date"],
                    target_date=target,
                    mep=mep,
                )
            elif at in ("BOND", "ON"):
                price = bond_price_usd_at(
                    ppc_usd=info["ppc_usd"],
                    current_usd=info["current_usd"],
                    purchase_date=info["purchase_date"],
                    current_date=today,
                    target_date=target,
                )
            elif at == "FCI":
                price = info["current_usd"]   # FCI money market ≈ estable en USD

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
