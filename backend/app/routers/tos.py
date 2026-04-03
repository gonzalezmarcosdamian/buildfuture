"""
TyC — Términos y Condiciones con versionado.
GET  /tos/status  — ¿el usuario aceptó la versión actual?
POST /tos/accept  — registra aceptación de la versión actual.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.auth import get_current_user

logger = logging.getLogger("buildfuture.tos")
router = APIRouter(prefix="/tos", tags=["tos"])


def _get_current_version(db: Session) -> dict | None:
    row = db.execute(
        text("SELECT id, version, summary FROM tos_versions WHERE is_current = true LIMIT 1")
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "version": row[1], "summary": row[2]}


def _has_accepted(db: Session, user_id: str, version_id: int) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM tos_acceptances WHERE user_id = :uid AND version_id = :vid LIMIT 1"
        ),
        {"uid": user_id, "vid": version_id},
    ).fetchone()
    return row is not None


@router.get("/status")
def tos_status(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Devuelve si el usuario aceptó la versión actual de los TyC."""
    current = _get_current_version(db)
    if not current:
        # Sin versión activa — dejamos pasar (no bloquear por error de config)
        return {"accepted": True, "version": None}

    accepted = _has_accepted(db, user_id, current["id"])
    return {
        "accepted": accepted,
        "version": current["version"],
        "summary": current["summary"] if not accepted else None,
    }


@router.post("/accept")
def tos_accept(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Registra que el usuario aceptó la versión actual de los TyC."""
    current = _get_current_version(db)
    if not current:
        raise HTTPException(status_code=404, detail="No hay versión activa de TyC")

    try:
        db.execute(
            text(
                """INSERT INTO tos_acceptances (user_id, version_id)
                   VALUES (:uid, :vid)
                   ON CONFLICT (user_id, version_id) DO NOTHING"""
            ),
            {"uid": user_id, "vid": current["id"]},
        )
        db.commit()
        logger.info("TyC aceptado: user=%s version=%s", user_id, current["version"])
    except Exception as e:
        db.rollback()
        logger.error("Error guardando aceptación TyC: %s", e)
        raise HTTPException(status_code=500, detail="Error al guardar aceptación")

    return {"ok": True, "version": current["version"]}
