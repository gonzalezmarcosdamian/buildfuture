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
    Operación de soporte completa para un usuario con históricos incorrectos.

    Flujo:
    1. Purga snapshots históricos del usuario (todos, excepto hoy si se quiere conservar).
    2. Re-sincroniza IOL: actualiza posiciones con ppc_usd correcto y reconstruye histórico.

    Usar cuando:
    - El gráfico de tenencia muestra valores inflados (millones en vez de miles).
    - Se deployó un fix de precios (unit mismatch, fuente de datos nueva).
    - El cliente reporta que su portfolio histórico no coincide con la realidad.

    POST /admin/support/repair-user?user_id=<uuid>&purge_snapshots=true
    Header: X-Admin-Key: <ADMIN_SECRET_KEY>
    """
    from app.models import Integration
    from app.services.iol_client import IOLClient
    from app.routers.integrations import _sync_iol

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
            status_code=404,
            detail=f"IOL no conectado para user_id={user_id}. Solo soportado para usuarios IOL.",
        )

    # 1. Purgar snapshots
    deleted_snaps = 0
    if purge_snapshots:
        deleted_snaps = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.user_id == user_id)
            .delete(synchronize_session=False)
        )
        db.flush()
        logger.info("support/repair-user: %d snapshots purgados para user=%s", deleted_snaps, user_id)

    # 2. Re-sync IOL (actualiza posiciones + reconstruye histórico)
    try:
        creds = integration.encrypted_credentials.split(":", 1)
        client = IOLClient(creds[0], creds[1])
        result = _sync_iol(client, db, user_id)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("support/repair-user: sync falló para user=%s: %s", user_id, e)
        raise HTTPException(status_code=502, detail=f"Sync IOL falló: {e}")

    logger.info(
        "support/repair-user: user=%s — %d snaps purgados, %d posiciones sync, %d snaps reconstruidos",
        user_id,
        deleted_snaps,
        result.get("positions_synced", 0),
        result.get("snapshots_reconstructed", 0),
    )
    return {
        "user_id": user_id,
        "snapshots_purged": deleted_snaps,
        "positions_synced": result.get("positions_synced", 0),
        "snapshots_reconstructed": result.get("snapshots_reconstructed", 0),
        "mep": result.get("mep"),
        "message": "Repair completado. El cliente puede recargar la app.",
    }


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
    Parcha snapshots históricos que solo tienen posiciones IOL añadiendo el valor
    actual de posiciones no-IOL (Cocos, Manual) como offset plano.

    Contexto: repair-user solo reconstruye histórico con IOL. Si el usuario tiene
    posiciones Cocos o Manual, esos valores no se incluyen en los snapshots históricos.
    Este endpoint los suma como offset fijo al total_usd de cada snapshot pasado,
    y corrige positions_count.

    Es una aproximación: asume que el valor de posiciones no-IOL es constante
    en el tiempo (lo mejor que podemos hacer sin histórico de esas posiciones).

    NO toca el snapshot de hoy (usar force-snapshot-today para eso).
    """
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
            "non_iol_value_usd": 0.0,
            "snapshots_patched": 0,
        }

    non_iol_total = float(sum(p.current_value_usd for p in non_iol_positions))
    non_iol_count = len(non_iol_positions)

    historical_snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date < today,
        )
        .all()
    )

    patched = 0
    for snap in historical_snapshots:
        snap.total_usd = snap.total_usd + non_iol_total
        snap.positions_count = snap.positions_count + non_iol_count
        patched += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    logger.info(
        "support/backfill-non-iol: user=%s non_iol_value=%.2f snapshots_patched=%d",
        user_id,
        non_iol_total,
        patched,
    )
    return {
        "user_id": user_id,
        "non_iol_sources": list({p.source for p in non_iol_positions}),
        "non_iol_positions_count": non_iol_count,
        "non_iol_value_usd": round(non_iol_total, 2),
        "snapshots_patched": patched,
        "message": (
            f"Se añadió USD {non_iol_total:.2f} de {non_iol_count} posiciones no-IOL "
            f"a {patched} snapshots históricos. Luego llamar a force-snapshot-today."
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
