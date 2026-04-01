"""Vercel serverless entry point — with error capture."""

import os
import traceback

os.environ["VERCEL"] = "1"

from fastapi import FastAPI

debug_app = FastAPI()
real_app = None
boot_error = None

try:
    from app.main import app as real_app
except Exception as e:
    boot_error = traceback.format_exc()


if real_app is not None:
    app = real_app
else:
    app = debug_app

    @app.get("/{path:path}")
    def catch_all(path: str = ""):
        return {"error": "app failed to load", "traceback": boot_error}

handler = app
