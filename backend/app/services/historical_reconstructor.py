"""
Reconstruccion historica de portfolio desde operaciones IOL - v2.

Algoritmo backwards-anchored:
1. Traer operaciones IOL (hasta 2 anos), usar cantidadOperada (unidades reales).
2. Reconstruir el timeline yendo hacia ATRAS desde las posiciones actuales.
   Si deshacer una compra deja el estado negativo hay ventas invisibles fuera
   de la ventana. Se descarta esa historia y solo se conserva la parte confiable.
3. Calcular precios historicos por tipo:
   - CEDEAR/ETF/CRYPTO : Yahoo Finance (cache DB)
   - LETRA             : capitalizacion diaria desde ppc_ars/100 (por VN)
   - FCI               : ppc_ars / MEP historico (por cuotaparte)
   - BOND/ON           : interpolacion lineal ppc a current
4. Crear PortfolioSnapshot para cada dia lunes-viernes faltante.

Resultado: snapshots que reflejan solo la historia verificable, sin inflacion
por operaciones fuera de la ventana o por importes ARS interpretados como unidades.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import PortfolioSnapshot
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
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "BNB": "BNB-USD",
    "SOL": "SOL-USD",
    "ADA": "ADA-USD",
    "XRP": "XRP-USD",
    "USDT": None,
    "USDC": None,
}

_YAHOO_TYPES = {"CEDEAR", "ETF", "CRYPTO"}


def _existing_snapshot_dates(db: Session, user_id: str) -> set[date]:
    rows = (
        db.query(PortfolioSnapshot.snapshot_date)
        .filter(PortfolioSnapshot.user_id == user_id)
        .all()
    )
    return {r[0] for r in rows}


def _yahoo_ticker_for(iol_ticker: str, asset_type: str) -> str | None:
    if asset_type == "CRYPTO":
        return _CRYPTO_YAHOO_MAP.get(iol_ticker)
    if asset_type in ("CEDEAR", "ETF"):
        return iol_ticker
    return None


def _parse_operations_v2(ops: list[dict]) -> list[dict]:
    """
    Parsea operaciones IOL usando cantidadOperada (unidades reales del fill).
    Solo incluye operaciones terminadas con cantidadOperada > 0.

    cantidadOperada es el campo clave: da acciones reales para CEDEAR (no ARS),
    VN nominal para LECAP, cuotapartes para FCI, independientemente del tipo
    de orden (por monto o por cantidad).
    """
    parsed = []
    for op in ops:
        estado = str(op.get("estado") or "").lower()
        if "terminada" not in estado:
            continue

        raw_date = op.get("fechaOrden") or op.get("fecha") or ""
        if not raw_date:
            continue
        try:
            op_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue

        ticker = (op.get("simbolo") or op.get("ticker") or "").upper().strip()
        if not ticker:
            continue

        tipo = str(op.get("tipo") or "").lower()

        qty_op = op.get("cantidadOperada")
        if qty_op is None or float(qty_op) <= 0:
            continue

        parsed.append(
            {
                "date": op_date,
                "ticker": ticker,
                "qty": float(qty_op),
                "tipo": tipo,
                "precio_op": float(op.get("precioOperado") or 0),
                "monto_op": float(op.get("montoOperado") or 0),
            }
        )

    return sorted(parsed, key=lambda x: x["date"])


def _build_reliable_timeline(
    parsed_ops: list[dict],
    current_pos: dict[str, float],
) -> dict[str, list[tuple[date, float]]]:
    """
    Construye un timeline confiable yendo hacia ATRAS desde las posiciones actuales.

    Para cada operacion (de mas reciente a mas antigua):
    - compra/suscripcion: deshacer restando qty del estado.
      Si el resultado seria negativo hay ventas invisibles fuera de la ventana:
      se deja de procesar ops mas antiguas para ese ticker pero se conservan
      los eventos ya registrados (historia reciente verificable).
    - venta/rescate: deshacer sumando qty al estado.

    El evento registrado en cada fecha es la cantidad POST-operacion (EOD),
    que es lo que el usuario tenia al cierre de ese dia.

    Solo se preservan tickers activos en current_pos (los que el usuario tiene hoy).
    Tickers ya vendidos no tienen historia relevante para el grafico.

    Nota sobre acentos: IOL devuelve tipo="suscripcion" o "suscripcion fci" (puede
    incluir la o acentuada). Se usa "suscripci" para capturar ambas variantes.
    """
    state: dict[str, float] = dict(current_pos)
    stop_older: set[str] = set()  # dejar de procesar ops mas antiguas para este ticker
    events_rev: dict[str, list[tuple[date, float]]] = defaultdict(list)

    for op in reversed(parsed_ops):
        ticker = op["ticker"]
        qty = op["qty"]
        tipo = op["tipo"]

        if ticker not in current_pos:
            continue
        if ticker in stop_older:
            continue

        current_qty = state.get(ticker, 0.0)

        if "compra" in tipo or "suscripci" in tipo:
            new_qty = current_qty - qty
            if new_qty < -0.5:
                stop_older.add(ticker)
                logger.info(
                    "Reconstructor: %s ventas invisibles fuera de ventana "
                    "(state=%.4f, op_qty=%.4f) — historia anterior a esta op descartada",
                    ticker,
                    current_qty,
                    qty,
                )
                continue
            state[ticker] = max(0.0, new_qty)
            # Evento: qty POST-compra en esa fecha (current_qty antes de restar)
            events_rev[ticker].append((op["date"], current_qty))

        elif "venta" in tipo or "rescate" in tipo:
            state[ticker] = current_qty + qty
            # Evento: qty POST-venta en esa fecha (current_qty antes de sumar)
            events_rev[ticker].append((op["date"], current_qty))

        else:
            continue

    today = date.today()
    result: dict[str, list[tuple[date, float]]] = {}
    for ticker in current_pos:
        ev = sorted(events_rev.get(ticker, []), key=lambda x: x[0])
        if not ev:
            continue
        if ev[-1][0] != today:
            ev.append((today, current_pos[ticker]))
        result[ticker] = ev

    return result


def _qty_at(tl: list[tuple[date, float]], target: date) -> float:
    qty = 0.0
    for ev_date, ev_qty in tl:
        if ev_date <= target:
            qty = ev_qty
        else:
            break
    return qty


def reconstruct_portfolio_history(
    client,
    db: Session,
    user_id: str,
    current_positions: list,
) -> int:
    """
    Crea PortfolioSnapshots historicos desde operaciones IOL.
    Usa el algoritmo backwards-anchored para garantizar consistencia con el
    estado actual del portfolio. Idempotente.
    Retorna cantidad de snapshots creados.
    """
    if not current_positions:
        return 0

    fecha_desde = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    try:
        raw_ops = client.get_operations(fecha_desde=fecha_desde)
    except Exception as e:
        logger.warning("Reconstructor: operaciones fallaron: %s", e)
        return 0

    if not raw_ops:
        return 0

    parsed = _parse_operations_v2(raw_ops)
    if not parsed:
        return 0

    logger.info("Reconstructor: %d ops terminadas con cantidadOperada", len(parsed))

    today = date.today()
    pos_info: dict[str, dict] = {
        p.ticker.upper(): {
            "asset_type": p.asset_type.upper(),
            "ppc_ars": float(p.ppc_ars or 0),
            "ppc_usd": float(p.avg_purchase_price_usd or 0),
            "current_usd": float(p.current_price_usd or 0),
            "annual_yield": float(p.annual_yield_pct or 0),
            "purchase_date": p.snapshot_date or today,
        }
        for p in current_positions
    }

    current_qty_map: dict[str, float] = {
        p.ticker.upper(): float(p.quantity)
        for p in current_positions
        if float(p.quantity) > 0
    }

    holdings_tl = _build_reliable_timeline(parsed, current_qty_map)

    if not holdings_tl:
        logger.info("Reconstructor: sin timeline confiable para user=%s", user_id)
        return 0

    first_date = min(tl[0][0] for tl in holdings_tl.values())
    logger.info(
        "Reconstructor: timeline confiable para %d tickers desde %s",
        len(holdings_tl),
        first_date,
    )

    yahoo_map: dict[str, str] = {}
    for ticker in holdings_tl:
        info = pos_info.get(ticker)
        if not info:
            continue
        yt = _yahoo_ticker_for(ticker, info["asset_type"])
        if yt:
            yahoo_map[ticker] = yt

    yahoo_prices: dict[str, dict[date, float]] = {}
    if yahoo_map:
        unique_yahoo = list(set(yahoo_map.values()))
        logger.info(
            "Reconstructor: %d tickers Yahoo (cache DB first)", len(unique_yahoo)
        )
        raw_yahoo = get_prices_batch_cached(db, unique_yahoo, first_date, today)
        for iol_t, yah_t in yahoo_map.items():
            yahoo_prices[iol_t] = raw_yahoo.get(yah_t, {})

    current_mep = float(client._get_mep())
    mep_by_date = get_mep_cached(db, first_date, today, fallback_mep=current_mep)

    existing = _existing_snapshot_dates(db, user_id)
    dates_needed = [
        first_date + timedelta(days=i)
        for i in range((today - first_date).days)
        if (first_date + timedelta(days=i)).weekday() < 5
        and (first_date + timedelta(days=i)) not in existing
    ]

    if not dates_needed:
        logger.info(
            "Reconstructor: todos los snapshots ya existen para user=%s", user_id
        )
        return 0

    logger.info(
        "Reconstructor: %d snapshots a generar para user=%s", len(dates_needed), user_id
    )

    batch: list[PortfolioSnapshot] = []
    created = 0

    _RENTA_TYPES = {"LETRA", "FCI"}
    _AMBOS_TYPES = {"BOND", "ON"}

    for target in dates_needed:
        mep = mep_by_date.get(target, current_mep)
        total_usd = 0.0
        renta_monthly_usd = 0.0
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

            if at in _YAHOO_TYPES:
                price = lookup_price(yahoo_prices.get(ticker, {}), target)

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
                if mep > 0 and info["ppc_ars"] > 0:
                    price = info["ppc_ars"] / mep

            if price and price > 0:
                value_usd = qty * price
                total_usd += value_usd
                n_pos += 1
                # Renta mensual solo desde activos de renta real
                annual_yield = info["annual_yield"]
                if at in _RENTA_TYPES:
                    renta_monthly_usd += value_usd * annual_yield / 12
                elif at in _AMBOS_TYPES:
                    renta_monthly_usd += value_usd * annual_yield / 12 * 0.5

        if total_usd <= 0:
            continue

        batch.append(
            PortfolioSnapshot(
                user_id=user_id,
                snapshot_date=target,
                total_usd=Decimal(str(round(total_usd, 2))),
                monthly_return_usd=Decimal(str(round(renta_monthly_usd, 2))),
                positions_count=n_pos,
                fx_mep=Decimal(str(round(mep, 2))),
                cost_basis_usd=Decimal("0"),
            )
        )
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
