from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Integration, Position
from app.services.iol_client import IOLClient, IOLAuthError

router = APIRouter(prefix="/integrations", tags=["integrations"])


class ConnectRequest(BaseModel):
    username: str
    password: str


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


@router.post("/iol/connect")
def connect_iol(body: ConnectRequest, db: Session = Depends(get_db)):
    """
    Testea credenciales IOL, guarda en DB (plain text para dev local),
    y hace el primer sync del portafolio.
    """
    # 1. Testear credenciales
    client = IOLClient(body.username, body.password)
    try:
        client.authenticate()
    except IOLAuthError as e:
        raise HTTPException(status_code=401, detail=f"Credenciales incorrectas: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error conectando con IOL: {str(e)}")

    # 2. Guardar credenciales (dev: plain text — prod: AES-256)
    integration = db.query(Integration).filter(Integration.provider == "IOL").first()
    if not integration:
        integration = Integration(provider="IOL", provider_type="ALYC")
        db.add(integration)

    # Guardamos como "usuario:password" — solo para dev local
    integration.encrypted_credentials = f"{body.username}:{body.password}"
    integration.is_connected = True
    integration.last_error = ""
    db.flush()

    # 3. Sincronizar portafolio real
    result = _sync_iol(client, db)

    integration.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "connected": True,
        "positions_synced": result["positions_synced"],
        "message": f"Conectado. {result['positions_synced']} posiciones sincronizadas.",
    }


@router.post("/iol/sync")
def sync_iol(db: Session = Depends(get_db)):
    """Re-sincroniza el portafolio IOL con las credenciales guardadas."""
    integration = db.query(Integration).filter(Integration.provider == "IOL").first()
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="IOL no está conectado")

    try:
        creds = integration.encrypted_credentials.split(":", 1)
        client = IOLClient(creds[0], creds[1])
        result = _sync_iol(client, db)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        return {"positions_synced": result["positions_synced"]}
    except Exception as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


def _sync_iol(client: IOLClient, db: Session) -> dict:
    """Trae posiciones de IOL y las upserta en la DB."""
    positions = client.get_portfolio()

    # Desactivar posiciones IOL anteriores
    db.query(Position).filter(
        Position.source == "IOL",
        Position.is_active == True
    ).update({"is_active": False})

    today = date.today()
    synced = 0

    for p in positions:
        if p.quantity <= 0:
            continue

        pos = Position(
            ticker=p.ticker,
            description=p.description,
            asset_type=p.asset_type,
            source="IOL",
            quantity=p.quantity,
            avg_purchase_price_usd=p.avg_price_usd,
            current_price_usd=p.current_price_usd,
            annual_yield_pct=p.annual_yield_pct,
            snapshot_date=today,
            is_active=True,
        )
        db.add(pos)
        synced += 1

    db.flush()
    return {"positions_synced": synced}
