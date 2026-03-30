from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Position, BudgetConfig, BudgetCategory, FreedomGoal
from app.services.freedom_calculator import calculate_freedom_score, calculate_milestone_projections
from app.services.ai_recommendations import get_ai_recommendations
from app.services.market_data import fetch_market_snapshot
from app.services.smart_recommendations import get_smart_recommendations

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


@router.get("/recommendations")
def get_portfolio_recommendations(
    capital_ars: float = Query(default=500000),
    risk_profile: str = Query(default="moderado"),
    use_ai: bool = Query(default=False),
    force_refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    positions = db.query(Position).filter(Position.is_active == True).all()
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()
    score = calculate_freedom_score(positions, budget.total_monthly_usd if budget else Decimal("2000"))

    current_tickers = [p.ticker for p in positions]
    monthly_savings_usd = float(budget.savings_monthly_usd) if budget else 1250.0
    freedom_pct = float(score["freedom_pct"])

    if use_ai:
        market = fetch_market_snapshot()
        return get_ai_recommendations(
            capital_ars=capital_ars,
            fx_rate=market.mep_usd,
            freedom_pct=freedom_pct,
            monthly_savings_usd=monthly_savings_usd,
            current_tickers=current_tickers,
            market=market,
            force_refresh=force_refresh,
        )

    return get_smart_recommendations(
        capital_ars=capital_ars,
        freedom_pct=freedom_pct,
        monthly_savings_usd=monthly_savings_usd,
        current_tickers=current_tickers,
        risk_profile=risk_profile,
    )


@router.get("/gamification")
def get_gamification(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.is_active == True).all()
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()

    # ── 1. ¿Qué paga tu portafolio? ──────────────────────────────────────────
    monthly_return_usd = float(sum(
        p.current_value_usd * p.annual_yield_pct / 12 for p in positions
    ))

    portfolio_covers = []
    if budget and budget.income_monthly_ars > 0:
        cats = sorted(budget.categories, key=lambda c: float(c.amount_usd))
        remaining = monthly_return_usd
        for c in cats:
            cat_usd = float(c.amount_usd)
            if cat_usd <= 0:
                continue
            if remaining >= cat_usd:
                status = "covered"
                covered_pct = 1.0
                remaining -= cat_usd
            elif remaining > 0:
                status = "partial"
                covered_pct = round(remaining / cat_usd, 2)
                remaining = 0.0
            else:
                status = "pending"
                covered_pct = 0.0
            portfolio_covers.append({
                "name": c.name,
                "icon": c.icon,
                "amount_usd": round(cat_usd, 1),
                "status": status,
                "covered_pct": covered_pct,
            })

    # ── 2. Racha mensual ─────────────────────────────────────────────────────
    # Proxy: mes con al menos una posición activa cuyo snapshot_date caiga en ese mes
    snapshot_months = set()
    for p in positions:
        snapshot_months.add(p.snapshot_date.replace(day=1))

    today = date.today()
    calendar = []
    for i in range(11, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_date = date(y, m, 1)
        calendar.append({
            "month": month_date.isoformat(),
            "invested": month_date in snapshot_months,
        })

    current_streak = 0
    for entry in reversed(calendar):
        if entry["invested"]:
            current_streak += 1
        else:
            break

    longest_streak, cur = 0, 0
    for entry in calendar:
        if entry["invested"]:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    return {
        "monthly_return_usd": round(monthly_return_usd, 2),
        "portfolio_covers": portfolio_covers,
        "streak": {
            "current": current_streak,
            "longest": longest_streak,
            "calendar": calendar,
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
