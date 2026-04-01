"""Vercel entry point — auto-detected by framework preset."""

import os

os.environ.setdefault("VERCEL", "1")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.main import app  # noqa: E402 — Vercel looks for `app`
