import logging
import threading
from decimal import Decimal
from datetime import date, datetime, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException

logger = logging.getLogger("buildfuture.portfolio")
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.auth import get_current_user
from pydantic import BaseModel
from app.models import Position, BudgetConfig, BudgetCategory, FreedomGoal, InvestmentMonth, PortfolioSnapshot, CapitalGoal
from app.services.freedom_calculator import calculate_freedom_score, calculate_milestone_projections, split_portfolio_buckets
from app.services.ai_recommendations import get_ai_recommendations
from app.services.market_data import fetch_market_snapshot
from app.services.smart_recommendations import get_smart_recommendations
from app.services.expert_committee import get_committee_recommendations, get_sections_recommendations, UNIVERSE

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# Auto-sync solo si los datos tienen más de 4 horas — para el sync en tiempo real usar el botón
AUTO_SYNC_MIN_AGE_MINUTES = 240

# ── Cache in-process de freedom score (TTL 2 min por usuario) ─────────────────
_score_cache: dict[str, tuple[dict, datetime]] = {}
_score_lock = threading.Lock()
_SCORE_TTL = 120  # segundos

def _get_freedom_score(user_id: str, positions: list, monthly_expenses_usd: Decimal) -> dict:
    """Calcula o devuelve desde cache el freedom score del usuario."""
    with _score_lock:
        cached = _score_cache.get(user_id)
        if cached and (datetime.utcnow() - cached[1]).total_seconds() < _SCORE_TTL:
            return cached[0]
    score = calculate_freedom_score(positions, monthly_expenses_usd)
    with _score_lock:
        _score_cache[user_id] = (score, datetime.utcnow())
    return score

def _invalidate_score_cache(user_id: str) -> None:
    with _score_lock:
        _score_cache.pop(user_id, None)

def _query_budget(db: Session, user_id: str) -> BudgetConfig | None:
    """Carga BudgetConfig con categorías eager para evitar lazy queries."""
    return (
        db.query(BudgetConfig)
        .options(selectinload(BudgetConfig.categories))
        .filter(BudgetConfig.user_id == user_id)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )


def _auto_sync_iol(user_id: str) -> None:
    """
    Sincroniza IOL en background si los datos tienen más de AUTO_SYNC_MIN_AGE_MINUTES.
    Usa lock atómico (UPDATE ... WHERE last_synced_at < threshold) para evitar
    que múltiples requests concurrentes dupliquen posiciones.
    """
    from app.database import SessionLocal
    from app.models import Integration
    from app.routers.integrations import _sync_iol
    from app.services.iol_client import IOLClient
    from sqlalchemy import update as sa_update, or_

    db = SessionLocal()
    try:
        threshold = datetime.utcnow() - timedelta(minutes=AUTO_SYNC_MIN_AGE_MINUTES)
        now = datetime.utcnow()

        # Lock atómico: el UPDATE solo aplica si last_synced_at sigue siendo viejo.
        # Si otro proceso ya tomó el lock, rowcount=0 y salimos sin sincronizar.
        result = db.execute(
            sa_update(Integration)
            .where(
                Integration.provider == "IOL",
                Integration.user_id == user_id,
                Integration.is_connected == True,
                or_(Integration.last_synced_at == None, Integration.last_synced_at < threshold),
            )
            .values(last_synced_at=now)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if result.rowcount == 0:
            logger.debug("Auto-sync IOL skipped — lock no adquirido para user %s", user_id)
            return

        integration = db.query(Integration).filter(
            Integration.provider == "IOL",
            Integration.user_id == user_id,
        ).first()
        if not integration or not integration.encrypted_credentials:
            return

        prev_synced_at = integration.last_synced_at

        try:
            logger.info("Auto-sync IOL iniciando para user %s", user_id)
            creds = integration.encrypted_credentials.split(":", 1)
            client = IOLClient(creds[0], creds[1])
            result = _sync_iol(client, db, user_id)
            integration.last_error = ""
            db.commit()
            logger.info("Auto-sync IOL OK: %d posiciones para user %s", result["positions_synced"], user_id)
        except Exception as inner_e:
            logger.warning("Auto-sync IOL falló para user %s: %s", user_id, inner_e)
            try:
                db.rollback()
                # Restaurar last_synced_at para que el próximo auto-sync pueda reintentar
                integration2 = db.query(Integration).filter(
                    Integration.provider == "IOL",
                    Integration.user_id == user_id,
                ).first()
                if integration2:
                    integration2.last_synced_at = prev_synced_at
                    db.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("Auto-sync IOL falló para user %s: %s", user_id, e)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/")
def get_portfolio(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    monthly_expenses_usd = budget.total_monthly_usd if budget else Decimal("2000")

    score = _get_freedom_score(current_user, positions, monthly_expenses_usd)
    buckets = split_portfolio_buckets(positions)

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
                "current_value_ars": float(p.current_value_ars) if p.current_value_ars else None,
                "cost_basis_usd": float(p.cost_basis_usd),
                "performance_pct": float(p.performance_pct),
                "performance_ars_pct": float(p.performance_ars_pct),
                "purchase_fx_rate": float(p.purchase_fx_rate),
                "ppc_ars": float(p.ppc_ars),
                "annual_yield_pct": float(p.annual_yield_pct),
                "snapshot_date": p.snapshot_date.isoformat() if p.snapshot_date else None,
            }
            for p in positions
        ],
        "summary": {
            "total_usd": float(score["portfolio_total_usd"]),
            "total_ars": float(sum(p.current_value_ars for p in positions if p.current_value_ars)) or None,
            # Renta bucket: LETRA/FCI con yield capeado — consistente con gamification y dashboard
            "monthly_return_usd": float(buckets["renta_monthly_usd"]),
            "renta_monthly_usd": float(buckets["renta_monthly_usd"]),
            "capital_total_usd": float(buckets["capital_total_usd"]),
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
    current_user: str = Depends(get_current_user),
):
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    score = _get_freedom_score(current_user, positions, budget.total_monthly_usd if budget else Decimal("2000"))

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


@router.get("/recommendations/sections")
def get_portfolio_sections(
    capital_ars: float = Query(default=500000),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Recomendaciones cross-perfil divididas en renta y capital.
    No requiere risk_profile — cada card devuelve recommended_for.
    6 instrumentos por sección, ordenados por score del comité.
    """
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    score = _get_freedom_score(current_user, positions, budget.total_monthly_usd if budget else Decimal("2000"))

    current_tickers = [p.ticker for p in positions]
    monthly_savings_usd = float(budget.savings_monthly_usd) if budget else 1250.0
    freedom_pct = float(score["freedom_pct"])

    return get_sections_recommendations(
        capital_ars=capital_ars,
        freedom_pct=freedom_pct,
        monthly_savings_usd=monthly_savings_usd,
        current_tickers=current_tickers,
    )


@router.get("/gamification")
def get_gamification(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    background_tasks.add_task(_auto_sync_iol, current_user)
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)

    # ── 1. ¿Qué paga tu portafolio? ──────────────────────────────────────────
    # Usar solo el bucket renta (LETRA, FCI, BOND parcial) con yield capeado.
    # Evita que el 68% nominal ARS de las LECAPs infle el monthly return en USD.
    buckets = split_portfolio_buckets(positions)
    monthly_return_usd = float(buckets["renta_monthly_usd"])

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
    real_months = db.query(InvestmentMonth.month).filter(
        InvestmentMonth.user_id == current_user
    ).all()
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

    current_month = date(today.year, today.month, 1)
    current_month_invested = current_month in invested_months

    return {
        "monthly_return_usd": round(monthly_return_usd, 2),
        "portfolio_covers": portfolio_covers,
        "current_month_invested": current_month_invested,
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
    current_user: str = Depends(get_current_user),
):
    from app.scheduler import trigger_snapshot_now

    # Posiciones activas — necesarias tanto para el snapshot live como para el costo base
    live_positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    total_cost_basis = sum(float(p.cost_basis_usd) for p in live_positions) if live_positions else 0
    total_cost_basis_decimal = Decimal(str(round(total_cost_basis, 2)))

    # Actualizar snapshot de hoy solo si no fue actualizado en los últimos 5 min
    today = date.today()
    try:
        if live_positions:
            budget = _query_budget(db, current_user)
            monthly_expenses = budget.total_monthly_usd if budget else Decimal("2000")
            score = _get_freedom_score(current_user, live_positions, monthly_expenses)

            from app.services.mep import get_mep
            fx_mep = get_mep(budget)  # budget → dolarapi.com → 1430, nunca 0

            snapshot_today = db.query(PortfolioSnapshot).filter(
                PortfolioSnapshot.snapshot_date == today,
                PortfolioSnapshot.user_id == current_user,
            ).first()
            if snapshot_today:
                snapshot_today.total_usd = score["portfolio_total_usd"]
                snapshot_today.monthly_return_usd = score["monthly_return_usd"]
                snapshot_today.positions_count = len(live_positions)
                snapshot_today.cost_basis_usd = total_cost_basis_decimal
                snapshot_today.fx_mep = fx_mep
            else:
                db.add(PortfolioSnapshot(
                    user_id=current_user,
                    snapshot_date=today,
                    total_usd=score["portfolio_total_usd"],
                    monthly_return_usd=score["monthly_return_usd"],
                    positions_count=len(live_positions),
                    fx_mep=fx_mep,
                    cost_basis_usd=total_cost_basis_decimal,
                ))
            db.commit()
            db.expire_all()
            logger.info("Snapshot hoy actualizado: USD %.4f", float(score["portfolio_total_usd"]))
    except Exception as e:
        logger.warning("Refresh snapshot hoy fallo: %s", e, exc_info=True)
        db.rollback()  # sin esto la sesión queda rota y toda query posterior falla

    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.user_id == current_user)
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
        delta_usd = round(total - prev_total, 2)

        # cost_basis guardado en el snapshot (histórico real) o fallback al actual
        cost_now = float(s.cost_basis_usd) if s.cost_basis_usd else total_cost_basis
        cost_prev = float(points_raw[i - 1]["snapshot"].cost_basis_usd) if i > 0 and points_raw[i - 1]["snapshot"].cost_basis_usd else cost_now

        # capital_in = cuánto capital nuevo entró ese período
        capital_in_usd = round(cost_now - cost_prev, 2) if i > 0 else 0
        # market_gain = variación total - capital nuevo
        market_gain_usd = round(delta_usd - capital_in_usd, 2)

        pnl_usd = round(total - cost_now, 2) if cost_now > 0 else 0
        pnl_pct = round(pnl_usd / cost_now * 100, 2) if cost_now > 0 else 0

        points.append({
            "label": item["label"],
            "date": item["date_iso"],
            "total_usd": round(total, 2),
            "monthly_return_usd": round(float(s.monthly_return_usd), 2),
            "fx_mep": round(float(s.fx_mep), 2) if s.fx_mep else 0,
            "delta_usd": delta_usd,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "market_gain_usd": market_gain_usd,
            "capital_in_usd": capital_in_usd,
        })

    return {"period": period, "points": points, "has_data": len(points) >= 1}


@router.get("/next-goal")
def get_next_goal(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    if not budget:
        return None

    score = _get_freedom_score(current_user, positions, budget.total_monthly_usd)
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
def get_freedom_score(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    goal = (
        db.query(FreedomGoal)
        .filter(FreedomGoal.user_id == current_user)
        .order_by(FreedomGoal.id.desc())
        .first()
    )

    monthly_expenses_usd = budget.total_monthly_usd if budget else Decimal("2000")
    monthly_savings_usd = goal.monthly_savings_usd if goal else Decimal("1250")
    annual_return_pct = goal.target_annual_return_pct if goal else Decimal("0.08")

    score = _get_freedom_score(current_user, positions, monthly_expenses_usd)
    buckets = split_portfolio_buckets(positions)

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
        "renta_monthly_usd": float(buckets["renta_monthly_usd"]),
        "capital_total_usd": float(buckets["capital_total_usd"]),
        "milestones": milestones,
    }


_ASSET_CONTEXT = {
    "CEDEAR": {
        "type_label": "CEDEAR",
        "full_name": "Certificado de Depósito Argentino",
        "description": "Representa acciones de empresas extranjeras que cotizan en ARS vía CCL.",
        "currency_note": "El precio en ARS refleja el tipo de cambio CCL implícito. El rendimiento en USD es el más representativo.",
        "liquidity": "Alta — mercado continuo L-V.",
    },
    "LETRA": {
        "type_label": "LECAP",
        "full_name": "Letra de Capitalización del Tesoro",
        "description": "Instrumento de deuda de corto plazo del Tesoro Argentino en ARS. Capitaliza diariamente.",
        "currency_note": "Cotiza en ARS. Valor par = 100 nominales. El precio sube diariamente con la TNA.",
        "liquidity": "Alta — mercado secundario BYMA.",
    },
    "FCI": {
        "type_label": "FCI",
        "full_name": "Fondo Común de Inversión",
        "description": "Fondo de inversión colectiva administrado por una sociedad gerente. Diversificación automática.",
        "currency_note": "Cuotapartes en ARS. El valor cuotaparte actualiza diariamente.",
        "liquidity": "Alta — rescate acreditado en 24-48hs hábiles.",
    },
    "BOND": {
        "type_label": "BONO",
        "full_name": "Bono de Renta Fija",
        "description": "Instrumento de deuda que paga cupones periódicos y amortización. Puede ser soberano o corporativo.",
        "currency_note": "Puede cotizar en ARS o USD según la serie. Los dollar-linked siguen al tipo de cambio oficial.",
        "liquidity": "Media — depende del volumen del bono.",
    },
    "CRYPTO": {
        "type_label": "CRYPTO",
        "full_name": "Criptomoneda",
        "description": "Activo digital descentralizado. Alta volatilidad. Mercado 24/7.",
        "currency_note": "Cotiza en USD. Sin regulación BCRA.",
        "liquidity": "Muy alta — mercado 24/7.",
    },
}


class GoalIn(BaseModel):
    monthly_savings_usd: float
    target_annual_return_pct: float = 0.08


class CapitalGoalIn(BaseModel):
    name: str
    emoji: str = "🎯"
    target_usd: float
    target_years: int = 5


@router.get("/goal")
def get_goal(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goal = (
        db.query(FreedomGoal)
        .filter(FreedomGoal.user_id == current_user)
        .order_by(FreedomGoal.id.desc())
        .first()
    )
    if not goal:
        return {"monthly_savings_usd": None, "target_annual_return_pct": 0.08}
    return {
        "monthly_savings_usd": float(goal.monthly_savings_usd),
        "target_annual_return_pct": float(goal.target_annual_return_pct),
    }


@router.put("/goal")
def save_goal(
    body: GoalIn,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goal = (
        db.query(FreedomGoal)
        .filter(FreedomGoal.user_id == current_user)
        .order_by(FreedomGoal.id.desc())
        .first()
    )
    if goal:
        goal.monthly_savings_usd = Decimal(str(round(body.monthly_savings_usd, 2)))
        goal.target_annual_return_pct = Decimal(str(round(body.target_annual_return_pct, 4)))
    else:
        goal = FreedomGoal(
            user_id=current_user,
            monthly_savings_usd=Decimal(str(round(body.monthly_savings_usd, 2))),
            target_annual_return_pct=Decimal(str(round(body.target_annual_return_pct, 4))),
        )
        db.add(goal)
    db.commit()
    return {"ok": True, "monthly_savings_usd": float(goal.monthly_savings_usd)}


@router.get("/capital-goals")
def list_capital_goals(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goals = (
        db.query(CapitalGoal)
        .filter(CapitalGoal.user_id == current_user)
        .order_by(CapitalGoal.created_at)
        .all()
    )
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    portfolio_usd = float(sum(p.current_value_usd for p in positions))
    budget = _query_budget(db, current_user)
    freedom_goal = (
        db.query(FreedomGoal)
        .filter(FreedomGoal.user_id == current_user)
        .order_by(FreedomGoal.id.desc())
        .first()
    )
    # monthly savings: from budget or from freedom_goal
    if budget:
        mep = float(budget.fx_rate)
        monthly_savings_usd = float(budget.savings_monthly_ars) / mep if mep > 0 else 0
    elif freedom_goal:
        monthly_savings_usd = float(freedom_goal.monthly_savings_usd)
    else:
        monthly_savings_usd = 0
    raw_return = float(freedom_goal.target_annual_return_pct) if freedom_goal else 0.08
    annual_return = max(0.06, min(raw_return, 0.15))  # cap realista 6–15% USD
    monthly_rate = annual_return / 12

    # Ordenar de menor a mayor target: la meta más chica se financia primero
    goals_sorted = sorted(goals, key=lambda g: float(g.target_usd))

    # Allocation secuencial: cada meta consume el capital restante
    remaining_usd = portfolio_usd
    result = []
    for g in goals_sorted:
        target = float(g.target_usd)
        allocated = min(remaining_usd, target)
        progress_pct = min(100, round(allocated / target * 100, 1)) if target > 0 else 0

        if monthly_savings_usd > 0 and monthly_rate > 0:
            bal = remaining_usd
            months = 0
            while bal < target and months < 600:
                bal = bal * (1 + monthly_rate) + monthly_savings_usd
                months += 1
            months_to_goal = months if bal >= target else None
        elif monthly_savings_usd > 0:
            months_to_goal = max(0, round(max(0.0, target - remaining_usd) / monthly_savings_usd))
        else:
            months_to_goal = None

        result.append({
            "id": g.id,
            "name": g.name,
            "emoji": g.emoji,
            "target_usd": target,
            "target_years": g.target_years,
            "portfolio_usd": allocated,
            "progress_pct": progress_pct,
            "months_to_goal": months_to_goal,
            "monthly_savings_usd": round(monthly_savings_usd, 2),
        })
        remaining_usd = max(0.0, remaining_usd - target)

    return result


@router.post("/capital-goals")
def create_capital_goal(
    body: CapitalGoalIn,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goal = CapitalGoal(
        user_id=current_user,
        name=body.name,
        emoji=body.emoji,
        target_usd=Decimal(str(round(body.target_usd, 2))),
        target_years=body.target_years,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return {"id": goal.id, "name": goal.name, "emoji": goal.emoji}


@router.put("/capital-goals/{goal_id}")
def update_capital_goal(
    goal_id: int,
    body: CapitalGoalIn,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goal = db.query(CapitalGoal).filter(
        CapitalGoal.id == goal_id,
        CapitalGoal.user_id == current_user,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.name = body.name
    goal.emoji = body.emoji
    goal.target_usd = Decimal(str(round(body.target_usd, 2)))
    goal.target_years = body.target_years
    db.commit()
    return {"ok": True}


@router.delete("/capital-goals/{goal_id}")
def delete_capital_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    goal = db.query(CapitalGoal).filter(
        CapitalGoal.id == goal_id,
        CapitalGoal.user_id == current_user,
    ).first()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(goal)
    db.commit()
    return {"ok": True}


@router.get("/projection")
def get_portfolio_projection(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Proyección compuesta a 10 años con dos curvas:
    - 'with_savings': portafolio actual + aportes mensuales + rendimiento
    - 'without_savings': solo portafolio actual + rendimiento, sin nuevos aportes
    Permite visualizar el impacto del DCA y el interés compuesto.
    """
    positions = db.query(Position).filter(
        Position.is_active == True,
        Position.user_id == current_user,
    ).all()
    budget = _query_budget(db, current_user)
    goal = (
        db.query(FreedomGoal)
        .filter(FreedomGoal.user_id == current_user)
        .order_by(FreedomGoal.id.desc())
        .first()
    )

    # Parámetros base
    # Proyección sobre el bucket capital (CEDEAR, ETF, CRYPTO + 50% BOND).
    # Excluir LETRA/FCI: su rendimiento nominal ARS no es comparable con USD compuesto.
    proj_buckets = split_portfolio_buckets(positions)
    capital_usd = float(proj_buckets["capital_total_usd"])
    current_usd = capital_usd if capital_usd > 0 else float(sum(p.current_value_usd for p in positions))
    monthly_savings_usd = float(goal.monthly_savings_usd) if goal else 1250.0
    if budget:
        ars = float(budget.savings_monthly_ars)
        mep = float(budget.fx_rate)
        if mep > 0:
            monthly_savings_usd = ars / mep

    # Yield anual: prioridad → goal configurado, luego yield del bucket capital (cap 15%)
    MAX_REALISTIC_YIELD = 0.15  # 15% anual USD — muy agresivo, rara vez superado
    MIN_YIELD = 0.06            # 6% — piso conservador
    if goal and goal.target_annual_return_pct and goal.target_annual_return_pct > 0:
        annual_return_pct = float(goal.target_annual_return_pct)
    else:
        # Yield del bucket capital: weighted average solo sobre posiciones de crecimiento
        cap_positions = [p for p in positions if getattr(p, "asset_type", "").upper() in {"CEDEAR", "ETF", "CRYPTO", "BOND"}]
        if cap_positions:
            cap_total = sum(float(p.current_value_usd) for p in cap_positions)
            if cap_total > 0:
                raw_yield = sum(float(p.current_value_usd) * float(p.annual_yield_pct) for p in cap_positions) / cap_total
            else:
                raw_yield = 0.08
        else:
            raw_yield = 0.08
        annual_return_pct = max(MIN_YIELD, min(raw_yield, MAX_REALISTIC_YIELD))
    monthly_rate = annual_return_pct / 12

    # Generar puntos: año 0 al 10 (anual)
    points = []
    bal_with    = current_usd
    bal_without = current_usd

    for year in range(0, 11):
        points.append({
            "year": year,
            "with_savings_usd":    round(bal_with,    0),
            "without_savings_usd": round(bal_without,  0),
            "label": f"Año {year}" if year > 0 else "Hoy",
        })
        # Proyectar 12 meses hacia adelante
        for _ in range(12):
            bal_with    = bal_with    * (1 + monthly_rate) + monthly_savings_usd
            bal_without = bal_without * (1 + monthly_rate)

    extra_usd = points[-1]["with_savings_usd"] - points[-1]["without_savings_usd"]

    return {
        "current_usd": round(current_usd, 2),
        "capital_total_usd": round(current_usd, 2),
        "monthly_savings_usd": round(monthly_savings_usd, 2),
        "annual_return_pct": round(annual_return_pct, 4),
        "extra_usd_10y": round(extra_usd, 0),
        "points": points,
    }


@router.get("/instrument/{ticker}")
def get_instrument_detail(
    ticker: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    position = db.query(Position).filter(
        Position.ticker == ticker,
        Position.is_active == True,
        Position.user_id == current_user,
    ).first()

    if not position:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado")

    budget = (
        db.query(BudgetConfig)
        .filter(BudgetConfig.user_id == current_user)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )
    mep = float(budget.fx_rate) if budget and budget.fx_rate else 1430.0

    pnl_usd = float(position.current_value_usd) - float(position.cost_basis_usd)
    monthly_return_usd = float(position.current_value_usd) * float(position.annual_yield_pct) / 12

    context = _ASSET_CONTEXT.get(position.asset_type, {
        "type_label": position.asset_type,
        "full_name": position.asset_type,
        "description": "Activo financiero.",
        "currency_note": "",
        "liquidity": "Variable.",
    })

    # LECAP: fecha de vencimiento decodificada del ticker
    maturity_date = None
    days_to_maturity = None
    if position.asset_type == "LETRA":
        from app.services.yield_updater import _parse_lecap_maturity
        mat = _parse_lecap_maturity(position.ticker)
        if mat:
            maturity_date = mat.isoformat()
            days_to_maturity = (mat - date.today()).days

    return {
        "ticker": position.ticker,
        "description": position.description,
        "asset_type": position.asset_type,
        "source": position.source,
        "quantity": float(position.quantity),
        "ppc_ars": float(position.ppc_ars),
        "purchase_fx_rate": float(position.purchase_fx_rate),
        "avg_purchase_price_usd": float(position.avg_purchase_price_usd),
        "current_price_usd": float(position.current_price_usd),
        "current_value_usd": float(position.current_value_usd),
        "cost_basis_usd": float(position.cost_basis_usd),
        "performance_pct": float(position.performance_pct),
        "pnl_usd": round(pnl_usd, 2),
        "annual_yield_pct": float(position.annual_yield_pct),
        "monthly_return_usd": round(monthly_return_usd, 4),
        "last_updated": position.snapshot_date.isoformat() if position.snapshot_date else None,
        "mep": round(mep, 2),
        "context": context,
        "maturity_date": maturity_date,
        "days_to_maturity": days_to_maturity,
    }
