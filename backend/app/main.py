import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, SessionLocal
from app.models import Base
from app.routers import portfolio, budget, integrations
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

app = FastAPI(title="BuildFuture API", version="0.6.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router)
app.include_router(budget.router)
app.include_router(integrations.router)


@app.on_event("startup")
def startup():
    if IS_SERVERLESS:
        return
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    seed(db)
    db.close()
    start_scheduler()


@app.on_event("shutdown")
def shutdown():
    if not IS_SERVERLESS:
        stop_scheduler()


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.6.1"}


@app.post("/admin/snapshot")
def manual_snapshot():
    """Dispara el snapshot manualmente — útil para testing o sync forzado."""
    from app.scheduler import trigger_snapshot_now
    return trigger_snapshot_now()
