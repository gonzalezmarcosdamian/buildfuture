"""Vercel serverless entry point — full FastAPI backend."""

import os
import sys
from pathlib import Path

os.environ["VERCEL"] = "1"

# Add backend directory to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402

handler = app
