from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Integration

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/")
def get_integrations(db: Session = Depends(get_db)):
    integrations = db.query(Integration).all()
    return [
        {
            "id": i.id,
            "provider": i.provider,
            "provider_type": i.provider_type,
            "is_active": i.is_active,
            "is_connected": i.is_connected,
            "last_synced_at": i.last_synced_at.isoformat() if i.last_synced_at else None,
            "last_error": i.last_error,
        }
        for i in integrations
    ]
