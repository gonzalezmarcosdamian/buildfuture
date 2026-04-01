"""Vercel serverless entry point."""

import os

os.environ["VERCEL"] = "1"

from app.main import app  # noqa: E402

handler = app
