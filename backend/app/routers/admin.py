"""
Endpoints de administración interna — sólo para soporte/equipo BuildFuture.
Protegidos con X-Admin-Key (env ADMIN_SECRET_KEY).
NO exponer a clientes ni documentar en el API público.
"""

import logging
import os
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from sqlalchemy import func
from app.database import SessionLocal
from app.models import PortfolioSnapshot, PriceHistory, MepHistory, Position

logger = logging.getLogger("buildfuture.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_KEY = os.environ.get("ADMIN_SECRET_KEY", "")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if not ADMIN_KEY:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints no configurados (ADMIN_SECRET_KEY ausente)",
        )
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Clave de administrador incorrecta")


# ── Snapshots ────────────────────────────────────────────────────────────────


@router.get("/snapshots/info")
def snapshots_info(
    user_id: Optional[str] = Query(None, description="Filtrar por usuario"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Info sobre snapshots almacenados.
    Sin user_id → resumen global. Con user_id → detalle del usuario.
    """
    q = db.query(PortfolioSnapshot)
    if user_id:
        q = q.filter(PortfolioSnapshot.user_id == user_id)
    rows = q.all()

    if not rows:
        return {"count": 0, "user_id": user_id}

    dates = sorted(r.snapshot_date for r in rows)
    by_user: dict = {}
    for r in rows:
        uid = r.user_id
        if uid not in by_user:
            by_user[uid] = {
                "count": 0,
                "oldest": r.snapshot_date,
                "newest": r.snapshot_date,
            }
        by_user[uid]["count"] += 1
        if r.snapshot_date < by_user[uid]["oldest"]:
            by_user[uid]["oldest"] = r.snapshot_date
        if r.snapshot_date > by_user[uid]["newest"]:
            by_user[uid]["newest"] = r.snapshot_date

    return {
        "total_count": len(rows),
        "global_oldest": dates[0].isoformat(),
        "global_newest": dates[-1].isoformat(),
        "by_user": {
            uid: {
                "count": v["count"],
                "oldest": v["oldest"].isoformat(),
                "newest": v["newest"].isoformat(),
            }
            for uid, v in by_user.items()
        },
    }


@router.delete("/snapshots/purge")
def snapshots_purge(
    user_id: Optional[str] = Query(
        None, description="Si se omite, purga TODOS los usuarios"
    ),
    before_date: Optional[date] = Query(
        None,
        description="Borrar snapshots anteriores a esta fecha (YYYY-MM-DD). Por defecto: hoy",
    ),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Elimina snapshots históricos para que el reconstructor los regenere correctamente.
    Útil tras correcciones en la lógica de precios (ej: fix del fallback current_usd).

    - user_id omitido → afecta TODOS los usuarios (cuidado)
    - before_date omitido → borra todo excepto hoy
    """
    cutoff = before_date or date.today()
    q = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.snapshot_date < cutoff)
    if user_id:
        q = q.filter(PortfolioSnapshot.user_id == user_id)

    deleted = q.delete(synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("snapshots_purge commit error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "admin/snapshots/purge: %d rows deleted (user=%s, before=%s)",
        deleted,
        user_id,
        cutoff,
    )
    return {
        "deleted": deleted,
        "user_id": user_id or "ALL",
        "before_date": cutoff.isoformat(),
        "message": "Snapshots eliminados. El próximo sync los regenerará automáticamente.",
    }


@router.get("/reconstruct/raw-ops")
def reconstruct_raw_ops(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Devuelve las operaciones IOL crudas para inspeccionar campos precio, titulo, tipo instrumento."""
    from app.models import Integration
    from app.services.iol_client import IOLClient
    from app.services.historical_prices import HISTORY_DAYS
    from datetime import timedelta

    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.provider == "IOL",
            Integration.is_connected == True,  # noqa: E712
        )
        .first()
    )
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(status_code=404, detail="IOL no conectado")

    creds = integration.encrypted_credentials.split(":", 1)
    client = IOLClient(creds[0], creds[1])
    fecha_desde = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    raw_ops = client.get_operations(fecha_desde=fecha_desde)

    # Normalizar para exponer todos los campos relevantes
    result = []
    for op in raw_ops:
        titulo = op.get("titulo") or {}
        result.append(
            {
                "fechaOrden": op.get("fechaOrden") or op.get("fecha"),
                "simbolo": op.get("simbolo") or op.get("ticker"),
                "tipo": op.get("tipo"),
                "estado": op.get("estado"),
                # Orden
                "cantidad": op.get("cantidad"),
                "precio": op.get("precio"),
                "monto": op.get("monto"),
                # Fill real (lo que se ejecutó)
                "cantidadOperada": op.get("cantidadOperada"),
                "precioOperado": op.get("precioOperado"),
                "montoOperado": op.get("montoOperado"),
                # Instrumento
                "inst_tipo": titulo.get("tipo"),
                "inst_mercado": titulo.get("mercado"),
                "_raw_keys": list(op.keys()),
            }
        )
    return {"total": len(result), "ops": result}


@router.get("/reconstruct/dry-run")
def reconstruct_dry_run(
    user_id: str = Query(...),
    target_date: date = Query(..., description="Fecha a simular (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Simula la reconstrucción para una fecha dada sin escribir nada en DB.
    Muestra operaciones parseadas, timeline de quantities y precios calculados por ticker.
    """
    from app.models import Integration, Position
    from app.services.iol_client import IOLClient
    from app.services.historical_reconstructor import (
        _parse_operations_v2,
        _build_reliable_timeline,
        _qty_at,
        _yahoo_ticker_for,
    )
    from app.services.historical_prices import (
        get_prices_batch_cached,
        get_mep_cached,
        lookup_price,
        letra_price_usd_at,
        bond_price_usd_at,
        HISTORY_DAYS,
    )
    from datetime import timedelta

    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.provider == "IOL",
            Integration.is_connected == True,  # noqa: E712
        )
        .first()
    )
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(
            status_code=404, detail="IOL no conectado para este usuario"
        )

    creds = integration.encrypted_credentials.split(":", 1)
    client = IOLClient(creds[0], creds[1])
    current_mep = float(client._get_mep())

    fecha_desde = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    raw_ops = client.get_operations(fecha_desde=fecha_desde)

    parsed = _parse_operations_v2(raw_ops)

    current_positions = (
        db.query(Position)
        .filter(
            Position.is_active == True,  # noqa: E712
            Position.user_id == user_id,
            Position.source == "IOL",
        )
        .all()
    )

    current_qty_map = {
        p.ticker.upper(): float(p.quantity)
        for p in current_positions
        if float(p.quantity) > 0
    }

    holdings_tl = _build_reliable_timeline(parsed, current_qty_map)

    pos_info = {
        p.ticker.upper(): {
            "asset_type": p.asset_type.upper(),
            "ppc_ars": float(p.ppc_ars or 0),
            "ppc_usd": float(p.avg_purchase_price_usd or 0),
            "current_usd": float(p.current_price_usd or 0),
            "annual_yield": float(p.annual_yield_pct or 0),
            "purchase_date": p.snapshot_date or date.today(),
        }
        for p in current_positions
    }

    yahoo_map = {}
    for ticker in holdings_tl:
        info = pos_info.get(ticker)
        if not info:
            continue
        yt = _yahoo_ticker_for(ticker, info["asset_type"])
        if yt:
            yahoo_map[ticker] = yt

    yahoo_prices = {}
    if yahoo_map:
        unique_yahoo = list(set(yahoo_map.values()))
        raw = get_prices_batch_cached(db, unique_yahoo, target_date, target_date)
        for iol_t, yah_t in yahoo_map.items():
            yahoo_prices[iol_t] = raw.get(yah_t, {})

    mep_by_date = get_mep_cached(db, target_date, target_date, fallback_mep=current_mep)
    mep = mep_by_date.get(target_date, current_mep)

    breakdown = []
    total_usd = 0.0
    for ticker, tl in holdings_tl.items():
        qty = _qty_at(tl, target_date)
        info = pos_info.get(ticker)
        at = info["asset_type"] if info else "UNKNOWN"
        price = None
        price_method = "no_info"

        if info:
            if at in ("CEDEAR", "ETF", "CRYPTO"):
                price = lookup_price(yahoo_prices.get(ticker, {}), target_date)
                price_method = "yahoo"
            elif at == "LETRA":
                price = letra_price_usd_at(
                    info["ppc_ars"],
                    info["annual_yield"],
                    info["purchase_date"],
                    target_date,
                    mep,
                )
                price_method = "letra_capitalize"
            elif at in ("BOND", "ON"):
                price = bond_price_usd_at(
                    info["ppc_usd"],
                    info["current_usd"],
                    info["purchase_date"],
                    date.today(),
                    target_date,
                )
                price_method = "bond_interpolate"
            elif at == "FCI":
                if mep > 0 and info["ppc_ars"] > 0:
                    price = info["ppc_ars"] / mep
                price_method = "ppc_ars/mep"

        contrib = (qty * price) if (price and price > 0 and qty > 0) else 0.0
        total_usd += contrib
        breakdown.append(
            {
                "ticker": ticker,
                "asset_type": at,
                "qty_at_date": qty,
                "price_usd": round(price, 6) if price else None,
                "price_method": price_method,
                "contribution_usd": round(contrib, 2),
            }
        )

    return {
        "target_date": target_date.isoformat(),
        "mep": round(mep, 2),
        "total_usd_computed": round(total_usd, 2),
        "tickers_in_timeline": list(holdings_tl.keys()),
        "breakdown": sorted(breakdown, key=lambda x: -x["contribution_usd"]),
        "raw_ops_count": len(raw_ops),
        "parsed_ops": [
            {
                "date": str(op["date"]),
                "ticker": op["ticker"],
                "qty": op["qty"],
                "tipo": op["tipo"],
            }
            for op in parsed[:50]
        ],
    }


@router.delete("/snapshots/purge-user-all")
def snapshots_purge_all_for_user(
    user_id: str = Query(..., description="Usuario a limpiar completamente"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Elimina TODOS los snapshots de un usuario (reset completo de historial)."""
    deleted = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.user_id == user_id)
        .delete(synchronize_session=False)
    )
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "admin/snapshots/purge-user-all: %d rows deleted for user=%s", deleted, user_id
    )
    return {"deleted": deleted, "user_id": user_id}


@router.get("/snapshots/values")
def snapshots_values(
    user_id: str = Query(..., description="Usuario a inspeccionar"),
    limit: int = Query(30, description="Últimos N snapshots"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Muestra los valores reales de los últimos N snapshots de un usuario."""
    rows = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(limit)
        .all()
    )
    return {
        "user_id": user_id,
        "count": len(rows),
        "snapshots": [
            {
                "date": r.snapshot_date.isoformat(),
                "total_usd": float(r.total_usd),
                "positions_count": r.positions_count,
                "fx_mep": float(r.fx_mep),
            }
            for r in rows
        ],
    }


# ── Price / MEP cache ─────────────────────────────────────────────────────────


@router.get("/cache/price-info")
def price_cache_info(
    ticker: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Info sobre entradas de price_history. Útil para diagnosticar precios faltantes."""
    q = db.query(PriceHistory)
    if ticker:
        q = q.filter(PriceHistory.ticker == ticker.upper())
    rows = q.all()
    by_ticker: dict = {}
    for r in rows:
        t = r.ticker
        if t not in by_ticker:
            by_ticker[t] = {"count": 0, "oldest": r.price_date, "newest": r.price_date}
        by_ticker[t]["count"] += 1
        if r.price_date < by_ticker[t]["oldest"]:
            by_ticker[t]["oldest"] = r.price_date
        if r.price_date > by_ticker[t]["newest"]:
            by_ticker[t]["newest"] = r.price_date
    return {
        "total_rows": len(rows),
        "by_ticker": {
            t: {
                **v,
                "oldest": v["oldest"].isoformat(),
                "newest": v["newest"].isoformat(),
            }
            for t, v in by_ticker.items()
        },
    }


@router.delete("/cache/price-purge")
def price_cache_purge(
    ticker: Optional[str] = Query(
        None, description="Si se omite, purga TODA la caché de precios"
    ),
    before_date: Optional[date] = Query(
        None, description="Borrar entradas anteriores a esta fecha"
    ),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Limpia caché de precios Yahoo para forzar re-descarga."""
    q = db.query(PriceHistory)
    if ticker:
        q = q.filter(PriceHistory.ticker == ticker.upper())
    if before_date:
        q = q.filter(PriceHistory.price_date < before_date)
    deleted = q.delete(synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("admin/cache/price-purge: %d rows deleted (ticker=%s)", deleted, ticker)
    return {"deleted": deleted, "ticker": ticker or "ALL"}


@router.get("/positions/inspect")
def positions_inspect(
    user_id: str = Query(...),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Muestra las posiciones activas de un usuario con todos los campos relevantes para debug."""
    q = db.query(Position).filter(
        Position.user_id == user_id, Position.is_active.is_(True)
    )
    if source:
        q = q.filter(Position.source == source.upper())
    rows = q.all()
    return {
        "count": len(rows),
        "positions": [
            {
                "id": r.id,
                "ticker": r.ticker,
                "asset_type": r.asset_type,
                "source": r.source,
                "quantity": float(r.quantity),
                "ppc_ars": float(r.ppc_ars or 0),
                "avg_purchase_price_usd": float(r.avg_purchase_price_usd or 0),
                "current_price_usd": float(r.current_price_usd or 0),
                "current_value_ars": float(r.current_value_ars or 0),
                "annual_yield_pct": float(r.annual_yield_pct or 0),
                "implied_total_usd": round(
                    float(r.quantity) * float(r.current_price_usd or 0), 2
                ),
                "implied_ppc_total_usd": round(float(r.ppc_ars or 0) / 1436, 4),
            }
            for r in rows
        ],
    }


@router.get("/positions/dupes")
def positions_dupes(
    user_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Detecta posiciones activas duplicadas (mismo user+ticker+source con más de 1 fila activa)."""
    q = (
        db.query(
            Position.user_id,
            Position.ticker,
            Position.source,
            func.count(Position.id).label("cnt"),
        )
        .filter(Position.is_active == True)  # noqa: E712
        .group_by(Position.user_id, Position.ticker, Position.source)
        .having(func.count(Position.id) > 1)
    )
    if user_id:
        q = q.filter(Position.user_id == user_id)
    rows = q.all()
    return {
        "duplicates_found": len(rows),
        "items": [
            {
                "user_id": r.user_id,
                "ticker": r.ticker,
                "source": r.source,
                "count": r.cnt,
            }
            for r in rows
        ],
    }


@router.delete("/positions/dedup")
def positions_dedup(
    user_id: Optional[str] = Query(
        None, description="Si se omite, dedup para todos los usuarios"
    ),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Desactiva posiciones duplicadas activas — mantiene solo la más reciente (id más alto)
    por cada combinación user+ticker+source.
    """
    q = (
        db.query(
            Position.user_id,
            Position.ticker,
            Position.source,
            func.max(Position.id).label("keep_id"),
        )
        .filter(Position.is_active == True)  # noqa: E712
        .group_by(Position.user_id, Position.ticker, Position.source)
        .having(func.count(Position.id) > 1)
    )
    if user_id:
        q = q.filter(Position.user_id == user_id)
    dupes = q.all()

    total_deactivated = 0
    for row in dupes:
        n = (
            db.query(Position)
            .filter(
                Position.user_id == row.user_id,
                Position.ticker == row.ticker,
                Position.source == row.source,
                Position.is_active == True,  # noqa: E712
                Position.id != row.keep_id,
            )
            .update({"is_active": False})
        )
        total_deactivated += n

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info("admin/positions/dedup: %d posiciones desactivadas", total_deactivated)
    return {"deactivated": total_deactivated, "groups_affected": len(dupes)}


@router.get("/cache/mep-info")
def mep_cache_info(
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Info sobre entradas de mep_history."""
    rows = db.query(MepHistory).all()
    if not rows:
        return {"count": 0}
    dates = sorted(r.price_date for r in rows)
    return {
        "count": len(rows),
        "oldest": dates[0].isoformat(),
        "newest": dates[-1].isoformat(),
    }


@router.get("/yields/diagnose")
def yields_diagnose(
    user_id: Optional[str] = Query(None, description="Filtrar por usuario (opcional)"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Muestra el estado de cada posición LETRA/BOND/ON/FCI relevante para el yield_updater.
    Indica si sería skipped (current_value_ars=0, quantity=0, ticker no parseble) y por qué.
    """
    from app.services.yield_updater import _parse_lecap_maturity, _BOND_YTM
    from app.services.mep import get_mep

    today = date.today()
    mep = float(get_mep())

    q = db.query(Position).filter(
        Position.is_active.is_(True),
        Position.asset_type.in_(["LETRA", "BOND", "ON", "FCI"]),
    )
    if user_id:
        q = q.filter(Position.user_id == user_id)
    positions = q.all()

    rows = []
    for p in positions:
        skip_reason = None
        expected_yield = None

        if p.asset_type == "LETRA":
            ticker_upper = p.ticker.upper()
            # Letras CER (prefijo X): yield negativo real es correcto
            if ticker_upper.startswith("X"):
                expected_yield = float(p.annual_yield_pct)  # viene de _yield_letra_cer
            else:
                maturity = _parse_lecap_maturity(p.ticker)
                if maturity is None:
                    skip_reason = "ticker no parseble"
                elif (maturity - today).days <= 1:
                    skip_reason = "vencida"
                    expected_yield = 0.0
                elif p.quantity <= 0:
                    skip_reason = "quantity=0"
                elif p.current_value_ars is None or p.current_value_ars <= 0:
                    if p.current_price_usd > 0:
                        synthetic_ars = float(p.quantity) * float(p.current_price_usd) * mep
                        price_per_100 = (synthetic_ars / float(p.quantity)) * 100
                        days = (maturity - today).days
                        skip_reason = (
                            "current_value_ars=0 (reconstruible desde price_usd×mep)"
                        )
                        from decimal import Decimal as D
                        from app.services.yield_updater import _lecap_tir

                        expected_yield = float(
                            _lecap_tir(D(str(round(price_per_100, 4))), days)
                        )
                    else:
                        skip_reason = "current_value_ars=0 y current_price_usd=0"
                else:
                    # Happy path: LECAP válida con precio → calcula TNA esperada
                    days = (maturity - today).days
                    price_per_100 = (float(p.current_value_ars) / float(p.quantity)) * 100
                    from decimal import Decimal as D
                    from app.services.yield_updater import _lecap_tir

                    expected_yield = float(
                        _lecap_tir(D(str(round(price_per_100, 4))), days)
                    )

        elif p.asset_type in ("BOND", "ON"):
            ytm = _BOND_YTM.get(p.ticker.upper())
            if ytm is None:
                skip_reason = "ticker no en tabla _BOND_YTM"
            else:
                expected_yield = float(ytm)

        elif p.asset_type == "FCI":
            expected_yield = None  # se calcula en runtime desde ArgentinaDatos

        rows.append(
            {
                "user_id": p.user_id,
                "ticker": p.ticker,
                "asset_type": p.asset_type,
                "source": p.source,
                "quantity": float(p.quantity),
                "current_price_usd": float(p.current_price_usd),
                "current_value_ars": (
                    float(p.current_value_ars) if p.current_value_ars else 0
                ),
                "annual_yield_pct_now": float(p.annual_yield_pct),
                "expected_yield": expected_yield,
                "will_update": skip_reason is None and expected_yield is not None,
                "skip_reason": skip_reason,
            }
        )

    skipped = [r for r in rows if r["skip_reason"]]
    updatable = [r for r in rows if r["will_update"]]

    return {
        "mep": mep,
        "total": len(rows),
        "updatable": len(updatable),
        "skipped": len(skipped),
        "positions": sorted(
            rows, key=lambda r: (r["skip_reason"] is None, r["asset_type"], r["ticker"])
        ),
    }


@router.post("/yields/run")
def yields_run(
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Dispara yield_updater manualmente para todas las posiciones activas.
    Útil para verificar cambios sin esperar al cierre de mercado (17:30 ART)."""
    from app.services.yield_updater import update_yields
    from app.services.mep import get_mep

    mep = get_mep()
    updated = update_yields(db, mep=mep)
    return {"updated": updated, "mep_used": float(mep)}


@router.delete("/cache/mep-purge")
def mep_cache_purge(
    before_date: Optional[date] = Query(
        None, description="Borrar entradas de MEP anteriores a esta fecha"
    ),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Limpia caché MEP para forzar re-descarga desde bluelytics."""
    q = db.query(MepHistory)
    if before_date:
        q = q.filter(MepHistory.price_date < before_date)
    deleted = q.delete(synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("admin/cache/mep-purge: %d rows deleted", deleted)
    return {"deleted": deleted}


# ── Soporte de usuario (repair) ───────────────────────────────────────────────


@router.post("/support/repair-user")
def support_repair_user(
    user_id: str = Query(..., description="UUID del usuario a reparar"),
    purge_snapshots: bool = Query(True, description="Purgar snapshots históricos antes de reconstruir"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Reconstrucción completa del historial para un usuario.

    Flujo resiliente (todas las fuentes):
    1. Purga todos los PortfolioSnapshots del usuario.
    2. Re-sincroniza IOL → reconstruye histórico desde operaciones reales (hasta 730d).
    3. Si tiene Binance → suma historial de accountSnapshot (últimos 30d) a los snapshots IOL.
    4. Ejecuta backfill-non-iol → suma Cocos/Manual usando PositionSnapshot histórico real
       (usa MIN(PositionSnapshot.snapshot_date) como fecha de inicio, no Position.snapshot_date).
    5. Crea/actualiza snapshot de HOY con todas las posiciones activas.

    Resultado: historial coherente con todas las fuentes. Idempotente.
    """
    from app.models import Integration, PositionSnapshot
    from app.services.iol_client import IOLClient
    from app.routers.integrations import _sync_iol, _sync_binance_history
    from app.services.binance_client import BinanceClient
    from app.services.mep import get_mep

    result: dict = {
        "user_id": user_id,
        "snapshots_purged": 0,
        "iol_positions_synced": 0,
        "iol_snapshots_reconstructed": 0,
        "binance_snapshots_added": 0,
        "non_iol_snapshots_patched": 0,
        "today_snapshot": False,
        "errors": [],
    }

    # ── 1. Purgar snapshots ───────────────────────────────────────────────────
    if purge_snapshots:
        deleted = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.user_id == user_id)
            .delete(synchronize_session=False)
        )
        db.flush()
        result["snapshots_purged"] = deleted
        logger.info("repair-user: %d snapshots purgados para user=%s", deleted, user_id)

    # ── 2. IOL: reconstruye histórico completo ────────────────────────────────
    iol_integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.provider == "IOL",
            Integration.is_connected == True,  # noqa: E712
        )
        .first()
    )
    if iol_integration and iol_integration.encrypted_credentials:
        try:
            creds = iol_integration.encrypted_credentials.split(":", 1)
            iol_client = IOLClient(creds[0], creds[1])
            iol_result = _sync_iol(iol_client, db, user_id)
            db.commit()
            result["iol_positions_synced"] = iol_result.get("positions_synced", 0)
            result["iol_snapshots_reconstructed"] = iol_result.get("snapshots_reconstructed", 0)
        except Exception as e:
            db.rollback()
            logger.error("repair-user: IOL sync falló user=%s: %s", user_id, e)
            result["errors"].append(f"IOL: {e}")
    else:
        result["errors"].append("IOL no conectado — historial IOL no reconstruido")

    # ── 3. Binance: suma historial accountSnapshot (30d) ─────────────────────
    binance_integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.provider == "BINANCE",
            Integration.is_connected == True,  # noqa: E712
        )
        .first()
    )
    if binance_integration and binance_integration.encrypted_credentials:
        try:
            api_key, secret = binance_integration.encrypted_credentials.split(":", 1)
            bin_client = BinanceClient(api_key=api_key, secret=secret)
            added = _sync_binance_history(bin_client, db, user_id)
            db.commit()
            result["binance_snapshots_added"] = added
        except Exception as e:
            db.rollback()
            logger.warning("repair-user: Binance history falló user=%s: %s", user_id, e)
            result["errors"].append(f"Binance: {e}")

    # ── 4. Non-IOL backfill: Cocos + Manual usando PositionSnapshot histórico ─
    non_iol_positions = (
        db.query(Position)
        .filter(
            Position.user_id == user_id,
            Position.is_active.is_(True),
            Position.source != "IOL",
        )
        .all()
    )
    if non_iol_positions:
        non_iol_tickers = {p.ticker for p in non_iol_positions}
        all_pos_snaps = (
            db.query(PositionSnapshot)
            .filter(
                PositionSnapshot.user_id == user_id,
                PositionSnapshot.ticker.in_(non_iol_tickers),
            )
            .all()
        )
        pos_snap_index: dict[tuple, float] = {
            (s.ticker, s.snapshot_date): float(s.value_usd) for s in all_pos_snaps
        }
        first_seen: dict[str, date] = {}
        for s in all_pos_snaps:
            if s.ticker not in first_seen or s.snapshot_date < first_seen[s.ticker]:
                first_seen[s.ticker] = s.snapshot_date
        pos_by_ticker = {p.ticker: p for p in non_iol_positions}

        today_date = date.today()
        hist_snaps = (
            db.query(PortfolioSnapshot)
            .filter(
                PortfolioSnapshot.user_id == user_id,
                PortfolioSnapshot.snapshot_date < today_date,
            )
            .order_by(PortfolioSnapshot.snapshot_date)
            .all()
        )
        patched = 0
        for snap in hist_snaps:
            offset = 0.0
            count_added = 0
            for ticker, pos in pos_by_ticker.items():
                start = first_seen.get(ticker, pos.snapshot_date)
                if start > snap.snapshot_date:
                    continue
                val = pos_snap_index.get((ticker, snap.snapshot_date), float(pos.current_value_usd))
                if val > 0:
                    offset += val
                    count_added += 1
            if offset > 0:
                snap.total_usd = snap.total_usd + Decimal(str(round(offset, 2)))
                snap.positions_count = (snap.positions_count or 0) + count_added
                patched += 1
        try:
            db.commit()
            result["non_iol_snapshots_patched"] = patched
        except Exception as e:
            db.rollback()
            logger.error("repair-user: backfill non-IOL falló user=%s: %s", user_id, e)
            result["errors"].append(f"backfill: {e}")

    # ── 5. Snapshot de HOY con todas las fuentes ─────────────────────────────
    try:
        today_date = date.today()
        all_positions = (
            db.query(Position)
            .filter(Position.user_id == user_id, Position.is_active.is_(True))
            .all()
        )
        if all_positions:
            mep = get_mep()
            total_usd = sum(p.current_value_usd for p in all_positions)
            existing = (
                db.query(PortfolioSnapshot)
                .filter(
                    PortfolioSnapshot.user_id == user_id,
                    PortfolioSnapshot.snapshot_date == today_date,
                )
                .first()
            )
            if existing:
                existing.total_usd = total_usd
                existing.positions_count = len(all_positions)
                existing.fx_mep = Decimal(str(round(float(mep), 2)))
            else:
                db.add(PortfolioSnapshot(
                    user_id=user_id,
                    snapshot_date=today_date,
                    total_usd=total_usd,
                    monthly_return_usd=Decimal("0"),
                    positions_count=len(all_positions),
                    fx_mep=Decimal(str(round(float(mep), 2))),
                    cost_basis_usd=Decimal("0"),
                ))
            db.commit()
            result["today_snapshot"] = True
    except Exception as e:
        db.rollback()
        logger.error("repair-user: snapshot hoy falló user=%s: %s", user_id, e)
        result["errors"].append(f"today_snapshot: {e}")

    result["message"] = (
        "Repair completado con todas las fuentes. "
        f"IOL: {result['iol_snapshots_reconstructed']} snaps, "
        f"Binance: {result['binance_snapshots_added']} snaps, "
        f"non-IOL patched: {result['non_iol_snapshots_patched']} snaps."
        + (f" Errores: {result['errors']}" if result["errors"] else "")
    )
    logger.info("repair-user completado: user=%s %s", user_id, result["message"])
    return result


@router.get("/support/snapshot-health")
def support_snapshot_health(
    user_id: str = Query(...),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Diagnóstico rápido del estado de snapshots de un usuario.
    Muestra rango de fechas, valores min/max/avg y los últimos 10 snapshots.
    Usar para confirmar si un repair fue exitoso o si los valores son coherentes.
    """
    from sqlalchemy import func as sqlfunc

    stats = (
        db.query(
            sqlfunc.count(PortfolioSnapshot.id),
            sqlfunc.min(PortfolioSnapshot.total_usd),
            sqlfunc.max(PortfolioSnapshot.total_usd),
            sqlfunc.avg(PortfolioSnapshot.total_usd),
            sqlfunc.min(PortfolioSnapshot.snapshot_date),
            sqlfunc.max(PortfolioSnapshot.snapshot_date),
        )
        .filter(PortfolioSnapshot.user_id == user_id)
        .first()
    )

    recent = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.user_id == user_id)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(10)
        .all()
    )

    count = stats[0] or 0
    max_val = float(stats[2]) if stats[2] else 0
    avg_val = float(stats[3]) if stats[3] else 0

    # Heurística: si max > 10x avg, probablemente hay snapshots inflados
    inflation_suspected = count > 5 and max_val > avg_val * 5

    return {
        "user_id": user_id,
        "count": count,
        "min_usd": float(stats[1]) if stats[1] else None,
        "max_usd": max_val or None,
        "avg_usd": avg_val or None,
        "oldest": stats[4].isoformat() if stats[4] else None,
        "newest": stats[5].isoformat() if stats[5] else None,
        "inflation_suspected": inflation_suspected,
        "recent_10": [
            {
                "date": s.snapshot_date.isoformat(),
                "total_usd": float(s.total_usd),
                "positions": s.positions_count,
            }
            for s in recent
        ],
    }


@router.post("/support/force-snapshot-today")
def support_force_snapshot_today(
    user_id: str = Query(..., description="UUID del usuario"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Fuerza la actualización del snapshot de HOY usando TODAS las posiciones activas
    del usuario (IOL + Cocos + Manual + cualquier otra fuente).

    Útil cuando repair-user reconstruye histórico solo con IOL pero el usuario
    tiene posiciones de otras fuentes (Cocos, Manual) que no se incluyen en la
    reconstrucción histórica.

    NO toca snapshots históricos — solo el de hoy.
    """
    from decimal import Decimal as D
    from app.services.mep import get_mep
    from app.services.freedom_calculator import calculate_freedom_score

    today = date.today()

    positions = (
        db.query(Position)
        .filter(
            Position.user_id == user_id,
            Position.is_active.is_(True),
        )
        .all()
    )

    if not positions:
        raise HTTPException(status_code=404, detail="No hay posiciones activas para este usuario")

    mep = get_mep()
    score = calculate_freedom_score(positions, D("1000"))  # expenses irrelevantes aquí
    total_usd = sum(p.current_value_usd for p in positions)
    total_cost_basis = sum(
        getattr(p, "cost_basis_usd", D("0")) or D("0") for p in positions
    )
    monthly_return = score["monthly_return_usd"]

    snapshot = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date == today,
        )
        .first()
    )
    if snapshot:
        snapshot.total_usd = total_usd
        snapshot.monthly_return_usd = monthly_return
        snapshot.positions_count = len(positions)
        snapshot.cost_basis_usd = total_cost_basis
        snapshot.fx_mep = mep
    else:
        db.add(
            PortfolioSnapshot(
                user_id=user_id,
                snapshot_date=today,
                total_usd=total_usd,
                monthly_return_usd=monthly_return,
                positions_count=len(positions),
                cost_basis_usd=total_cost_basis,
                fx_mep=mep,
            )
        )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "support/force-snapshot-today: user=%s total_usd=%.2f positions=%d",
        user_id,
        float(total_usd),
        len(positions),
    )
    return {
        "user_id": user_id,
        "snapshot_date": today.isoformat(),
        "total_usd": float(total_usd),
        "positions_count": len(positions),
        "fx_mep": float(mep),
        "message": "Snapshot de hoy actualizado con todas las posiciones activas.",
    }


@router.post("/support/backfill-non-iol")
def support_backfill_non_iol(
    user_id: str = Query(..., description="UUID del usuario"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Parcha snapshots históricos añadiendo el valor REAL de posiciones no-IOL en cada fecha.

    Estrategia (en orden de calidad de datos):
    1. Si existe un PositionSnapshot para esa posición en esa fecha → usar ese valor exacto.
    2. Si no existe snapshot pero la posición ya existía (Position.snapshot_date <= fecha) →
       usar current_value_usd como aproximación (posición existía, no tenemos precio histórico).
    3. Si Position.snapshot_date > fecha → la posición no existía, NO sumar.

    De esta forma:
    - Un CASH_USD ingresado el 4-abr no infla snapshots del 30-mar.
    - COCOSPPA que valía $4,471 en abril 3-9 y $2,447 desde el 10-abr se refleja correctamente
      porque sus PositionSnapshots históricos existen.

    NO toca el snapshot de hoy (usar force-snapshot-today para eso).
    """
    from app.models import PositionSnapshot
    today = date.today()

    non_iol_positions = (
        db.query(Position)
        .filter(
            Position.user_id == user_id,
            Position.is_active.is_(True),
            Position.source != "IOL",
        )
        .all()
    )

    if not non_iol_positions:
        return {
            "user_id": user_id,
            "message": "No hay posiciones no-IOL activas. Nada que hacer.",
            "snapshots_patched": 0,
        }

    from app.models import PositionSnapshot
    non_iol_tickers = {p.ticker for p in non_iol_positions}

    # Pre-cargar todos los PositionSnapshots no-IOL (sin filtro de fecha, necesitamos el primer)
    all_pos_snaps = (
        db.query(PositionSnapshot)
        .filter(
            PositionSnapshot.user_id == user_id,
            PositionSnapshot.ticker.in_(non_iol_tickers),
        )
        .all()
    )
    # Índice: {(ticker, date) -> value_usd}
    pos_snap_index: dict[tuple, float] = {
        (s.ticker, s.snapshot_date): float(s.value_usd)
        for s in all_pos_snaps
    }
    # Fecha de inicio REAL: la más temprana en PositionSnapshot.
    # Position.snapshot_date refleja el último sync, no el primero — no sirve para esto.
    first_seen: dict[str, date] = {}
    for s in all_pos_snaps:
        if s.ticker not in first_seen or s.snapshot_date < first_seen[s.ticker]:
            first_seen[s.ticker] = s.snapshot_date

    pos_by_ticker = {p.ticker: p for p in non_iol_positions}

    historical_snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date < today,
        )
        .order_by(PortfolioSnapshot.snapshot_date)
        .all()
    )

    patched = 0
    detail_log = []
    for snap in historical_snapshots:
        offset = 0.0
        count_added = 0
        for ticker, pos in pos_by_ticker.items():
            # Inicio real de la posición: primer PositionSnapshot o Position.snapshot_date
            start_date = first_seen.get(ticker, pos.snapshot_date)
            if start_date > snap.snapshot_date:
                continue  # Posición no existía en esta fecha
            # PositionSnapshot exacto si existe; valor actual como aproximación si no
            if (ticker, snap.snapshot_date) in pos_snap_index:
                val = pos_snap_index[(ticker, snap.snapshot_date)]
            else:
                val = float(pos.current_value_usd)
            if val > 0:
                offset += val
                count_added += 1

        if offset == 0:
            continue

        snap.total_usd = snap.total_usd + Decimal(str(round(offset, 2)))
        snap.positions_count = (snap.positions_count or 0) + count_added
        patched += 1
        detail_log.append({"date": snap.snapshot_date.isoformat(), "offset_added": round(offset, 2)})

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "support/backfill-non-iol: user=%s snapshots_patched=%d",
        user_id,
        patched,
    )
    return {
        "user_id": user_id,
        "non_iol_sources": list({p.source for p in non_iol_positions}),
        "non_iol_positions_count": len(non_iol_positions),
        "snapshots_patched": patched,
        "detail": detail_log,
        "message": (
            f"Se parcharon {patched} snapshots históricos usando valores reales por fecha "
            f"(PositionSnapshot cuando existe, snapshot_date como límite de inicio). "
            f"Luego llamar a force-snapshot-today."
        ),
    }


@router.delete("/cache/price-source-purge")
def price_source_purge(
    ticker: Optional[str] = Query(None, description="Ticker específico o todos"),
    source: str = Query(..., description="Fuente a purgar: YAHOO | IOL_BOND | IOL"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """
    Purga entradas de price_history por fuente (YAHOO, IOL_BOND, IOL).
    Útil para forzar re-fetch desde una fuente cuando los precios cacheados son incorrectos.
    Ejemplo: purgar YAHOO para un ticker CEDEAR para que el próximo sync use IOL.
    """
    q = db.query(PriceHistory).filter(PriceHistory.source == source)
    if ticker:
        q = q.filter(PriceHistory.ticker == ticker.upper())
    deleted = q.delete(synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    logger.info(
        "admin/cache/price-source-purge: %d rows deleted (source=%s, ticker=%s)",
        deleted,
        source,
        ticker or "ALL",
    )
    return {"deleted": deleted, "source": source, "ticker": ticker or "ALL"}
