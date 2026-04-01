"""
Scheduler de tareas automáticas — BuildFuture.

Backup: antes de cada job diario se copia buildfuture.db → backups/buildfuture_YYYY-MM-DD.db.
Se retienen los últimos 30 días. Las tablas irrecuperables (portfolio_snapshots, integrations)
quedan protegidas sin depender de servicios externos.

Job diario: cierre de mercado local (17:30 ART = 20:30 UTC).
  1. Sync portafolio IOL si está conectado.
  2. Guarda snapshot diario de valor del portafolio (por cada usuario activo).

El scheduler corre en-proceso con FastAPI (APScheduler 3.x BackgroundScheduler).
Solo captura datos mientras el servidor está corriendo — aceptable para uso personal.
"""

import logging
import shutil
import glob
from datetime import date
from decimal import Decimal
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("buildfuture.scheduler")

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")

    # Cierre de mercado: lunes a viernes 17:30 ART
    _scheduler.add_job(
        _daily_close_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=30,
            timezone="America/Argentina/Buenos_Aires",
        ),
        id="daily_close",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler iniciado — job diario: L-V 17:30 ART")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler detenido")


DB_PATH = Path(__file__).parent.parent / "buildfuture.db"
BACKUP_DIR = Path(__file__).parent.parent / "backups"
BACKUP_RETENTION_DAYS = 30


def _backup_db() -> None:
    """Copia buildfuture.db → backups/buildfuture_YYYY-MM-DD.db. Retiene 30 días."""
    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(exist_ok=True)
    dest = BACKUP_DIR / f"buildfuture_{date.today().isoformat()}.db"
    if not dest.exists():
        shutil.copy2(DB_PATH, dest)
        logger.info("Backup creado: %s", dest.name)

    # Limpiar backups viejos (> 30 días)
    all_backups = sorted(glob.glob(str(BACKUP_DIR / "buildfuture_*.db")))
    for old in all_backups[:-BACKUP_RETENTION_DAYS]:
        Path(old).unlink(missing_ok=True)
        logger.info("Backup viejo eliminado: %s", Path(old).name)


def _daily_close_job() -> None:
    """Tarea principal del cierre de mercado."""
    logger.info("=== Cierre de mercado — snapshot diario ===")
    try:
        _backup_db()
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            _maybe_sync_iol(db)
            _refresh_manual_prices(db)
            _save_portfolio_snapshot(db)
        finally:
            db.close()
    except Exception as e:
        logger.error("Error en daily_close_job: %s", e, exc_info=True)


def _maybe_sync_iol(db) -> None:
    """Sync IOL para todos los usuarios conectados."""
    from app.models import Integration
    from app.services.iol_client import IOLClient
    from app.routers.integrations import _sync_iol

    integrations = db.query(Integration).filter(
        Integration.provider == "IOL",
        Integration.is_connected == True,
    ).all()

    if not integrations:
        logger.info("IOL no conectado — skip sync")
        return

    for integration in integrations:
        if not integration.encrypted_credentials:
            continue
        try:
            creds = integration.encrypted_credentials.split(":", 1)
            client = IOLClient(creds[0], creds[1])
            result = _sync_iol(client, db, integration.user_id)
            from datetime import datetime
            integration.last_synced_at = datetime.utcnow()
            integration.last_error = ""
            db.commit()
            logger.info("IOL sync OK user=%s — posiciones: %d, meses: %d",
                        integration.user_id,
                        result.get("positions_synced", 0),
                        result.get("months_synced", 0))
        except Exception as e:
            logger.warning("IOL sync falló en scheduler user=%s: %s", integration.user_id, e)
            integration.last_error = str(e)[:200]
            db.commit()


def _refresh_manual_prices(db) -> None:
    """Actualiza current_price_usd y annual_yield_pct para posiciones manuales."""
    from decimal import Decimal
    from app.models import Position
    from app.services import crypto_prices, fci_prices, external_prices

    manual = db.query(Position).filter(
        Position.source == "MANUAL",
        Position.is_active == True,
    ).all()

    if not manual:
        return

    # MEP actual para convertir VCP de FCI (ARS) a USD
    fx_mep = 1430.0
    try:
        import httpx
        r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if r.status_code == 200:
            fx_mep = float(r.json().get("venta", fx_mep))
    except Exception:
        pass

    for pos in manual:
        try:
            if pos.asset_type == "CRYPTO" and pos.external_id:
                price = crypto_prices.get_price_usd(pos.external_id)
                if price:
                    pos.current_price_usd = Decimal(str(price))
                yield_pct = crypto_prices.get_yield_30d(pos.external_id)
                pos.annual_yield_pct = Decimal(str(yield_pct))

            elif pos.asset_type == "FCI" and pos.external_id and pos.fci_categoria:
                vcp = fci_prices.get_vcp(pos.external_id, pos.fci_categoria)
                if vcp and fx_mep > 0:
                    pos.current_price_usd = Decimal(str(vcp / fx_mep))
                yield_pct = fci_prices.get_yield_30d(pos.external_id, pos.fci_categoria)
                pos.annual_yield_pct = Decimal(str(yield_pct))

            elif pos.asset_type in ("ETF", "CEDEAR") and pos.external_id:
                price = external_prices.get_price_usd(pos.external_id)
                if price:
                    pos.current_price_usd = Decimal(str(price))
                yield_pct = external_prices.get_yield_30d(pos.external_id)
                pos.annual_yield_pct = Decimal(str(yield_pct))

            logger.info("Precio manual actualizado: %s %s → USD %.4f yield %.2f%%",
                        pos.asset_type, pos.ticker,
                        float(pos.current_price_usd), float(pos.annual_yield_pct) * 100)
        except Exception as e:
            logger.warning("Refresh precio manual falló (%s %s): %s",
                           pos.asset_type, pos.ticker, e)

    db.commit()


def _save_portfolio_snapshot(db) -> None:
    """Guarda snapshot diario para cada usuario con posiciones activas."""
    from app.models import Position, PortfolioSnapshot
    from app.services.freedom_calculator import calculate_freedom_score

    today = date.today()

    # Obtener todos los user_ids distintos con posiciones activas
    user_ids = (
        db.query(Position.user_id)
        .filter(Position.is_active == True)
        .distinct()
        .all()
    )

    if not user_ids:
        logger.info("Sin posiciones activas — skip snapshot")
        return

    # Intentar traer MEP actual una sola vez
    fx_mep = Decimal("0")
    try:
        import httpx
        r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
        if r.status_code == 200:
            fx_mep = Decimal(str(r.json().get("venta", 0)))
    except Exception:
        pass

    for (user_id,) in user_ids:
        existing = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.snapshot_date == today,
            PortfolioSnapshot.user_id == user_id,
        ).first()
        if existing:
            logger.info("Snapshot de hoy ya existe para user=%s — skip", user_id)
            continue

        positions = db.query(Position).filter(
            Position.is_active == True,
            Position.user_id == user_id,
        ).all()
        if not positions:
            continue

        score = calculate_freedom_score(positions, Decimal("2000"))
        total_usd = score["portfolio_total_usd"]
        monthly_return = score["monthly_return_usd"]

        snapshot = PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=today,
            total_usd=total_usd,
            monthly_return_usd=monthly_return,
            positions_count=len(positions),
            fx_mep=fx_mep,
        )
        db.add(snapshot)
        db.commit()
        logger.info("Snapshot guardado user=%s: USD %.2f | retorno %.2f/mes | MEP %.0f",
                    user_id, float(total_usd), float(monthly_return), float(fx_mep))


def trigger_snapshot_now() -> dict:
    """
    Dispara el job manualmente (para sync desde la UI).
    Retorna el resultado del snapshot.
    """
    logger.info("Snapshot manual disparado")
    _daily_close_job()
    return {"triggered": True}
