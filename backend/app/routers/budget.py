from decimal import Decimal
from datetime import date, datetime
import httpx
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models import BudgetConfig, BudgetCategory

logger = logging.getLogger("buildfuture.budget")
router = APIRouter(prefix="/budget", tags=["budget"])

# Cache in-process del tipo de cambio MEP (TTL 10 min)
_fx_cache: dict | None = None
_fx_cache_time: datetime | None = None
_FX_TTL = 600  # segundos


@router.get("/fx-rate")
def get_fx_rate():
    """Trae el tipo de cambio MEP. Cacheado 10 min para no llamar APIs externas en cada request."""
    global _fx_cache, _fx_cache_time
    if (
        _fx_cache
        and _fx_cache_time
        and (datetime.utcnow() - _fx_cache_time).total_seconds() < _FX_TTL
    ):
        return _fx_cache

    result = _fetch_fx_rate()
    _fx_cache = result
    _fx_cache_time = datetime.utcnow()
    return result


def _fetch_fx_rate() -> dict:
    # Fuente 1: dolarapi.com
    try:
        resp = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=8)
        resp.raise_for_status()
        data = resp.json()
        value = data.get("venta") or data.get("compra")
        if value:
            logger.info("TC MEP (dolarapi): %s", value)
            return {
                "fx_rate": round(float(value), 2),
                "source": "dolarapi",
                "type": "MEP",
            }
    except Exception as e:
        logger.warning("dolarapi falló: %s", e)

    # Fuente 2: bluelytics blue como proxy
    try:
        resp = httpx.get("https://api.bluelytics.com.ar/v2/latest", timeout=8)
        resp.raise_for_status()
        data = resp.json()
        value = data.get("blue", {}).get("value_sell")
        if value:
            logger.info("TC blue (bluelytics proxy): %s", value)
            return {
                "fx_rate": round(float(value), 2),
                "source": "bluelytics_blue",
                "type": "Blue",
            }
    except Exception as e:
        logger.warning("bluelytics falló: %s", e)

    logger.warning("No se pudo obtener TC online — usando fallback 1431")
    return {"fx_rate": 1431.0, "source": "fallback", "type": "MEP"}


class CategoryIn(BaseModel):
    id: int | None = None
    name: str
    percentage: float
    icon: str = "💰"
    color: str = "#3B82F6"
    is_vacation: bool = False


class BudgetIn(BaseModel):
    income_monthly_ars: float
    fx_rate: float
    categories: list[CategoryIn]


def _serialize(budget: BudgetConfig) -> dict:
    return {
        "id": budget.id,
        "effective_month": budget.effective_month.isoformat(),
        "income_monthly_ars": float(budget.income_monthly_ars),
        "income_monthly_usd": float(budget.income_monthly_usd),
        "total_monthly_ars": float(budget.total_monthly_ars),
        "total_monthly_usd": float(budget.total_monthly_usd),
        "fx_rate": float(budget.fx_rate),
        "savings_monthly_ars": float(budget.savings_monthly_ars),
        "savings_monthly_usd": float(budget.savings_monthly_usd),
        "expenses_pct": float(budget.expenses_pct),
        "vacation_pct": float(budget.vacation_pct),
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "percentage": float(c.percentage),
                "amount_ars": float(c.amount_ars),
                "amount_usd": float(c.amount_usd),
                "icon": c.icon,
                "color": c.color,
                "is_vacation": c.is_vacation,
            }
            for c in budget.categories
        ],
    }


@router.get("/")
def get_budget(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    budget = (
        db.query(BudgetConfig)
        .filter(BudgetConfig.user_id == current_user)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )
    if not budget:
        return None
    return _serialize(budget)


@router.put("/")
def update_budget(
    body: BudgetIn,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    budget = (
        db.query(BudgetConfig)
        .filter(BudgetConfig.user_id == current_user)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )
    if not budget:
        budget = BudgetConfig(
            user_id=current_user,
            effective_month=date.today().replace(day=1),
        )
        db.add(budget)

    budget.income_monthly_ars = Decimal(str(body.income_monthly_ars))
    budget.fx_rate = Decimal(str(body.fx_rate))

    # Recalcular total gastos = sum de categorías no-vacaciones * ingreso
    expense_pct = sum(c.percentage for c in body.categories if not c.is_vacation)
    budget.total_monthly_ars = budget.income_monthly_ars * Decimal(str(expense_pct))

    # Reemplazar categorías
    for c in budget.categories:
        db.delete(c)
    db.flush()

    for cat in body.categories:
        db.add(
            BudgetCategory(
                budget_id=budget.id,
                name=cat.name,
                percentage=Decimal(str(cat.percentage)),
                icon=cat.icon,
                color=cat.color,
                is_vacation=cat.is_vacation,
            )
        )

    db.commit()
    db.refresh(budget)
    return _serialize(budget)
