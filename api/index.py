"""Vercel serverless entry point — wraps the FastAPI app."""

import sys
import os
from pathlib import Path

# Add backend directory to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Force VERCEL flag before any app import
os.environ["VERCEL"] = "1"

from app.main import app  # noqa: E402


@app.get("/debug-env")
def debug_env():
    return {
        "VERCEL": os.environ.get("VERCEL", "NOT SET"),
        "DATABASE_URL": "set" if os.environ.get("DATABASE_URL") else "NOT SET",
        "SUPABASE_URL": "set" if os.environ.get("SUPABASE_URL") else "NOT SET",
    }


handler = app
