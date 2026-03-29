"""
Seed data — portafolio mock de Marcos para desarrollo local.
Refleja su perfil financiero real con posiciones ficticias pero realistas.
"""
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import Position, BudgetConfig, BudgetCategory, FreedomGoal, Integration


def seed(db: Session) -> None:
    if db.query(Position).count() > 0:
        return  # Ya está seeded

    today = date.today()

    # ── Posiciones mock (portafolio inicial realista para AR) ──────────────
    positions = [
        Position(
            ticker="GGAL",
            description="Grupo Financiero Galicia CEDEAR",
            asset_type="CEDEAR",
            source="IOL",
            quantity=Decimal("200"),
            avg_purchase_price_usd=Decimal("12.50"),
            current_price_usd=Decimal("14.20"),
            annual_yield_pct=Decimal("0.12"),  # CEDEARs: mix de apreciación + dividendo
            snapshot_date=today,
        ),
        Position(
            ticker="MSFT",
            description="Microsoft CEDEAR",
            asset_type="CEDEAR",
            source="IOL",
            quantity=Decimal("15"),
            avg_purchase_price_usd=Decimal("380.00"),
            current_price_usd=Decimal("415.00"),
            annual_yield_pct=Decimal("0.10"),
            snapshot_date=today,
        ),
        Position(
            ticker="AL30",
            description="Bono Soberano AL30 USD",
            asset_type="BOND",
            source="IOL",
            quantity=Decimal("100"),
            avg_purchase_price_usd=Decimal("45.00"),
            current_price_usd=Decimal("51.00"),
            annual_yield_pct=Decimal("0.09"),  # cupón + apreciación
            snapshot_date=today,
        ),
        Position(
            ticker="LECAP",
            description="Letra Capitalizable Tesoro",
            asset_type="LETRA",
            source="IOL",
            quantity=Decimal("500000"),
            avg_purchase_price_usd=Decimal("0.00075"),
            current_price_usd=Decimal("0.00080"),
            annual_yield_pct=Decimal("0.40"),  # TNA en ARS (~40%) convertida
            snapshot_date=today,
        ),
        Position(
            ticker="BTC",
            description="Bitcoin",
            asset_type="CRYPTO",
            source="NEXO",
            quantity=Decimal("0.08"),
            avg_purchase_price_usd=Decimal("42000.00"),
            current_price_usd=Decimal("67000.00"),
            annual_yield_pct=Decimal("0.04"),  # yield de Nexo ~4%
            snapshot_date=today,
        ),
        Position(
            ticker="USDT",
            description="Tether USD (Nexo)",
            asset_type="CRYPTO",
            source="NEXO",
            quantity=Decimal("2000"),
            avg_purchase_price_usd=Decimal("1.00"),
            current_price_usd=Decimal("1.00"),
            annual_yield_pct=Decimal("0.10"),  # yield stablecoin Nexo ~10%
            snapshot_date=today,
        ),
        Position(
            ticker="CASH_ARS",
            description="Efectivo ARS",
            asset_type="CASH",
            source="IOL",
            quantity=Decimal("1"),
            avg_purchase_price_usd=Decimal("1500.00"),
            current_price_usd=Decimal("1500.00"),
            annual_yield_pct=Decimal("0.00"),  # cash no rinde
            snapshot_date=today,
        ),
    ]
    db.add_all(positions)

    # ── Presupuesto mensual (basado en el perfil real de Marcos) ──────────
    budget = BudgetConfig(
        effective_month=date(today.year, today.month, 1),
        total_monthly_ars=Decimal("2640000"),  # gastos totales estimados
        fx_rate=Decimal("1320"),               # tipo de cambio MEP aprox
        notes="Presupuesto base 2026 — actualizar con tipo de cambio mensual",
    )
    db.add(budget)
    db.flush()  # para tener el id

    categories = [
        BudgetCategory(budget_id=budget.id, name="Vivienda",      percentage=Decimal("0.511"), icon="🏠", color="#3B82F6"),
        BudgetCategory(budget_id=budget.id, name="Alimentación",  percentage=Decimal("0.170"), icon="🛒", color="#10B981"),
        BudgetCategory(budget_id=budget.id, name="Transporte",    percentage=Decimal("0.057"), icon="🚗", color="#F59E0B"),
        BudgetCategory(budget_id=budget.id, name="Ocio",          percentage=Decimal("0.114"), icon="🎯", color="#8B5CF6"),
        BudgetCategory(budget_id=budget.id, name="Servicios",     percentage=Decimal("0.076"), icon="⚡", color="#EF4444"),
        BudgetCategory(budget_id=budget.id, name="Varios",        percentage=Decimal("0.072"), icon="📦", color="#6B7280"),
    ]
    db.add_all(categories)

    # ── Objetivo de libertad financiera ───────────────────────────────────
    goal = FreedomGoal(
        monthly_savings_usd=Decimal("1250"),
        target_annual_return_pct=Decimal("0.08"),
    )
    db.add(goal)

    # ── Integraciones (vacías — el usuario conecta sus cuentas desde la UI) ─
    integrations = [
        Integration(provider="IOL",   provider_type="ALYC",   is_active=True,  is_connected=False),
        Integration(provider="NEXO",  provider_type="CRYPTO", is_active=True,  is_connected=False),
        Integration(provider="BITSO", provider_type="CRYPTO", is_active=True,  is_connected=False),
    ]
    db.add_all(integrations)

    db.commit()
    print("Seed completado - portafolio mock de Marcos listo")
