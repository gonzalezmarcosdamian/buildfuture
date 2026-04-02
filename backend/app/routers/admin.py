"""
Endpoints de administración interna — sólo para soporte/equipo BuildFuture.
Protegidos con X-Admin-Key (env ADMIN_SECRET_KEY).
NO exponer a clientes ni documentar en el API público.
"""
import logging
import os
from datetime import date
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
        raise HTTPException(status_code=503, detail="Admin endpoints no configurados (ADMIN_SECRET_KEY ausente)")
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
            by_user[uid] = {"count": 0, "oldest": r.snapshot_date, "newest": r.snapshot_date}
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
    user_id: Optional[str] = Query(None, description="Si se omite, purga TODOS los usuarios"),
    before_date: Optional[date] = Query(None, description="Borrar snapshots anteriores a esta fecha (YYYY-MM-DD). Por defecto: hoy"),
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

    logger.info("admin/snapshots/purge: %d rows deleted (user=%s, before=%s)", deleted, user_id, cutoff)
    return {
        "deleted": deleted,
        "user_id": user_id or "ALL",
        "before_date": cutoff.isoformat(),
        "message": "Snapshots eliminados. El próximo sync los regenerará automáticamente.",
    }


@router.delete("/snapshots/purge-user-all")
def snapshots_purge_all_for_user(
    user_id: str = Query(..., description="Usuario a limpiar completamente"),
    db: Session = Depends(get_db),
    _: None = Depends(verify_admin),
):
    """Elimina TODOS los snapshots de un usuario (reset completo de historial)."""
    deleted = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.user_id == user_id
    ).delete(synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info("admin/snapshots/purge-user-all: %d rows deleted for user=%s", deleted, user_id)
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
            t: {**v, "oldest": v["oldest"].isoformat(), "newest": v["newest"].isoformat()}
            for t, v in by_ticker.items()
        },
    }


@router.delete("/cache/price-purge")
def price_cache_purge(
    ticker: Optional[str] = Query(None, description="Si se omite, purga TODA la caché de precios"),
    before_date: Optional[date] = Query(None, description="Borrar entradas anteriores a esta fecha"),
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
    q = db.query(Position).filter(Position.user_id == user_id, Position.is_active == True)  # noqa: E712
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
                "implied_total_usd": round(float(r.quantity) * float(r.current_price_usd or 0), 2),
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
        "items": [{"user_id": r.user_id, "ticker": r.ticker, "source": r.source, "count": r.cnt} for r in rows],
    }


@router.delete("/positions/dedup")
def positions_dedup(
    user_id: Optional[str] = Query(None, description="Si se omite, dedup para todos los usuarios"),
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


@router.delete("/cache/mep-purge")
def mep_cache_purge(
    before_date: Optional[date] = Query(None, description="Borrar entradas de MEP anteriores a esta fecha"),
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
