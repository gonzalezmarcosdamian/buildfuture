from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Position, BudgetConfig, BudgetCategory, FreedomGoal, InvestmentMonth, PortfolioSnapshot
from app.services.freedom_calculator import calculate_freedom_score, calculate_milestone_projections
from app.services.ai_recommendations import get_ai_recommendations
from app.services.market_data import fetch_market_snapshot
from app.services.smart_recommendations import get_smart_recommendations
from app.services.expert_committee import get_committee_recommendations, UNIVERSE

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
                "cost_basis_usd": float(p.cost_basis_usd),
                "performance_pct": float(p.performance_pct),
                "purchase_fx_rate": float(p.purchase_fx_rate),
                "ppc_ars": float(p.ppc_ars),
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

    return get_committee_recommendations(
        capital_ars=capital_ars,
        risk_profile=risk_profile,
        freedom_pct=freedom_pct,
        monthly_savings_usd=monthly_savings_usd,
        current_tickers=current_tickers,
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
    # Fuente primaria: tabla investment_months (operaciones reales de IOL).
    # Fallback: proxy por snapshot_date si no hay datos reales aún.
    real_months = db.query(InvestmentMonth.month).all()
    if real_months:
        invested_months = {row.month.replace(day=1) for row in real_months}
    else:
        invested_months = {p.snapshot_date.replace(day=1) for p in positions}

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
            "invested": month_date in invested_months,
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


_MONTH_NAMES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]


def _normalize_date(s_date) -> date:
    """Normaliza a datetime.date aunque SQLite devuelva str."""
    if hasattr(s_date, "year"):
        return s_date
    return date.fromisoformat(str(s_date))


@router.get("/history")
def get_portfolio_history(
    period: str = Query(default="daily"),  # daily | monthly | annual
    db: Session = Depends(get_db),
):
    snapshots = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )

    if not snapshots:
        return {"period": period, "points": [], "has_data": False}

    grouped: dict = {}
    for s in snapshots:
        d = _normalize_date(s.snapshot_date)
        if period == "daily":
            key = d.isoformat()
            label = f"{d.day} {_MONTH_NAMES[d.month - 1]}"
        elif period == "monthly":
            key = f"{d.year}-{d.month:02d}"
            label = f"{_MONTH_NAMES[d.month - 1]} {str(d.year)[2:]}"
        else:  # annual
            key = str(d.year)
            label = key

        grouped[key] = {"label": label, "date_iso": d.isoformat(), "snapshot": s}

    points_raw = list(grouped.values())
    points = []
    for i, item in enumerate(points_raw):
        s = item["snapshot"]
        total = float(s.total_usd)
        prev_total = float(points_raw[i - 1]["snapshot"].total_usd) if i > 0 else total
        points.append({
            "label": item["label"],
            "date": item["date_iso"],
            "total_usd": round(total, 2),
            "monthly_return_usd": round(float(s.monthly_return_usd), 2),
            "fx_mep": round(float(s.fx_mep), 2) if s.fx_mep else 0,
            "delta_usd": round(total - prev_total, 2),
        })

    return {"period": period, "points": points, "has_data": len(points) >= 2}


@router.get("/next-goal")
def get_next_goal(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.is_active == True).all()
    budget = db.query(BudgetConfig).order_by(BudgetConfig.effective_month.desc()).first()
    if not budget:
        return None

    score = calculate_freedom_score(positions, budget.total_monthly_usd)
    monthly_return = float(score["monthly_return_usd"])
    mep = float(budget.fx_rate)
    savings_ars = float(budget.savings_monthly_ars)
    savings_usd = savings_ars / mep if mep > 0 else 0

    # Encontrar la próxima categoría a desbloquear (la más barata aún no cubierta)
    cats = sorted(budget.categories, key=lambda c: float(c.amount_usd))
    remaining = monthly_return
    next_cat = None
    for c in cats:
        cat_usd = float(c.amount_usd)
        if cat_usd <= 0:
            continue
        if remaining >= cat_usd:
            remaining -= cat_usd
        else:
            missing_return_usd = round(cat_usd - max(remaining, 0), 2)
            next_cat = {
                "name": c.name,
                "icon": c.icon,
                "target_monthly_usd": round(cat_usd, 2),
                "current_monthly_usd": round(max(monthly_return, 0), 2),
                "missing_monthly_usd": missing_return_usd,
            }
            remaining = 0
            break

    if not next_cat:
        return {"all_unlocked": True}

    # Instrumento top del comité para calcular proyección
    top_instrument = next((i for i in UNIVERSE if i.asset_type == "LETRA"), UNIVERSE[0])
    annual_yield = top_instrument.base_yield_pct

    # Capital necesario para generar missing_return_usd/mes
    # missing_return = capital × annual_yield / 12  →  capital = missing_return × 12 / annual_yield
    capital_needed_usd = (next_cat["missing_monthly_usd"] * 12 / annual_yield) if annual_yield > 0 else 0
    capital_needed_ars = round(capital_needed_usd * mep)

    # Meses de ahorro necesarios
    months_to_unlock = round(capital_needed_usd / savings_usd) if savings_usd > 0 else None

    return {
        "all_unlocked": False,
        "next_category": next_cat,
        "capital_needed_usd": round(capital_needed_usd, 2),
        "capital_needed_ars": capital_needed_ars,
        "savings_monthly_usd": round(savings_usd, 2),
        "savings_monthly_ars": round(savings_ars),
        "months_to_unlock": months_to_unlock,
        "recommended_ticker": top_instrument.ticker,
        "recommended_name": top_instrument.name,
        "recommended_yield_pct": top_instrument.base_yield_pct,
        "mep": round(mep, 2),
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
