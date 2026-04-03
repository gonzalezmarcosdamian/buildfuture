from decimal import Decimal
from typing import TypedDict

# ── Bucket classification ──────────────────────────────────────────────────────
# Renta: instrumentos que generan ingreso periódico en ARS (LECAPs, FCIs)
# Capital: instrumentos de crecimiento en USD (CEDEARs, ETFs, crypto)
# Ambos: bonos que pagan cupón (renta) y tienen apreciación de precio (capital)
RENTA_ASSET_TYPES = {"LETRA", "FCI"}
CAPITAL_ASSET_TYPES = {"CEDEAR", "ETF", "CRYPTO"}
AMBOS_ASSET_TYPES = {"BOND", "ON"}   # ON = Obligaciones Negociables, mismo tratamiento 50/50
def split_portfolio_buckets(positions: list) -> dict:
    """
    Separa el portfolio en dos carriles:
    - renta_monthly_usd: ingreso mensual del bucket renta usando el yield real del instrumento
    - renta_total_usd: valor total del bucket renta
    - capital_total_usd: valor total del bucket capital (CEDEAR/ETF/CRYPTO + 50% BOND)
    - crypto_total_usd: subset de capital — solo CRYPTO
    - by_source: desglose {source: {total_usd, capital_usd, renta_usd, crypto_usd}}

    LETRA y FCI: yield directo del ALYC (TNA nominal ARS).
    BOND/ON: split 50/50 — cupón a renta, apreciación a capital.
    CASH → neutral (no computa en ningún bucket).
    CRYPTO → capital únicamente, nunca renta (apreciación especulativa).
    """
    renta_monthly = Decimal("0")
    renta_total = Decimal("0")
    capital_total = Decimal("0")
    cedear_total = Decimal("0")   # capital puro: solo CEDEAR/ETF (sin BOND split)
    crypto_total = Decimal("0")
    by_source: dict[str, dict] = {}

    for p in positions:
        asset_type = getattr(p, "asset_type", "").upper()
        value = p.current_value_usd
        raw_yield = p.annual_yield_pct
        source = getattr(p, "source", "MANUAL") or "MANUAL"

        if source not in by_source:
            by_source[source] = {
                "total_usd": Decimal("0"),
                "capital_usd": Decimal("0"),
                "renta_usd": Decimal("0"),
                "crypto_usd": Decimal("0"),
            }
        by_source[source]["total_usd"] += value

        if asset_type in RENTA_ASSET_TYPES:
            renta_monthly += value * raw_yield / 12
            renta_total += value
            by_source[source]["renta_usd"] += value
        elif asset_type in CAPITAL_ASSET_TYPES:
            capital_total += value
            by_source[source]["capital_usd"] += value
            if asset_type == "CRYPTO":
                crypto_total += value
                by_source[source]["crypto_usd"] += value
            else:
                cedear_total += value   # CEDEAR / ETF puro
        elif asset_type in AMBOS_ASSET_TYPES:
            renta_monthly += value * raw_yield / 12 * Decimal("0.5")
            renta_total += value * Decimal("0.5")
            capital_total += value * Decimal("0.5")
            by_source[source]["renta_usd"] += value * Decimal("0.5")
            by_source[source]["capital_usd"] += value * Decimal("0.5")
        # CASH, OTHER, STOCK → neutral

    return {
        "renta_monthly_usd": renta_monthly,
        "renta_total_usd": renta_total,
        "capital_total_usd": capital_total,
        "cedear_total_usd": cedear_total,
        "crypto_total_usd": crypto_total,
        "by_source": by_source,
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

    Solo activos de renta (LETRA, FCI, BOND, ON) contribuyen a monthly_return_usd.
    CEDEAR, ETF y CRYPTO son capital — su apreciación no es renta mensual predecible.
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

    if portfolio_total == 0:
        return FreedomScore(
            portfolio_total_usd=Decimal("0"),
            monthly_return_usd=Decimal("0"),
            monthly_expenses_usd=monthly_expenses_usd,
            freedom_pct=Decimal("0"),
            annual_return_pct=Decimal("0"),
        )

    # monthly_return solo desde buckets de renta real
    buckets = split_portfolio_buckets(positions)
    monthly_return = buckets["renta_monthly_usd"]

    # annual_return_pct: rendimiento anual del portfolio completo (para proyecciones)
    renta_total = buckets["renta_total_usd"]
    annual_return_pct = (monthly_return * 12 / renta_total) if renta_total > 0 else Decimal("0")

    freedom_pct = monthly_return / monthly_expenses_usd

    return FreedomScore(
        portfolio_total_usd=portfolio_total,
        monthly_return_usd=monthly_return,
        monthly_expenses_usd=monthly_expenses_usd,
        freedom_pct=freedom_pct,
        annual_return_pct=annual_return_pct,
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
