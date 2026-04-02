"""
Seed de datos mock para QA local — 5 personas con distintos estados del producto.
Solo correr cuando MOCK_SEED=true. No llegar a producción.

Personas:
  A — matiasmoron: bonos BOND+ON, metas capital ($90K vs $25K auto + $150K casa)
  B — nuevo:       usuario vacío, sin nada — testea FTU
  C — renta:       LECAP + FCI + presupuesto, renta cubriendo gastos
  D — capital:     solo CEDEAR + CRYPTO, renta $0, capital $120K
  E — mixto:       todo — LETRA/BOND/CEDEAR/ON/FCI/CRYPTO + presupuesto + meta
"""
import os
import random
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models import (
    Position, BudgetConfig, BudgetCategory, FreedomGoal,
    Integration, CapitalGoal, PortfolioSnapshot, InvestmentMonth,
)

if os.getenv("VERCEL") == "1":
    raise RuntimeError("seed_mock no debe correrse en producción")

# UUIDs fijos — prefijo 0000... garantiza que no colisionen con UUIDs v4 de Supabase
USERS = {
    "marcos":      "00000000-0000-0000-0000-000000000001",
    "matiasmoron": "00000000-0000-0000-0000-000000000010",
    "nuevo":       "00000000-0000-0000-0000-000000000020",
    "renta":       "00000000-0000-0000-0000-000000000030",
    "capital":     "00000000-0000-0000-0000-000000000040",
    "mixto":       "00000000-0000-0000-0000-000000000050",
}

TODAY = date.today()
MEP = Decimal("1430")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pos(user_id: str, **kwargs) -> Position:
    defaults = dict(
        source="IOL",
        quantity=Decimal("1"),
        annual_yield_pct=Decimal("0.08"),
        snapshot_date=TODAY,
        is_active=True,
        purchase_fx_rate=MEP,
        ppc_ars=Decimal("0"),
        current_value_ars=Decimal("0"),
        performance_pct=Decimal("0"),
        performance_ars_pct=Decimal("0"),
        cost_basis_usd=Decimal("0"),
    )
    defaults.update(kwargs)
    # Auto-compute current_value_usd if not provided
    if "current_value_usd" not in defaults:
        defaults["current_value_usd"] = (
            defaults["quantity"] * defaults["current_price_usd"]
        )
    if defaults.get("ppc_ars") == Decimal("0") and defaults.get("avg_purchase_price_usd"):
        defaults["ppc_ars"] = defaults["avg_purchase_price_usd"] * MEP
    if defaults.get("current_value_ars") == Decimal("0"):
        defaults["current_value_ars"] = defaults["current_value_usd"] * MEP
    return Position(user_id=user_id, **defaults)


def _budget(user_id: str, income_ars: Decimal, cats: list[dict]) -> tuple[BudgetConfig, list[BudgetCategory]]:
    expenses_pct = sum(Decimal(str(c["percentage"])) for c in cats if not c.get("is_vacation"))
    total_ars = income_ars * expenses_pct
    budget = BudgetConfig(
        user_id=user_id,
        effective_month=date(TODAY.year, TODAY.month, 1),
        income_monthly_ars=income_ars,
        total_monthly_ars=total_ars,
        fx_rate=MEP,
    )
    return budget, [BudgetCategory(percentage=Decimal(str(c["percentage"])), **{k: v for k, v in c.items() if k != "percentage"}) for c in cats]


def _integration(user_id: str, provider: str, connected: bool = False) -> Integration:
    return Integration(
        user_id=user_id,
        provider=provider,
        provider_type="ALYC" if provider in ("IOL", "PPI", "COCOS") else "EXCHANGE",
        is_active=True,
        is_connected=connected,
        encrypted_credentials="mock:mock" if connected else None,
    )


def _snapshots(user_id: str, base_usd: float, days: int = 60, growth_rate: float = 0.003) -> list[PortfolioSnapshot]:
    """Crea una curva de snapshots diaria con ruido realista."""
    snaps = []
    val = base_usd * (1 - growth_rate * days)  # empezar un poco más bajo
    for i in range(days):
        snap_date = TODAY - timedelta(days=days - i)
        # Ruido diario ±0.5%
        noise = random.uniform(-0.005, 0.005)
        val = val * (1 + growth_rate + noise)
        snaps.append(PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=snap_date,
            total_usd=Decimal(str(round(val, 2))),
            monthly_return_usd=Decimal(str(round(val * 0.005, 2))),
            positions_count=3,
            fx_mep=MEP,
            cost_basis_usd=Decimal(str(round(val * 0.85, 2))),
        ))
    return snaps


def _investment_months(user_id: str, months: int = 6, amount_ars: float = 500_000) -> list[InvestmentMonth]:
    result = []
    for i in range(months, 0, -1):
        m = TODAY.replace(day=1) - timedelta(days=30 * i)
        result.append(InvestmentMonth(
            user_id=user_id,
            month=m.replace(day=1),
            amount_ars=Decimal(str(amount_ars)),
            amount_usd=Decimal(str(round(amount_ars / float(MEP), 2))),
            source="IOL",
        ))
    return result


def _already_seeded(db: Session, user_id: str) -> bool:
    return db.query(Position).filter(Position.user_id == user_id).count() > 0


# ── Persona A — matiasmoron ───────────────────────────────────────────────────
# $90K portfolio: bonos soberanos + ON. Sin presupuesto.
# Metas: auto $25K → 100%, casa $150K → 43%

def _seed_a(db: Session) -> None:
    uid = USERS["matiasmoron"]
    if _already_seeded(db, uid):
        print(f"  [skip] matiasmoron ya seeded")
        return

    # Posiciones: ~$90K total
    positions = [
        _pos(uid,
             ticker="AL30", description="Bono Soberano AL30 USD",
             asset_type="BOND", source="IOL",
             quantity=Decimal("80000"), avg_purchase_price_usd=Decimal("0.45"),
             current_price_usd=Decimal("0.51"),
             annual_yield_pct=Decimal("0.09"),
             ppc_ars=Decimal("450"),
             current_value_usd=Decimal("40800")),
        _pos(uid,
             ticker="GD30", description="Bono Soberano GD30 USD",
             asset_type="BOND", source="IOL",
             quantity=Decimal("70000"), avg_purchase_price_usd=Decimal("0.38"),
             current_price_usd=Decimal("0.46"),
             annual_yield_pct=Decimal("0.09"),
             current_value_usd=Decimal("32200")),
        _pos(uid,
             ticker="YCA6O", description="YPF ON USD 2026",
             asset_type="ON", source="IOL",
             quantity=Decimal("17000"), avg_purchase_price_usd=Decimal("0.95"),
             current_price_usd=Decimal("0.98"),
             annual_yield_pct=Decimal("0.09"),
             current_value_usd=Decimal("16660")),
    ]
    # Total: 40800 + 32200 + 16660 = $89660 ≈ $90K ✓

    db.add_all(positions)
    db.flush()

    # Metas de capital (auto $25K → 100%; casa $150K → 43% con $65K restante)
    db.add_all([
        CapitalGoal(user_id=uid, name="Auto", emoji="🚗",
                    target_usd=Decimal("25000"), target_years=2),
        CapitalGoal(user_id=uid, name="Casa", emoji="🏠",
                    target_usd=Decimal("150000"), target_years=7),
    ])

    db.add(_integration(uid, "IOL", connected=True))
    db.add(_integration(uid, "PPI"))

    db.add_all(_snapshots(uid, base_usd=90000, days=60, growth_rate=0.002))
    print(f"  [OK] matiasmoron: $90K | auto 100% | casa 43%")


# ── Persona B — nuevo ─────────────────────────────────────────────────────────
# Usuario vacío: sin posiciones, sin presupuesto, sin metas — testea FTU

def _seed_b(db: Session) -> None:
    uid = USERS["nuevo"]
    if db.query(Integration).filter(Integration.user_id == uid).count() > 0:
        print(f"  [skip] nuevo ya seeded")
        return

    # Solo las integraciones desconectadas (que se crean con el lazy-creation)
    db.add(_integration(uid, "IOL"))
    db.add(_integration(uid, "PPI"))
    print(f"  [OK] nuevo: usuario vacío (FTU)")


# ── Persona C — renta ─────────────────────────────────────────────────────────
# LECAP + FCI + presupuesto. Renta mensual cubre gastos principales.

def _seed_c(db: Session) -> None:
    uid = USERS["renta"]
    if _already_seeded(db, uid):
        print(f"  [skip] renta ya seeded")
        return

    # LECAP: 2M nominales × $0.00071 ≈ $1420 USD → yield 68% → renta ≈ $80/mes (capeado a 15% → $18)
    # FCI: 5000 cuotapartes × $0.00065 ≈ $3250 USD → yield 8% → $22/mes
    positions = [
        _pos(uid,
             ticker="S31O5", description="LECAP S31O5",
             asset_type="LETRA", source="IOL",
             quantity=Decimal("5000000"), avg_purchase_price_usd=Decimal("0.000710"),
             current_price_usd=Decimal("0.000720"),
             annual_yield_pct=Decimal("0.68"),
             ppc_ars=Decimal("0.9500"),
             current_value_usd=Decimal("3600")),
        _pos(uid,
             ticker="IOLMMA", description="IOL Money Market ARS",
             asset_type="FCI", source="IOL",
             quantity=Decimal("8000000"), avg_purchase_price_usd=Decimal("0.000060"),
             current_price_usd=Decimal("0.000065"),
             annual_yield_pct=Decimal("0.08"),
             current_value_usd=Decimal("520")),
        _pos(uid,
             ticker="GGAL", description="Grupo Financiero Galicia CEDEAR",
             asset_type="CEDEAR", source="IOL",
             quantity=Decimal("200"), avg_purchase_price_usd=Decimal("12.00"),
             current_price_usd=Decimal("14.20"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("2840")),
        _pos(uid,
             ticker="CASH_IOL", description="Saldo disponible en pesos · IOL",
             asset_type="CASH", source="IOL",
             quantity=Decimal("1"),
             avg_purchase_price_usd=Decimal("200"),
             current_price_usd=Decimal("200"),
             annual_yield_pct=Decimal("0"),
             current_value_usd=Decimal("200")),
    ]
    db.add_all(positions)
    db.flush()

    # Presupuesto: $3.5M ARS neto (~$2450 USD al MEP)
    income = Decimal("3500000")
    cats = [
        {"name": "Vivienda",     "percentage": 0.23, "icon": "🏠", "color": "#3B82F6", "is_vacation": False},
        {"name": "Alimentación", "percentage": 0.10, "icon": "🛒", "color": "#10B981", "is_vacation": False},
        {"name": "Transporte",   "percentage": 0.05, "icon": "🚗", "color": "#F59E0B", "is_vacation": False},
        {"name": "Servicios",    "percentage": 0.04, "icon": "⚡", "color": "#EF4444", "is_vacation": False},
        {"name": "Ocio",         "percentage": 0.06, "icon": "🎯", "color": "#8B5CF6", "is_vacation": False},
        {"name": "Vacaciones",   "percentage": 0.05, "icon": "🌴", "color": "#0EA5E9", "is_vacation": True},
    ]
    budget, budget_cats = _budget(uid, income, cats)
    db.add(budget)
    db.flush()
    for c in budget_cats:
        c.budget_id = budget.id
    db.add_all(budget_cats)

    db.add(FreedomGoal(user_id=uid, monthly_savings_usd=Decimal("350"),
                       target_annual_return_pct=Decimal("0.08")))
    db.add(_integration(uid, "IOL", connected=True))
    db.add_all(_snapshots(uid, base_usd=7160, days=60, growth_rate=0.001))
    db.add_all(_investment_months(uid, months=6, amount_ars=300_000))
    print(f"  [OK] renta: LECAP+FCI+CEDEAR, presupuesto configurado")


# ── Persona D — capital ───────────────────────────────────────────────────────
# Solo CEDEAR + CRYPTO. Renta $0. Capital $120K. Sin presupuesto.

def _seed_d(db: Session) -> None:
    uid = USERS["capital"]
    if _already_seeded(db, uid):
        print(f"  [skip] capital ya seeded")
        return

    positions = [
        _pos(uid,
             ticker="GGAL", description="Grupo Financiero Galicia CEDEAR",
             asset_type="CEDEAR", source="IOL",
             quantity=Decimal("2000"), avg_purchase_price_usd=Decimal("10.00"),
             current_price_usd=Decimal("14.20"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("28400")),
        _pos(uid,
             ticker="VIST", description="Vista Energy CEDEAR",
             asset_type="CEDEAR", source="IOL",
             quantity=Decimal("500"), avg_purchase_price_usd=Decimal("38.00"),
             current_price_usd=Decimal("52.00"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("26000")),
        _pos(uid,
             ticker="BTC", description="Bitcoin",
             asset_type="CRYPTO", source="NEXO",
             quantity=Decimal("0.50"), avg_purchase_price_usd=Decimal("55000"),
             current_price_usd=Decimal("82000"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("41000")),
        _pos(uid,
             ticker="ETH", description="Ethereum",
             asset_type="CRYPTO", source="NEXO",
             quantity=Decimal("8"), avg_purchase_price_usd=Decimal("2500"),
             current_price_usd=Decimal("3100"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("24800")),
    ]
    # Total: 28400 + 26000 + 41000 + 24800 = $120200 ✓
    db.add_all(positions)

    db.add(_integration(uid, "IOL", connected=True))
    db.add(_integration(uid, "PPI"))
    db.add_all(_snapshots(uid, base_usd=120000, days=60, growth_rate=0.004))
    print(f"  [OK] capital: CEDEAR+CRYPTO $120K, renta $0")


# ── Persona E — mixto avanzado ────────────────────────────────────────────────
# Tiene todo: LETRA+BOND+CEDEAR+ON+FCI+CRYPTO, presupuesto, meta capital.

def _seed_e(db: Session) -> None:
    uid = USERS["mixto"]
    if _already_seeded(db, uid):
        print(f"  [skip] mixto ya seeded")
        return

    positions = [
        _pos(uid,
             ticker="S31O5", description="LECAP S31O5",
             asset_type="LETRA", source="IOL",
             quantity=Decimal("8000000"), avg_purchase_price_usd=Decimal("0.000710"),
             current_price_usd=Decimal("0.000720"),
             annual_yield_pct=Decimal("0.68"),
             current_value_usd=Decimal("5760")),
        _pos(uid,
             ticker="AL30", description="Bono Soberano AL30 USD",
             asset_type="BOND", source="IOL",
             quantity=Decimal("100000"), avg_purchase_price_usd=Decimal("0.43"),
             current_price_usd=Decimal("0.51"),
             annual_yield_pct=Decimal("0.09"),
             current_value_usd=Decimal("51000")),
        _pos(uid,
             ticker="GGAL", description="Grupo Financiero Galicia CEDEAR",
             asset_type="CEDEAR", source="IOL",
             quantity=Decimal("2000"), avg_purchase_price_usd=Decimal("11.00"),
             current_price_usd=Decimal("14.20"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("28400")),
        _pos(uid,
             ticker="YCA6O", description="YPF ON USD 2026",
             asset_type="ON", source="IOL",
             quantity=Decimal("30000"), avg_purchase_price_usd=Decimal("0.92"),
             current_price_usd=Decimal("0.98"),
             annual_yield_pct=Decimal("0.09"),
             current_value_usd=Decimal("29400")),
        _pos(uid,
             ticker="IOLMMA", description="IOL Money Market ARS",
             asset_type="FCI", source="IOL",
             quantity=Decimal("5000000"), avg_purchase_price_usd=Decimal("0.000060"),
             current_price_usd=Decimal("0.000065"),
             annual_yield_pct=Decimal("0.08"),
             current_value_usd=Decimal("325")),
        _pos(uid,
             ticker="BTC", description="Bitcoin",
             asset_type="CRYPTO", source="NEXO",
             quantity=Decimal("0.25"), avg_purchase_price_usd=Decimal("60000"),
             current_price_usd=Decimal("82000"),
             annual_yield_pct=Decimal("0.10"),
             current_value_usd=Decimal("20500")),
    ]
    # Total: 5760 + 51000 + 28400 + 29400 + 325 + 20500 = $135385
    db.add_all(positions)
    db.flush()

    # Presupuesto $7.5M ARS neto
    income = Decimal("7500000")
    cats = [
        {"name": "Vivienda",     "percentage": 0.22, "icon": "🏠", "color": "#3B82F6", "is_vacation": False},
        {"name": "Alimentación", "percentage": 0.09, "icon": "🛒", "color": "#10B981", "is_vacation": False},
        {"name": "Transporte",   "percentage": 0.04, "icon": "🚗", "color": "#F59E0B", "is_vacation": False},
        {"name": "Servicios",    "percentage": 0.04, "icon": "⚡", "color": "#EF4444", "is_vacation": False},
        {"name": "Ocio",         "percentage": 0.07, "icon": "🎯", "color": "#8B5CF6", "is_vacation": False},
        {"name": "Varios",       "percentage": 0.03, "icon": "📦", "color": "#6B7280", "is_vacation": False},
        {"name": "Vacaciones",   "percentage": 0.05, "icon": "🌴", "color": "#0EA5E9", "is_vacation": True},
    ]
    budget, budget_cats = _budget(uid, income, cats)
    db.add(budget)
    db.flush()
    for c in budget_cats:
        c.budget_id = budget.id
    db.add_all(budget_cats)

    db.add_all([
        FreedomGoal(user_id=uid, monthly_savings_usd=Decimal("1500"),
                    target_annual_return_pct=Decimal("0.09")),
        CapitalGoal(user_id=uid, name="Departamento", emoji="🏠",
                    target_usd=Decimal("80000"), target_years=5),
    ])

    db.add(_integration(uid, "IOL", connected=True))
    db.add(_integration(uid, "PPI"))
    db.add(_integration(uid, "NEXO", connected=True))

    db.add_all(_snapshots(uid, base_usd=135000, days=60, growth_rate=0.003))
    db.add_all(_investment_months(uid, months=12, amount_ars=800_000))
    print(f"  [OK] mixto: todo incluido, $135K")


# ── Entry point ───────────────────────────────────────────────────────────────

def seed_mock(db: Session, users: list[str] | str = "all") -> None:
    """
    Seedea las personas de QA. Por defecto seedea todas.
    - users="all"  → las 5 personas
    - users=["matiasmoron", "nuevo"] → solo esas
    """
    print("=== seed_mock: iniciando personas de QA ===")
    seeders = {
        "matiasmoron": _seed_a,
        "nuevo":        _seed_b,
        "renta":        _seed_c,
        "capital":      _seed_d,
        "mixto":        _seed_e,
    }
    targets = list(seeders.keys()) if users == "all" else users
    for alias in targets:
        if alias in seeders:
            seeders[alias](db)
    db.commit()
    print("=== seed_mock: listo ===")
