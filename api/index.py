"""Vercel serverless entry point — wraps the FastAPI app."""

import sys
import os
from pathlib import Path

# Add backend directory to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

# Ensure Vercel env is set before importing app
os.environ.setdefault("VERCEL", "1")

from app.main import app  # noqa: E402

handler = app
