import logging
import os

logger = logging.getLogger("buildfuture.main")
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, SessionLocal
from app.models import Base
from app.routers import (
    portfolio,
    budget,
    integrations,
    profile,
    positions,
    admin,
    waitlist,
    tos,
)

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

app = FastAPI(title="BuildFuture API", version="0.14.0")

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
app.include_router(admin.router, include_in_schema=False)  # no expuesto en /docs
app.include_router(waitlist.router)
app.include_router(tos.router)


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
    _backfill_instrument_metadata(db)   # v0.12.0: seed metadata estática de instrumentos
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
        (
            "ALTER TABLE capital_goals ADD COLUMN IF NOT EXISTS backing_position_id INTEGER REFERENCES positions(id) ON DELETE SET NULL",
            "capital_goals.backing_position_id",
        ),
        (
            """CREATE TABLE IF NOT EXISTS price_history (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR(20) NOT NULL,
                price_date DATE NOT NULL,
                price_usd NUMERIC(14,4) NOT NULL,
                source VARCHAR(20) DEFAULT 'YAHOO',
                CONSTRAINT uq_price_ticker_date UNIQUE (ticker, price_date)
            )""",
            "price_history table",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_price_history_ticker ON price_history(ticker, price_date)",
            "idx_price_history_ticker",
        ),
        (
            """CREATE TABLE IF NOT EXISTS mep_history (
                id SERIAL PRIMARY KEY,
                price_date DATE NOT NULL,
                mep_rate NUMERIC(10,2) NOT NULL,
                source VARCHAR(20) DEFAULT 'BLUELYTICS',
                CONSTRAINT uq_mep_date UNIQUE (price_date)
            )""",
            "mep_history table",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_mep_history_date ON mep_history(price_date)",
            "idx_mep_history_date",
        ),
        (
            """CREATE TABLE IF NOT EXISTS tos_versions (
                id SERIAL PRIMARY KEY,
                version TEXT NOT NULL UNIQUE,
                effective_date DATE NOT NULL,
                summary TEXT,
                is_current BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW()
            )""",
            "tos_versions table",
        ),
        (
            """CREATE TABLE IF NOT EXISTS tos_acceptances (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                version_id INTEGER NOT NULL REFERENCES tos_versions(id),
                accepted_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_tos_user_version UNIQUE (user_id, version_id)
            )""",
            "tos_acceptances table",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_tos_acceptances_user ON tos_acceptances(user_id)",
            "idx_tos_acceptances_user",
        ),
        (
            """INSERT INTO tos_versions (version, effective_date, summary, is_current)
               VALUES ('1.0', '2026-04-03', 'Versión inicial — términos, privacidad y disclaimer CNV', true)
               ON CONFLICT (version) DO NOTHING""",
            "tos_versions seed v1.0",
        ),
        (
            "ALTER TABLE portfolio_snapshots ADD COLUMN IF NOT EXISTS non_iol_offset_usd NUMERIC(12,2) DEFAULT 0",
            "portfolio_snapshots.non_iol_offset_usd",
        ),
        # ── v0.12.0: Price Store + yield soberano ────────────────────────────
        (
            """CREATE TABLE IF NOT EXISTS instrument_metadata (
                ticker          VARCHAR(20) PRIMARY KEY,
                asset_type      VARCHAR(20) NOT NULL,
                emision_date    DATE,
                maturity_date   DATE,
                tem             NUMERIC(8,6),
                currency        CHAR(3) DEFAULT 'ARS',
                fondo_name      VARCHAR(100),
                fci_categoria   VARCHAR(50),
                description     VARCHAR(200),
                fetched_at      TIMESTAMP NOT NULL DEFAULT NOW()
            )""",
            "instrument_metadata table",
        ),
        (
            """CREATE TABLE IF NOT EXISTS instrument_prices (
                id          SERIAL PRIMARY KEY,
                ticker      VARCHAR(20) NOT NULL,
                price_date  DATE NOT NULL,
                vwap        NUMERIC(14,4),
                prev_close  NUMERIC(14,4),
                volume      NUMERIC(18,2),
                mep         NUMERIC(10,2),
                source      VARCHAR(20) NOT NULL DEFAULT 'BYMA',
                CONSTRAINT uq_instrument_price UNIQUE (ticker, price_date)
            )""",
            "instrument_prices table",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_instrument_prices_ticker_date ON instrument_prices(ticker, price_date DESC)",
            "idx_instrument_prices_ticker_date",
        ),
        (
            "ALTER TABLE position_snapshots ADD COLUMN IF NOT EXISTS value_ars NUMERIC(14,2) DEFAULT NULL",
            "position_snapshots.value_ars",
        ),
        (
            "ALTER TABLE position_snapshots ADD COLUMN IF NOT EXISTS mep NUMERIC(10,2) DEFAULT NULL",
            "position_snapshots.mep",
        ),
        (
            "ALTER TABLE positions ADD COLUMN IF NOT EXISTS yield_currency CHAR(3) DEFAULT 'ARS'",
            "positions.yield_currency",
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
        bad = (
            db.query(Position)
            .filter(
                Position.source == "MANUAL",
                Position.is_active == True,
            )
            .all()
        )
        purged = 0
        for p in bad:
            if float(p.quantity) * float(p.current_price_usd) > 10_000_000:
                p.is_active = False
                purged += 1
                logger.info(
                    "Purged bad manual position: %s id=%s value=%.0f",
                    p.ticker,
                    p.id,
                    float(p.quantity * p.current_price_usd),
                )
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
            db.query(
                Position.user_id,
                Position.ticker,
                Position.source,
                func.count(Position.id).label("cnt"),
                func.max(Position.id).label("keep_id"),
            )
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
            logger.info(
                "_dedup_positions: %d posiciones duplicadas desactivadas", total
            )
    except Exception as e:
        logger.warning("_dedup_positions failed: %s", e)
        db.rollback()


_DEFAULT_INTEGRATIONS = [
    {"provider": "IOL", "provider_type": "ALYC"},
    {"provider": "PPI", "provider_type": "ALYC"},
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
                    db.add(
                        Integration(
                            user_id=user_id,
                            provider=spec["provider"],
                            provider_type=spec["provider_type"],
                            is_active=True,
                            is_connected=False,
                        )
                    )
                    created += 1
        if created:
            db.commit()
            logger.info(
                "_backfill_integrations: %d registros creados para %d usuarios",
                created,
                len(user_ids),
            )
    except Exception as e:
        logger.warning("_backfill_integrations failed: %s", e)
        db.rollback()


def _backfill_instrument_metadata(db):
    """
    v0.12.0: llama a fichatecnica de BYMA para todas las posiciones activas
    LETRA/BOND/ON y guarda la metadata estática en instrument_metadata.
    Solo corre para tickers no registrados todavía — idempotente.
    """
    try:
        from app.services.price_collector import backfill_metadata_from_positions
        n = backfill_metadata_from_positions(db)
        logger.info("_backfill_instrument_metadata: %d tickers guardados", n)
    except Exception as e:
        logger.warning("_backfill_instrument_metadata falló (no crítico): %s", e)


@app.on_event("shutdown")
def shutdown():
    if not IS_SERVERLESS:
        stop_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "version": "0.14.0", "env": "vercel"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.14.0"}


@app.post("/admin/snapshot")
def manual_snapshot():
    """Dispara el snapshot manualmente — útil para testing o sync forzado."""
    from app.scheduler import trigger_snapshot_now

    return trigger_snapshot_now()


@app.post("/admin/collect-prices")
def manual_collect_prices(background_tasks: BackgroundTasks):
    """
    Dispara el price collector manualmente en background.
    Retorna inmediatamente — el job corre en background del servidor.
    Ver logs Railway para el resultado.
    """
    def _run():
        from app.database import SessionLocal
        from app.services.price_collector import collect_daily_prices
        from app.services.mep import get_mep
        from decimal import Decimal
        db = SessionLocal()
        try:
            mep = Decimal(str(get_mep()))
            summary = collect_daily_prices(db, mep_today=mep)
            logger.info("manual collect-prices: %s", summary)
        except Exception as e:
            logger.error("manual collect-prices falló: %s", e)
        finally:
            db.close()

    background_tasks.add_task(_run)
    return {"status": "accepted", "message": "Price collector iniciado en background — ver logs Railway"}


@app.post("/admin/collect-metadata")
def manual_collect_metadata():
    """Dispara el backfill de metadata estática (fichatecnica BYMA) para posiciones activas."""
    from app.database import SessionLocal
    from app.services.price_collector import backfill_metadata_from_positions

    db = SessionLocal()
    try:
        n = backfill_metadata_from_positions(db)
        return {"status": "ok", "tickers_saved": n}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()
