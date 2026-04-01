"""
Gestión de posiciones manuales (CRYPTO, FCI, ETF/acciones, OTRO).
Complementa las posiciones sincronizadas desde IOL.
"""
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models import Position, BudgetConfig
from app.services import crypto_prices, fci_prices, external_prices

logger = logging.getLogger("buildfuture.positions")

router = APIRouter(prefix="/positions", tags=["positions"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ManualPositionCreate(BaseModel):
    asset_type: str          # CRYPTO | FCI | ETF | OTRO
    ticker: str              # símbolo o nombre corto (ej: BTC, SPY, CocosDolaresPlus)
    description: str         # nombre legible
    quantity: float
    ppc_ars: float           # precio promedio de compra en ARS (0 si es en USD)
    purchase_price_usd: float  # precio promedio de compra en USD
    purchase_fx_rate: float  # MEP al momento de compra (0 si la compra fue en USD)
    purchase_date: Optional[str] = None  # ISO date de la compra
    # Campos específicos por tipo
    external_id: Optional[str] = None       # CoinGecko ID | ticker Yahoo
    fci_categoria: Optional[str] = None     # para FCI: categoria ArgentinaDatos
    manual_yield_pct: Optional[float] = None  # yield anual manual para OTRO


class ManualPositionUpdate(BaseModel):
    quantity: Optional[float] = None
    purchase_price_usd: Optional[float] = None
    ppc_ars: Optional[float] = None
    purchase_fx_rate: Optional[float] = None
    manual_yield_pct: Optional[float] = None
    description: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_live_price_and_yield(
    asset_type: str,
    external_id: str | None,
    fci_categoria: str | None,
    manual_yield_pct: float | None,
    purchase_price_usd: float,
) -> tuple[float, float]:
    """
    Retorna (current_price_usd, annual_yield_pct) para la posición.
    Fallback al precio de compra si no se puede obtener precio live.
    """
    price = purchase_price_usd
    yield_pct = manual_yield_pct or 0.0

    if asset_type == "CRYPTO" and external_id:
        live = crypto_prices.get_price_usd(external_id)
        if live:
            price = live
        yield_pct = crypto_prices.get_yield_30d(external_id)

    elif asset_type == "FCI" and external_id and fci_categoria:
        yield_pct = fci_prices.get_yield_30d(external_id, fci_categoria)
        vcp = fci_prices.get_vcp(external_id, fci_categoria)
        if vcp:
            # Convertir VCP (ARS) a USD usando MEP actual
            try:
                import httpx as _httpx
                r = _httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=5)
                mep = float(r.json().get("venta", 1430)) if r.status_code == 200 else 1430.0
            except Exception:
                mep = 1430.0
            price = vcp / mep if mep > 0 else purchase_price_usd

    elif asset_type in ("ETF", "CEDEAR") and external_id:
        live = external_prices.get_price_usd(external_id)
        if live:
            price = live
        yield_pct = external_prices.get_yield_30d(external_id)

    return price, yield_pct


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/search/crypto")
def search_crypto(q: str = Query(min_length=1)):
    """Busca criptomonedas en CoinGecko por nombre o símbolo."""
    return {"results": crypto_prices.search_coins(q)}


@router.get("/search/fci")
def search_fci(q: str = Query(default="", min_length=0)):
    """Busca fondos de inversión en ArgentinaDatos por nombre. Sin q devuelve todos."""
    return {"results": fci_prices.search_fci(q)}


@router.get("/search/etf")
def search_etf(ticker: str = Query(min_length=1)):
    """Valida y retorna info de un ticker en Yahoo Finance (ETF, acción, índice)."""
    info = external_prices.validate_ticker(ticker)
    if not info:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' no encontrado en Yahoo Finance")
    return info


@router.post("/manual")
def create_manual_position(
    body: ManualPositionCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Crea una posición manual (CRYPTO, FCI, ETF o activo genérico)."""
    # Obtener precio live y yield estimado
    price_usd, yield_pct = _get_live_price_and_yield(
        asset_type=body.asset_type,
        external_id=body.external_id,
        fci_categoria=body.fci_categoria,
        manual_yield_pct=body.manual_yield_pct,
        purchase_price_usd=body.purchase_price_usd,
    )

    # Para FCI: el precio de compra en ARS / MEP de compra = costo base USD
    ppc_ars = Decimal(str(body.ppc_ars)) if body.ppc_ars else Decimal("0")
    purchase_fx = Decimal(str(body.purchase_fx_rate)) if body.purchase_fx_rate else Decimal("0")

    pos = Position(
        user_id=user_id,
        ticker=body.ticker.upper()[:20],
        description=body.description[:100],
        asset_type=body.asset_type,
        source="MANUAL",
        quantity=Decimal(str(body.quantity)),
        avg_purchase_price_usd=Decimal(str(body.purchase_price_usd)),
        current_price_usd=Decimal(str(price_usd)),
        annual_yield_pct=Decimal(str(yield_pct)),
        snapshot_date=date.today(),
        is_active=True,
        ppc_ars=ppc_ars,
        purchase_fx_rate=purchase_fx,
        external_id=body.external_id,
        fci_categoria=body.fci_categoria,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    logger.info("Posición manual creada: %s %s (user %s)", body.asset_type, body.ticker, user_id)
    return {
        "id": pos.id,
        "ticker": pos.ticker,
        "description": pos.description,
        "asset_type": pos.asset_type,
        "quantity": float(pos.quantity),
        "current_price_usd": float(pos.current_price_usd),
        "current_value_usd": float(pos.current_value_usd),
        "cost_basis_usd": float(pos.cost_basis_usd),
        "annual_yield_pct": float(pos.annual_yield_pct),
    }


@router.patch("/manual/{position_id}")
def update_manual_position(
    position_id: int,
    body: ManualPositionUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Actualiza cantidad, precio de compra o yield de una posición manual."""
    pos = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == user_id,
        Position.source == "MANUAL",
        Position.is_active == True,
    ).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Posición no encontrada")

    if body.quantity is not None:
        pos.quantity = Decimal(str(body.quantity))
    if body.purchase_price_usd is not None:
        pos.avg_purchase_price_usd = Decimal(str(body.purchase_price_usd))
    if body.ppc_ars is not None:
        pos.ppc_ars = Decimal(str(body.ppc_ars))
    if body.purchase_fx_rate is not None:
        pos.purchase_fx_rate = Decimal(str(body.purchase_fx_rate))
    if body.manual_yield_pct is not None:
        pos.annual_yield_pct = Decimal(str(body.manual_yield_pct))
    if body.description is not None:
        pos.description = body.description[:100]
    pos.snapshot_date = date.today()

    db.commit()
    db.refresh(pos)
    return {
        "id": pos.id,
        "ticker": pos.ticker,
        "quantity": float(pos.quantity),
        "current_value_usd": float(pos.current_value_usd),
        "cost_basis_usd": float(pos.cost_basis_usd),
    }


@router.delete("/manual/{position_id}")
def delete_manual_position(
    position_id: int,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Desactiva (soft delete) una posición manual."""
    pos = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == user_id,
        Position.source == "MANUAL",
    ).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Posición no encontrada")
    pos.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/manual/{position_id}/refresh-price")
def refresh_manual_price(
    position_id: int,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Fuerza actualización de precio y yield para una posición manual."""
    pos = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == user_id,
        Position.source == "MANUAL",
        Position.is_active == True,
    ).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Posición no encontrada")

    price_usd, yield_pct = _get_live_price_and_yield(
        asset_type=pos.asset_type,
        external_id=pos.external_id,
        fci_categoria=pos.fci_categoria,
        manual_yield_pct=None,
        purchase_price_usd=float(pos.avg_purchase_price_usd),
    )
    pos.current_price_usd = Decimal(str(price_usd))
    pos.annual_yield_pct = Decimal(str(yield_pct))
    pos.snapshot_date = date.today()
    db.commit()
    return {
        "current_price_usd": float(pos.current_price_usd),
        "annual_yield_pct": float(pos.annual_yield_pct),
        "current_value_usd": float(pos.current_value_usd),
    }
