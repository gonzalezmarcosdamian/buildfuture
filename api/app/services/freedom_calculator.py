from decimal import Decimal
from typing import TypedDict


class FreedomScore(TypedDict):
    portfolio_total_usd: Decimal
    monthly_return_usd: Decimal
    monthly_expenses_usd: Decimal
    freedom_pct: Decimal
    annual_return_pct: Decimal


def calculate_freedom_score(
    positions: list,
    monthly_expenses_usd: Decimal,
) -> FreedomScore:
    """
    Core metric: qué % de los gastos mensuales cubre el rendimiento del portafolio.
    freedom_pct = portfolio_monthly_return / monthly_expenses
    """
    if not positions or monthly_expenses_usd == 0:
        return FreedomScore(
            portfolio_total_usd=Decimal("0"),
            monthly_return_usd=Decimal("0"),
            monthly_expenses_usd=monthly_expenses_usd,
            freedom_pct=Decimal("0"),
            annual_return_pct=Decimal("0"),
        )

    portfolio_total = sum(p.current_value_usd for p in positions)

    # Weighted average annual yield por tipo de activo
    if portfolio_total == 0:
        return FreedomScore(
            portfolio_total_usd=Decimal("0"),
            monthly_return_usd=Decimal("0"),
            monthly_expenses_usd=monthly_expenses_usd,
            freedom_pct=Decimal("0"),
            annual_return_pct=Decimal("0"),
        )

    weighted_yield = sum(
        p.current_value_usd * p.annual_yield_pct for p in positions
    ) / portfolio_total

    monthly_return = portfolio_total * (weighted_yield / 12)
    freedom_pct = monthly_return / monthly_expenses_usd

    return FreedomScore(
        portfolio_total_usd=portfolio_total,
        monthly_return_usd=monthly_return,
        monthly_expenses_usd=monthly_expenses_usd,
        freedom_pct=freedom_pct,
        annual_return_pct=weighted_yield,
    )


def calculate_milestone_projections(
    current_portfolio_usd: Decimal,
    monthly_savings_usd: Decimal,
    monthly_expenses_usd: Decimal,
    annual_return_pct: Decimal,
    milestones: list[Decimal] = [Decimal("0.25"), Decimal("0.50"), Decimal("0.75"), Decimal("1.00")],
) -> list[dict]:
    """
    Para cada milestone, calcula:
    - Capital requerido
    - Meses hasta llegar (búsqueda binaria)
    - Fecha estimada
    """
    from datetime import date, timedelta

    monthly_rate = annual_return_pct / 12
    results = []

    for target_pct in milestones:
        required_capital = (monthly_expenses_usd * target_pct * 12) / annual_return_pct

        if current_portfolio_usd >= required_capital:
            results.append({
                "milestone_pct": float(target_pct),
                "required_capital_usd": float(required_capital),
                "months_to_reach": 0,
                "projected_date": date.today().isoformat(),
                "reached": True,
            })
            continue

        # Búsqueda binaria: cuántos meses para llegar
        lo, hi = 0, 600  # max 50 años
        while lo < hi:
            mid = (lo + hi) // 2
            # Valor futuro: portafolio actual crece + aportes mensuales
            fv = current_portfolio_usd * (1 + monthly_rate) ** mid
            fv += monthly_savings_usd * (((1 + monthly_rate) ** mid - 1) / monthly_rate) if monthly_rate > 0 else monthly_savings_usd * mid

            if fv >= required_capital:
                hi = mid
            else:
                lo = mid + 1

        projected_date = date.today() + timedelta(days=lo * 30)

        results.append({
            "milestone_pct": float(target_pct),
            "required_capital_usd": float(required_capital),
            "months_to_reach": lo,
            "projected_date": projected_date.isoformat(),
            "reached": False,
        })

    return results
