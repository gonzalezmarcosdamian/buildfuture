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
    db = SessionLocal()
    seed(db)
    _purge_bad_manual_positions(db)
    db.close()
    start_scheduler()


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


@app.on_event("shutdown")
def shutdown():
    if not IS_SERVERLESS:
        stop_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "version": "0.9.0", "env": "vercel"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.9.0"}


@app.post("/admin/snapshot")
def manual_snapshot():
    """Dispara el snapshot manualmente — útil para testing o sync forzado."""
    from app.scheduler import trigger_snapshot_now
    return trigger_snapshot_now()


