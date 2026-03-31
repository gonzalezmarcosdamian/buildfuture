"""Vercel serverless entry point — debug imports step by step."""

import sys
import os
from pathlib import Path

# Add backend directory to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BuildFuture API", version="0.6.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track which imports succeed
import_status = {}

try:
    from app.database import engine, SessionLocal, get_db, Base
    import_status["database"] = "ok"
except Exception as e:
    import_status["database"] = str(e)

try:
    from app.models import Position, BudgetConfig, BudgetCategory, FreedomGoal
    import_status["models"] = "ok"
except Exception as e:
    import_status["models"] = str(e)

try:
    from app.auth import get_current_user
    import_status["auth"] = "ok"
except Exception as e:
    import_status["auth"] = str(e)

try:
    from app.routers import portfolio
    import_status["router_portfolio"] = "ok"
except Exception as e:
    import_status["router_portfolio"] = str(e)

try:
    from app.routers import budget
    import_status["router_budget"] = "ok"
except Exception as e:
    import_status["router_budget"] = str(e)

try:
    from app.routers import integrations
    import_status["router_integrations"] = "ok"
except Exception as e:
    import_status["router_integrations"] = str(e)


@app.get("/")
@app.get("/health")
def health():
    return {"status": "debug", "imports": import_status}


handler = app
