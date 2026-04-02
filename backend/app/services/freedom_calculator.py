from decimal import Decimal
from typing import TypedDict

# ── Bucket classification ──────────────────────────────────────────────────────
# Renta: instrumentos que generan ingreso periódico en ARS (LECAPs, FCIs)
# Capital: instrumentos de crecimiento en USD (CEDEARs, ETFs, crypto)
# Ambos: bonos que pagan cupón (renta) y tienen apreciación de precio (capital)
RENTA_ASSET_TYPES = {"LETRA", "FCI"}
CAPITAL_ASSET_TYPES = {"CEDEAR", "ETF", "CRYPTO"}
AMBOS_ASSET_TYPES = {"BOND", "ON"}   # ON = Obligaciones Negociables, mismo tratamiento 50/50
MAX_RENTA_USD_YIELD = Decimal("0.15")   # cap para evitar que el 68% nominal ARS infle el monthly return


def split_portfolio_buckets(positions: list) -> dict:
    """
    Separa el portfolio en dos carriles:
    - renta_monthly_usd: ingreso mensual del bucket renta (LETRA/FCI con yield capeado)
    - renta_total_usd: valor total del bucket renta
    - capital_total_usd: valor total del bucket capital (CEDEAR/ETF/CRYPTO + 50% BOND)

    LETRA y FCI tienen yields nominales en ARS (68% para LECAPs).
    Capear a MAX_RENTA_USD_YIELD convierte a rendimiento real aproximado en USD.
    BOND (AL30, GD30): split 50/50 — el cupón va a renta, la apreciación va a capital.
    CASH → neutral (no computa en ningún bucket).
    """
    renta_monthly = Decimal("0")
    renta_total = Decimal("0")
    capital_total = Decimal("0")

    for p in positions:
        asset_type = getattr(p, "asset_type", "").upper()
        value = p.current_value_usd
        raw_yield = p.annual_yield_pct

        if asset_type in RENTA_ASSET_TYPES:
            capped_yield = min(raw_yield, MAX_RENTA_USD_YIELD)
            renta_monthly += value * capped_yield / 12
            renta_total += value
        elif asset_type in CAPITAL_ASSET_TYPES:
            capital_total += value
        elif asset_type in AMBOS_ASSET_TYPES:
            bond_yield = min(raw_yield, Decimal("0.12"))
            renta_monthly += value * bond_yield / 12 * Decimal("0.5")
            capital_total += value * Decimal("0.5")
        # CASH, OTHER → neutral

    return {
        "renta_monthly_usd": renta_monthly,
        "renta_total_usd": renta_total,
        "capital_total_usd": capital_total,
    }


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
