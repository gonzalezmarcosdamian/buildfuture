from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import BudgetConfig

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/")
def get_budget(db: Session = Depends(get_db)):
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()
    if not budget:
        return None

    return {
        "id": budget.id,
        "effective_month": budget.effective_month.isoformat(),
        "total_monthly_ars": float(budget.total_monthly_ars),
        "total_monthly_usd": float(budget.total_monthly_usd),
        "fx_rate": float(budget.fx_rate),
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "percentage": float(c.percentage),
                "amount_ars": float(c.amount_ars),
                "amount_usd": float(c.amount_usd),
                "icon": c.icon,
                "color": c.color,
            }
            for c in budget.categories
        ],
    }
