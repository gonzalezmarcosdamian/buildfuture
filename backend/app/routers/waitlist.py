"""
Waitlist pública — sin autenticación.
POST /waitlist — registra email interesado en BuildFuture.
Rate limit simple: 3 requests por IP por hora vía cabecera X-Forwarded-For.
"""

import logging
import re
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import WaitlistEntry

logger = logging.getLogger("buildfuture.waitlist")
router = APIRouter(prefix="/waitlist", tags=["waitlist"])

# Rate limit en memoria — se resetea con el proceso (suficiente para MVP)
_ip_hits: dict[str, list[datetime]] = defaultdict(list)
_RATE_LIMIT = 3
_RATE_WINDOW = timedelta(hours=1)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistRequest(BaseModel):
    email: str
    source: str = "landing"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email inválido")
        if len(v) > 254:
            raise ValueError("Email demasiado largo")
        return v


def _check_rate_limit(ip: str) -> None:
    now = datetime.utcnow()
    hits = [t for t in _ip_hits[ip] if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT:
        raise HTTPException(
            status_code=429, detail="Demasiados intentos. Esperá un momento."
        )
    hits.append(now)
    _ip_hits[ip] = hits


@router.post("/")
def register_waitlist(
    req: WaitlistRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    forwarded = request.headers.get("X-Forwarded-For")
    fallback = request.client.host if request.client else "unknown"
    ip = forwarded.split(",")[0].strip() if forwarded else fallback
    _check_rate_limit(ip)

    entry = WaitlistEntry(
        email=req.email,
        source=req.source,
        created_at=datetime.utcnow(),
    )
    try:
        db.add(entry)
        db.commit()
        logger.info("Waitlist: nuevo registro %s (source=%s)", req.email, req.source)
    except IntegrityError:
        db.rollback()
        # Email ya registrado — respondemos OK igualmente (no revelar existencia)
        logger.info("Waitlist: email duplicado %s (silenciado)", req.email)

    return {"ok": True, "message": "¡Te anotamos! Te avisamos cuando haya novedades."}


@router.get("/count")
def waitlist_count(db: Session = Depends(get_db)):
    """Público — devuelve conteo para mostrar en landing."""
    count = db.query(WaitlistEntry).count()
    return {"count": count}
