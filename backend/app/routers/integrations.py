import logging
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("buildfuture.integrations")
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models import Integration, Position, InvestmentMonth
from app.services.iol_client import IOLClient, IOLAuthError
from app.services.nexo_client import NexoClient, NexoAuthError

router = APIRouter(prefix="/integrations", tags=["integrations"])


class ConnectRequest(BaseModel):
    username: str
    password: str


class ConnectNexoRequest(BaseModel):
    api_key: str
    api_secret: str


@router.get("/")
def get_integrations(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    integrations = db.query(Integration).filter(
        Integration.user_id == current_user
    ).all()
    return [
        {
            "id": i.id,
            "provider": i.provider,
            "provider_type": i.provider_type,
            "is_active": i.is_active,
            "is_connected": i.is_connected,
            "last_synced_at": i.last_synced_at.isoformat() if i.last_synced_at else None,
            "last_error": i.last_error,
        }
        for i in integrations
    ]


@router.post("/iol/connect")
def connect_iol(
    body: ConnectRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Testea credenciales IOL, guarda en DB (plain text para dev local),
    y hace el primer sync del portafolio.
    """
    # 1. Testear credenciales
    client = IOLClient(body.username, body.password)
    try:
        client.authenticate()
    except IOLAuthError as e:
        raise HTTPException(status_code=401, detail=f"Credenciales incorrectas: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error conectando con IOL: {str(e)}")

    # 2. Guardar credenciales (dev: plain text — prod: AES-256)
    integration = db.query(Integration).filter(
        Integration.provider == "IOL",
        Integration.user_id == current_user,
    ).first()
    if not integration:
        integration = Integration(
            user_id=current_user,
            provider="IOL",
            provider_type="ALYC",
        )
        db.add(integration)

    # Guardamos como "usuario:password" — solo para dev local
    integration.encrypted_credentials = f"{body.username}:{body.password}"
    integration.is_connected = True
    integration.last_error = ""
    db.flush()

    # 3. Sincronizar portafolio real
    result = _sync_iol(client, db, current_user)

    integration.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "connected": True,
        "positions_synced": result["positions_synced"],
        "message": f"Conectado. {result['positions_synced']} posiciones sincronizadas.",
    }


@router.post("/iol/sync")
def sync_iol(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Re-sincroniza el portafolio IOL con las credenciales guardadas."""
    integration = db.query(Integration).filter(
        Integration.provider == "IOL",
        Integration.user_id == current_user,
    ).first()
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="IOL no está conectado")

    try:
        creds = integration.encrypted_credentials.split(":", 1)
        client = IOLClient(creds[0], creds[1])
        result = _sync_iol(client, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        return {"positions_synced": result["positions_synced"]}
    except Exception as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/iol/debug")
def debug_iol(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Muestra lo que IOL devuelve sin modificar la DB.
    Útil para diagnosticar diferencias entre IOL y BuildFuture.
    """
    integration = db.query(Integration).filter(
        Integration.provider == "IOL",
        Integration.user_id == current_user,
        Integration.is_connected == True,
    ).first()
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(status_code=400, detail="IOL no está conectado")

    try:
        creds = integration.encrypted_credentials.split(":", 1)
        client = IOLClient(creds[0], creds[1])
        mep = client._get_mep()
        raw = client._get("/api/v2/portafolio/argentina")
        activos = raw.get("activos", [])

        items = []
        total_ars = 0.0
        for a in activos:
            titulo = a.get("titulo", {})
            valorizado = float(a.get("valorizado") or 0)
            cantidad = float(a.get("cantidad") or 0)
            total_ars += valorizado
            items.append({
                "ticker": titulo.get("simbolo"),
                "tipo": titulo.get("tipo"),
                "cantidad": cantidad,
                "valorizado_ars": round(valorizado, 2),
                "valorizado_usd": round(valorizado / mep, 2) if mep else 0,
                "ppc": a.get("ppc"),
            })

        cuenta = client.get_account_balance()

        return {
            "mep": round(mep, 2),
            "total_ars_iol": round(total_ars, 2),
            "total_usd_iol": round(total_ars / mep, 2) if mep else 0,
            "positions_count": len(items),
            "positions": items,
            "estadocuenta_raw": cuenta,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/iol/disconnect")
def disconnect_iol(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Desconecta IOL: borra credenciales y desactiva posiciones sincronizadas."""
    integration = db.query(Integration).filter(
        Integration.provider == "IOL",
        Integration.user_id == current_user,
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integración IOL no encontrada")

    # Limpiar credenciales y marcar como desconectado
    integration.encrypted_credentials = ""
    integration.is_connected = False
    integration.last_error = ""

    # Desactivar todas las posiciones IOL del usuario
    from app.models import Position
    db.query(Position).filter(
        Position.user_id == current_user,
        Position.source == "IOL",
        Position.is_active == True,
    ).update({"is_active": False})

    db.commit()
    return {"disconnected": True}


@router.post("/nexo/connect")
def connect_nexo(
    body: ConnectNexoRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    client = NexoClient(body.api_key, body.api_secret)
    try:
        client.test_auth()
    except NexoAuthError as e:
        raise HTTPException(status_code=401, detail=f"Credenciales Nexo inválidas: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error conectando con Nexo: {str(e)}")

    integration = db.query(Integration).filter(
        Integration.provider == "NEXO",
        Integration.user_id == current_user,
    ).first()
    if not integration:
        integration = Integration(
            user_id=current_user,
            provider="NEXO",
            provider_type="CRYPTO",
        )
        db.add(integration)

    integration.encrypted_credentials = f"{body.api_key}:{body.api_secret}"
    integration.is_connected = True
    integration.last_error = ""
    db.flush()

    result = _sync_nexo(client, db, current_user)
    integration.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "connected": True,
        "positions_synced": result["positions_synced"],
        "message": f"Nexo conectado. {result['positions_synced']} assets sincronizados.",
    }


@router.post("/nexo/sync")
def sync_nexo(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    integration = db.query(Integration).filter(
        Integration.provider == "NEXO",
        Integration.user_id == current_user,
    ).first()
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="Nexo no está conectado")

    try:
        parts = integration.encrypted_credentials.split(":", 1)
        client = NexoClient(parts[0], parts[1])
        result = _sync_nexo(client, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        return {"positions_synced": result["positions_synced"]}
    except Exception as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


def _sync_nexo(client: NexoClient, db: Session, user_id: str) -> dict:
    positions = client.get_balances()

    db.query(Position).filter(
        Position.source == "NEXO",
        Position.is_active == True,
        Position.user_id == user_id,
    ).update({"is_active": False})

    today = date.today()
    synced = 0

    for p in positions:
        pos = Position(
            user_id=user_id,
            ticker=p.ticker,
            description=p.description,
            asset_type=p.asset_type,
            source="NEXO",
            quantity=p.quantity,
            avg_purchase_price_usd=p.current_price_usd,
            current_price_usd=p.current_price_usd,
            annual_yield_pct=p.annual_yield_pct,
            snapshot_date=today,
            is_active=True,
        )
        db.add(pos)
        synced += 1

    db.flush()
    return {"positions_synced": synced}


def _sync_iol(client: IOLClient, db: Session, user_id: str) -> dict:
    """Trae posiciones y operaciones de IOL, upserta en la DB."""
    # Obtener MEP actual UNA vez — se usa para conversión ARS→USD y para actualizar budget
    current_mep = client._get_mep()

    positions = client.get_portfolio()

    # Desactivar posiciones IOL anteriores del usuario
    db.query(Position).filter(
        Position.source == "IOL",
        Position.is_active == True,
        Position.user_id == user_id,
    ).update({"is_active": False})

    today = date.today()
    synced = 0

    # Buscar MEP histórico por ticker desde operaciones para el costo base real
    purchase_mep_by_ticker = _get_purchase_mep_from_operations(client)

    for p in positions:
        if p.quantity <= 0:
            continue

        purchase_fx = purchase_mep_by_ticker.get(p.ticker, float(p.avg_price_usd) * 0)
        # Si no tenemos MEP histórico, usamos el MEP actual como aproximación
        if not purchase_fx:
            purchase_fx = client._get_mep()

        pos = Position(
            user_id=user_id,
            ticker=p.ticker,
            description=p.description,
            asset_type=p.asset_type,
            source="IOL",
            quantity=p.quantity,
            avg_purchase_price_usd=p.avg_price_usd,
            current_price_usd=p.current_price_usd,
            annual_yield_pct=p.annual_yield_pct,
            snapshot_date=today,
            is_active=True,
            ppc_ars=p.ppc_ars,
            purchase_fx_rate=Decimal(str(round(purchase_fx, 2))),
            current_value_ars=p.valorizado_ars,
        )
        db.add(pos)
        synced += 1

    # Sincronizar meses de inversión desde operaciones (últimos 13 meses)
    months_synced = _sync_investment_months(client, db, user_id)

    # Actualizar MEP en el presupuesto del usuario para que el display en ARS sea consistente
    # con los valores almacenados (que usan el mismo MEP para la conversión ARS→USD)
    from app.models import BudgetConfig
    budget = (
        db.query(BudgetConfig)
        .filter(BudgetConfig.user_id == user_id)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )
    if budget and current_mep > 0:
        budget.fx_rate = Decimal(str(round(current_mep, 2)))
        logger.info("Budget fx_rate actualizado a MEP=%.2f para user %s", current_mep, user_id)

    # ── Cash disponible IOL ──────────────────────────────────────────────────
    # Se guarda como posición sintética CASH_IOL para que aparezca en el portafolio.
    # Primero desactivar cualquier cash anterior para este usuario.
    db.query(Position).filter(
        Position.ticker == "CASH_IOL",
        Position.user_id == user_id,
    ).update({"is_active": False})

    cash_ars = client.get_cash_balance_ars()
    if cash_ars > 0:
        mep_dec = Decimal(str(current_mep))
        cash_usd = cash_ars / mep_dec if mep_dec > 0 else Decimal("0")
        db.add(Position(
            user_id=user_id,
            ticker="CASH_IOL",
            description="Saldo disponible en pesos · IOL",
            asset_type="CASH",
            source="IOL",
            quantity=Decimal("1"),
            avg_purchase_price_usd=cash_usd,
            current_price_usd=cash_usd,
            annual_yield_pct=Decimal("0"),
            snapshot_date=today,
            is_active=True,
            ppc_ars=cash_ars,
            purchase_fx_rate=mep_dec,
            current_value_ars=cash_ars,
        ))
        logger.info("Cash IOL guardado: ARS %.2f → USD %.2f", float(cash_ars), float(cash_usd))
        synced += 1

    # Invalidar cache de freedom score para que el próximo request incluya el cash
    try:
        from app.routers.portfolio import _invalidate_score_cache
        _invalidate_score_cache(user_id)
    except Exception:
        pass

    db.flush()
    return {"positions_synced": synced, "months_synced": months_synced, "mep": round(current_mep, 2)}


def _get_purchase_mep_from_operations(client: IOLClient) -> dict[str, float]:
    """
    Para cada ticker con compras en IOL, busca la fecha de la primera/principal
    compra y obtiene el MEP histórico de ese día.
    Retorna {ticker: mep_al_momento_de_compra}.
    """
    from datetime import timedelta
    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime("%Y-%m-%d")
    operations = client.get_operations(fecha_desde=fecha_desde)

    # Agrupar compras por ticker: fecha más reciente de compra relevante
    ticker_dates: dict[str, str] = {}
    for op in operations:
        if "compra" not in str(op.get("tipo", "")).lower():
            continue
        raw_date = op.get("fechaOrden") or op.get("fecha") or ""
        ticker = op.get("simbolo") or op.get("ticker") or ""
        if raw_date and ticker:
            fecha = raw_date[:10]
            # Si ya tenemos una fecha más reciente, quedarse con la más reciente
            if ticker not in ticker_dates or fecha > ticker_dates[ticker]:
                ticker_dates[ticker] = fecha

    # Necesitamos precio ARS actual por ticker para derivar la equivalencia de CEDEARs
    # Lo obtenemos del portafolio actual (ya lo tenemos en memoria aquí no, así que
    # pasamos el cálculo al cliente con el precio del portfolio)
    portfolio = client.get_portfolio()
    price_ars_by_ticker = {
        p.ticker: float(p.quantity * p.current_price_usd * Decimal(str(client._get_mep())))
        / float(p.quantity) if p.quantity > 0 else 0
        for p in portfolio
    }

    result: dict[str, float] = {}
    for ticker, fecha in ticker_dates.items():
        # Buscar si es CEDEAR para usar CCL implícito
        pos = next((p for p in portfolio if p.ticker == ticker), None)
        if pos and pos.asset_type == "CEDEAR":
            price_ars = price_ars_by_ticker.get(ticker, 0)
            if price_ars > 0:
                ccl = client.get_cedear_implicit_ccl(ticker, price_ars, purchase_date=fecha)
                if ccl:
                    result[ticker] = ccl
                    logger.info("CCL implícito %s en %s = %.2f", ticker, fecha, ccl)
                    continue
        # Fallback: MEP histórico para instrumentos ARS o si no hay datos NYSE
        mep = client.get_historical_mep(fecha)
        result[ticker] = mep
        logger.info("MEP compra %s en %s = %.2f", ticker, fecha, mep)

    return result


def _sync_investment_months(client: IOLClient, db: Session, user_id: str) -> int:
    """
    Trae operaciones de compra de IOL y registra los meses con inversión real.
    IOL devuelve: fechaOrden, tipo ('compra'/'venta'), simbolo, monto, precio.
    """
    from datetime import timedelta

    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime("%Y-%m-%d")
    operations = client.get_operations(fecha_desde=fecha_desde)

    months_found: dict[date, dict] = {}
    for op in operations:
        tipo = str(op.get("tipo", "")).lower()
        if "compra" not in tipo:
            continue

        raw_date = op.get("fechaOrden") or op.get("fecha") or ""
        if not raw_date:
            continue
        try:
            op_date = datetime.fromisoformat(raw_date[:10]).date()
        except ValueError:
            continue

        month_key = op_date.replace(day=1)
        monto = float(op.get("monto", 0) or op.get("montoOperado", 0) or 0)

        if month_key not in months_found:
            months_found[month_key] = {"amount_ars": 0.0, "tickers": []}
        months_found[month_key]["amount_ars"] += monto
        ticker = op.get("simbolo", op.get("ticker", ""))
        if ticker:
            months_found[month_key]["tickers"].append(ticker)

    synced = 0
    for month_date, data in months_found.items():
        existing = db.query(InvestmentMonth).filter(
            InvestmentMonth.month == month_date,
            InvestmentMonth.user_id == user_id,
        ).first()
        if not existing:
            note = ", ".join(set(data["tickers"]))[:200]
            db.add(InvestmentMonth(
                user_id=user_id,
                month=month_date,
                amount_ars=Decimal(str(round(data["amount_ars"], 2))),
                source="IOL",
                note=note,
            ))
            synced += 1

    return synced
