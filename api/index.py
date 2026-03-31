"""Vercel serverless entry point — minimal test first."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="BuildFuture API", version="0.6.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "version": "0.6.1", "env": "vercel"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.6.1"}


handler = app
