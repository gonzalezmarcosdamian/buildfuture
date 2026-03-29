from decimal import Decimal
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Position, BudgetConfig, FreedomGoal
from app.services.freedom_calculator import calculate_freedom_score, calculate_milestone_projections

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/")
def get_portfolio(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.is_active == True).all()
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()
    monthly_expenses_usd = budget.total_monthly_usd if budget else Decimal("2000")

    score = calculate_freedom_score(positions, monthly_expenses_usd)

    return {
        "positions": [
            {
                "id": p.id,
                "ticker": p.ticker,
                "description": p.description,
                "asset_type": p.asset_type,
                "source": p.source,
                "quantity": float(p.quantity),
                "avg_purchase_price_usd": float(p.avg_purchase_price_usd),
                "current_price_usd": float(p.current_price_usd),
                "current_value_usd": float(p.current_value_usd),
                "performance_pct": float(p.performance_pct),
                "annual_yield_pct": float(p.annual_yield_pct),
            }
            for p in positions
        ],
        "summary": {
            "total_usd": float(score["portfolio_total_usd"]),
            "monthly_return_usd": float(score["monthly_return_usd"]),
            "freedom_pct": float(score["freedom_pct"]),
            "annual_return_pct": float(score["annual_return_pct"]),
        },
    }


@router.get("/freedom-score")
def get_freedom_score(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.is_active == True).all()
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()
    goal = db.query(FreedomGoal).order_by(FreedomGoal.id.desc()).first()

    monthly_expenses_usd = budget.total_monthly_usd if budget else Decimal("2000")
    monthly_savings_usd = goal.monthly_savings_usd if goal else Decimal("1250")
    annual_return_pct = goal.target_annual_return_pct if goal else Decimal("0.08")

    score = calculate_freedom_score(positions, monthly_expenses_usd)

    milestones = calculate_milestone_projections(
        current_portfolio_usd=score["portfolio_total_usd"],
        monthly_savings_usd=monthly_savings_usd,
        monthly_expenses_usd=monthly_expenses_usd,
        annual_return_pct=score["annual_return_pct"] if score["annual_return_pct"] > 0 else annual_return_pct,
    )

    return {
        "freedom_pct": float(score["freedom_pct"]),
        "portfolio_total_usd": float(score["portfolio_total_usd"]),
        "monthly_return_usd": float(score["monthly_return_usd"]),
        "monthly_expenses_usd": float(score["monthly_expenses_usd"]),
        "milestones": milestones,
    }
