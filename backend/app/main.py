import logging
import os

logger = logging.getLogger("buildfuture.main")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, SessionLocal
from app.models import Base
from app.routers import portfolio, budget, integrations, profile, positions
IS_SERVERLESS = os.environ.get("VERCEL", "") == "1"

if not IS_SERVERLESS:
    from app.seed import seed
    from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

app = FastAPI(title="BuildFuture API", version="0.10.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router)
app.include_router(budget.router)
app.include_router(integrations.router)
app.include_router(profile.router)
app.include_router(positions.router)


@app.on_event("startup")
def startup():
    if IS_SERVERLESS:
        return
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    db = SessionLocal()
    seed(db)
    if os.getenv("MOCK_SEED") == "true":
        from app.seed_mock import seed_mock
        seed_mock(db)
    _purge_bad_manual_positions(db)
    _dedup_positions(db)
    _backfill_integrations(db)
    db.close()
    start_scheduler()


def _run_migrations():
    """Migraciones incrementales — ALTER TABLE y CREATE INDEX para Postgres."""
    from sqlalchemy import text
    migrations = [
        (
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS current_value_ars NUMERIC(18,2) DEFAULT 0",
            "positions.current_value_ars",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_positions_user_active ON positions(user_id, is_active)",
            "idx_positions_user_active",
        ),
        (
            "ALTER TABLE portfolio_snapshots ADD COLUMN IF NOT EXISTS cost_basis_usd NUMERIC(12,2) DEFAULT 0",
            "portfolio_snapshots.cost_basis_usd",
        ),
        (
            """CREATE TABLE IF NOT EXISTS capital_goals (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                name VARCHAR(100) NOT NULL,
                emoji VARCHAR(10) DEFAULT '🎯',
                target_usd NUMERIC(12,2) NOT NULL,
                target_years INTEGER DEFAULT 5,
                created_at TIMESTAMP DEFAULT NOW()
            )""",
            "capital_goals table",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_capital_goals_user ON capital_goals(user_id)",
            "idx_capital_goals_user",
        ),
    ]
    try:
        with engine.connect() as conn:
            for sql, label in migrations:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info("Migration OK: %s", label)
                except Exception as e:
                    conn.rollback()
                    logger.warning("Migration skipped (%s): %s", label, e)
    except Exception as e:
        logger.warning("_run_migrations connection failed: %s", e)


def _purge_bad_manual_positions(db):
    """One-time cleanup: desactiva posiciones manuales con valor absurdo (> 10M USD)."""
    from app.models import Position
    from decimal import Decimal
    try:
        bad = db.query(Position).filter(
            Position.source == "MANUAL",
            Position.is_active == True,
        ).all()
        purged = 0
        for p in bad:
            if float(p.quantity) * float(p.current_price_usd) > 10_000_000:
                p.is_active = False
                purged += 1
                logger.info("Purged bad manual position: %s id=%s value=%.0f", p.ticker, p.id, float(p.quantity * p.current_price_usd))
        if purged:
            db.commit()
            logger.info("Purged %d bad manual positions on startup", purged)
    except Exception as e:
        logger.warning("_purge_bad_manual_positions failed: %s", e)
        db.rollback()


def _dedup_positions(db):
    """
    Limpia posiciones duplicadas activas causadas por race condition en auto-sync.
    Para cada (user_id, ticker, source) mantiene solo la posición con el id más alto
    (la más reciente) y desactiva las anteriores.
    """
    from app.models import Position
    from sqlalchemy import func
    try:
        # Encontrar grupos con más de una posición activa para el mismo ticker
        dupes = (
            db.query(Position.user_id, Position.ticker, Position.source,
                     func.count(Position.id).label("cnt"),
                     func.max(Position.id).label("keep_id"))
            .filter(Position.is_active == True)
            .group_by(Position.user_id, Position.ticker, Position.source)
            .having(func.count(Position.id) > 1)
            .all()
        )
        total = 0
        for row in dupes:
            deactivated = (
                db.query(Position)
                .filter(
                    Position.user_id == row.user_id,
                    Position.ticker == row.ticker,
                    Position.source == row.source,
                    Position.is_active == True,
                    Position.id != row.keep_id,
                )
                .update({"is_active": False})
            )
            total += deactivated
        if total:
            db.commit()
            logger.info("_dedup_positions: %d posiciones duplicadas desactivadas", total)
    except Exception as e:
        logger.warning("_dedup_positions failed: %s", e)
        db.rollback()


_DEFAULT_INTEGRATIONS = [
    {"provider": "IOL",  "provider_type": "ALYC"},
    {"provider": "PPI",  "provider_type": "ALYC"},
]

def _backfill_integrations(db):
    """
    Garantiza que todos los usuarios existentes tengan los registros
    de integración IOL y PPI. Crea únicamente los que faltan.
    Cubre usuarios creados antes de que el lazy-creation existiera.
    """
    from app.models import Integration, Position
    from sqlalchemy import select, distinct
    try:
        # Recolectar todos los user_id conocidos en la DB
        user_ids = set()
        for model in (Position,):
            rows = db.execute(select(distinct(model.user_id))).scalars().all()
            user_ids.update(rows)

        created = 0
        for user_id in user_ids:
            existing_providers = {
                i.provider
                for i in db.query(Integration.provider)
                .filter(Integration.user_id == user_id)
                .all()
            }
            for spec in _DEFAULT_INTEGRATIONS:
                if spec["provider"] not in existing_providers:
                    db.add(Integration(
                        user_id=user_id,
                        provider=spec["provider"],
                        provider_type=spec["provider_type"],
                        is_active=True,
                        is_connected=False,
                    ))
                    created += 1
        if created:
            db.commit()
            logger.info("_backfill_integrations: %d registros creados para %d usuarios", created, len(user_ids))
    except Exception as e:
        logger.warning("_backfill_integrations failed: %s", e)
        db.rollback()


@app.on_event("shutdown")
def shutdown():
    if not IS_SERVERLESS:
        stop_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "version": "0.10.0", "env": "vercel"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.10.0"}


@app.post("/admin/snapshot")
def manual_snapshot():
    """Dispara el snapshot manualmente — útil para testing o sync forzado."""
    from app.scheduler import trigger_snapshot_now
    return trigger_snapshot_now()


