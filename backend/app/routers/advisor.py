"""
Invest Advisor — endpoints FastAPI.

GET  /advisor/credits      → créditos usados/disponibles hoy
POST /advisor/query        → consulta con streaming SSE
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.services.advisor import (
    DAILY_CREDIT_LIMIT,
    QUERY_TYPE_LABELS,
    get_credits_used,
    stream_advisor_response,
)

logger = logging.getLogger("buildfuture.advisor")
router = APIRouter(prefix="/advisor", tags=["advisor"])


class AdvisorQuery(BaseModel):
    type: str           # "portfolio" | "technical" | "fundamental" | "macro" | "scenario"
    query: str          # texto libre del usuario
    ticker: str | None = None


@router.get("/credits")
def credits_status(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    used = get_credits_used(db, current_user)
    return {
        "used": used,
        "remaining": max(0, DAILY_CREDIT_LIMIT - used),
        "limit": DAILY_CREDIT_LIMIT,
    }


@router.post("/query")
def advisor_query(
    body: AdvisorQuery,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Consulta al advisor con streaming SSE.
    Cada chunk es un fragmento de texto markdown.
    El cliente debe leer el stream con EventSource o fetch+ReadableStream.

    Formato SSE:
        data: {"chunk": "texto..."}\n\n
        data: {"done": true, "credits_remaining": 3}\n\n
    """
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="La consulta no puede estar vacía.")

    if body.type not in QUERY_TYPE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo inválido. Valores posibles: {list(QUERY_TYPE_LABELS.keys())}",
        )

    def generate():
        try:
            for chunk in stream_advisor_response(
                query_type=body.type,
                user_query=body.query,
                user_id=current_user,
                db=db,
                ticker=body.ticker,
            ):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"

            remaining = max(0, DAILY_CREDIT_LIMIT - get_credits_used(db, current_user))
            yield f"data: {json.dumps({'done': True, 'credits_remaining': remaining})}\n\n"

        except ValueError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        except RuntimeError as e:
            logger.error("advisor stream error: %s", e)
            yield f"data: {json.dumps({'error': 'Error interno. Intentá de nuevo.'})}\n\n"
        except Exception as e:
            logger.error("advisor unexpected error: %s", e)
            yield f"data: {json.dumps({'error': 'Error inesperado.'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
