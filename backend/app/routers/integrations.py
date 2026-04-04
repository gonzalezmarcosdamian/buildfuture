import logging
import os
from datetime import datetime, date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("buildfuture.integrations")
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
import json
from app.models import (
    Integration,
    IntegrationDiscovery,
    IntegrationErrorLog,
    Position,
    InvestmentMonth,
    PortfolioSnapshot,
    BudgetConfig,
)
from app.services.iol_client import IOLClient, IOLAuthError
from app.services.nexo_client import NexoClient, NexoAuthError
from app.services.ppi_client import PPIClient, PPIAuthError
from app.services.cocos_client import CocosClient, CocosAuthError
from app.services.binance_client import BinanceClient, BinanceAuthError

router = APIRouter(prefix="/integrations", tags=["integrations"])


class ConnectRequest(BaseModel):
    username: str
    password: str


class ConnectNexoRequest(BaseModel):
    api_key: str
    api_secret: str


def _log_error(
    db: Session, user_id: str, provider: str, operation: str, error: Exception
) -> None:
    """Persiste un error de integración para diagnóstico multi-usuario."""
    code = ""
    msg = str(error)
    # Extraer código HTTP si está en el mensaje
    import re as _re

    m = _re.search(r"(?:status|Status|PPI respondió|respondió)\s*(\d{3})", msg)
    if m:
        code = m.group(1)
    try:
        db.add(
            IntegrationErrorLog(
                user_id=user_id,
                provider=provider,
                operation=operation,
                error_code=code,
                error_message=msg[:500],
            )
        )
        db.flush()
    except Exception:
        pass  # logging nunca debe romper el flujo principal


_DEFAULT_INTEGRATIONS = [
    {"provider": "IOL", "provider_type": "ALYC"},
    {"provider": "PPI", "provider_type": "ALYC"},
    {"provider": "COCOS", "provider_type": "ALYC"},
    {"provider": "BINANCE", "provider_type": "EXCHANGE"},
]


@router.get("/")
def get_integrations(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    integrations = (
        db.query(Integration).filter(Integration.user_id == current_user).all()
    )

    # Primer acceso: crear integraciones por defecto si el usuario no tiene ninguna
    if not integrations:
        for spec in _DEFAULT_INTEGRATIONS:
            db.add(
                Integration(
                    user_id=current_user,
                    provider=spec["provider"],
                    provider_type=spec["provider_type"],
                    is_active=True,
                    is_connected=False,
                )
            )
        db.commit()
        integrations = (
            db.query(Integration).filter(Integration.user_id == current_user).all()
        )
    else:
        # Backfill: agregar providers nuevos que no tenga el usuario todavía
        existing_providers = {i.provider for i in integrations}
        added = False
        for spec in _DEFAULT_INTEGRATIONS:
            if spec["provider"] not in existing_providers:
                db.add(
                    Integration(
                        user_id=current_user,
                        provider=spec["provider"],
                        provider_type=spec["provider_type"],
                        is_active=True,
                        is_connected=False,
                    )
                )
                added = True
        if added:
            db.commit()
            integrations = (
                db.query(Integration).filter(Integration.user_id == current_user).all()
            )

    return [_integration_response(i) for i in integrations]


def _integration_response(i: Integration) -> dict:
    """Serializa una Integration. auto_sync_enabled indica si el scheduler puede sincronizar."""
    auto_sync_enabled = True
    if i.provider == "COCOS" and i.is_connected:
        parts = (i.encrypted_credentials or "").split(":", 2)
        totp_secret = parts[2] if len(parts) == 3 else ""
        auto_sync_enabled = bool(totp_secret)
    return {
        "id": i.id,
        "provider": i.provider,
        "provider_type": i.provider_type,
        "is_active": i.is_active,
        "is_connected": i.is_connected,
        "auto_sync_enabled": auto_sync_enabled,
        "last_synced_at": i.last_synced_at.isoformat() if i.last_synced_at else None,
        "last_error": i.last_error,
    }


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
    # 1. Testear credenciales (skip en modo mock)
    client = IOLClient(body.username, body.password)
    if not (os.getenv("MOCK_INTEGRATIONS") == "true" and body.username == "mock"):
        try:
            client.authenticate()
        except IOLAuthError as e:
            raise HTTPException(
                status_code=401, detail=f"Credenciales incorrectas: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Error conectando con IOL: {str(e)}"
            )

    # 2. Guardar credenciales (dev: plain text — prod: AES-256)
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "IOL",
            Integration.user_id == current_user,
        )
        .first()
    )
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

    # Crear snapshot inicial para que la proyección histórica tenga al menos el día de hoy
    try:
        _upsert_today_snapshot(db, current_user)
    except Exception as snap_err:
        logger.warning("connect_iol: snapshot inicial falló (no crítico): %s", snap_err)

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
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "IOL",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="IOL no está conectado")

    try:
        creds = integration.encrypted_credentials.split(":", 1)
        client = IOLClient(creds[0], creds[1])
        result = _sync_iol(client, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        try:
            _upsert_today_snapshot(db, current_user)
        except Exception as snap_err:
            logger.warning("sync_iol: snapshot falló (no crítico): %s", snap_err)
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
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "IOL",
            Integration.user_id == current_user,
            Integration.is_connected == True,
        )
        .first()
    )
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
            items.append(
                {
                    "ticker": titulo.get("simbolo"),
                    "tipo": titulo.get("tipo"),
                    "cantidad": cantidad,
                    "valorizado_ars": round(valorizado, 2),
                    "valorizado_usd": round(valorizado / mep, 2) if mep else 0,
                    "ppc": a.get("ppc"),
                }
            )

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
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "IOL",
            Integration.user_id == current_user,
        )
        .first()
    )
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
        raise HTTPException(
            status_code=401, detail=f"Credenciales Nexo inválidas: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Error conectando con Nexo: {str(e)}"
        )

    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "NEXO",
            Integration.user_id == current_user,
        )
        .first()
    )
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
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "NEXO",
            Integration.user_id == current_user,
        )
        .first()
    )
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


def _get_enrichment(db: Session, user_id: str, source: str) -> dict[str, dict]:
    """
    Lee los campos platform-owned de las posiciones activas actuales ANTES de desactivarlas.
    Retorna un dict {ticker: {annual_yield_pct, external_id, fci_categoria}} por source+user.

    Esto garantiza que cada re-sync preserve el enriquecimiento calculado por yield_updater
    y _fci_external_id, en lugar de pisarlo con los DEFAULT del ALYC.

    Solo preserva annual_yield_pct si es diferente al DEFAULT por tipo de activo — así
    posiciones nuevas sin enriquecimiento previo siguen usando el default del ALYC.
    """
    from app.services.iol_client import DEFAULT_YIELDS

    _TYPE_TO_KEY = {
        "BOND": "bono",
        "ON": "on",
        "CEDEAR": "cedear",
        "LETRA": "letra",
        "FCI": "fci",
        "CASH": "default",
    }
    rows = (
        db.query(
            Position.ticker,
            Position.asset_type,
            Position.annual_yield_pct,
            Position.external_id,
            Position.fci_categoria,
        )
        .filter(
            Position.source == source,
            Position.user_id == user_id,
            Position.is_active == True,
        )
        .all()
    )

    result: dict[str, dict] = {}
    for row in rows:
        yield_key = _TYPE_TO_KEY.get(row.asset_type, "default")
        default_yield = DEFAULT_YIELDS.get(yield_key, DEFAULT_YIELDS["default"])
        # Solo preservar si es valor enriquecido (diferente al default del tipo)
        enriched_yield = (
            row.annual_yield_pct if row.annual_yield_pct != default_yield else None
        )
        result[row.ticker] = {
            "annual_yield_pct": enriched_yield,
            "external_id": row.external_id,
            "fci_categoria": row.fci_categoria,
        }
    return result


# Manual mapping for IOL FCI tickers that are misclassified or poorly matched by fuzzy search.
# Format: ticker → (external_id | None, fci_categoria)
# external_id=None means yield_updater falls back to category average (safe).
# Add entries when a new IOL FCI ticker is confirmed to belong to a specific ArgentinaDatos fund.
_IOL_FCI_TICKER_MAP: dict[str, tuple[str | None, str]] = {
    "IOLCAMA": (None, "mercadoDinero"),   # IOL Money Market ARS — category confirmed
    "IOLCAM":  (None, "mercadoDinero"),   # alias variant
    "IOLMMA":  (None, "mercadoDinero"),   # IOL Money Market ARS variant
    "IOLMM":   (None, "mercadoDinero"),   # alias variant
}


def _fci_external_id(description: str, ticker: str = "") -> tuple[str | None, str | None]:
    """
    Resuelve external_id + fci_categoria para un FCI.
    1. Consulta primero el mapa manual _IOL_FCI_TICKER_MAP por ticker (exacto y seguro).
    2. Si no hay mapeo manual, intenta fuzzy match por descripción contra ArgentinaDatos.
    Retorna (fondo_name | None, categoria) o (None, None) si no hay match.
    """
    # Paso 1: mapa manual — evita falsos positivos del fuzzy match
    if ticker.upper() in _IOL_FCI_TICKER_MAP:
        return _IOL_FCI_TICKER_MAP[ticker.upper()]

    if not description:
        return None, None

    # Paso 2: fuzzy match por descripción
    try:
        from app.services.fci_prices import _fetch_categoria, CATEGORIAS

        desc_lower = description.lower()
        for cat in CATEGORIAS:
            fondos = _fetch_categoria(cat)
            for f in fondos:
                nombre = f.get("fondo", "")
                # Match si al menos 3 palabras de la descripción aparecen en el nombre del fondo
                words = [w for w in desc_lower.split() if len(w) > 3]
                if words and sum(1 for w in words if w in nombre.lower()) >= min(
                    2, len(words)
                ):
                    return nombre, cat
    except Exception:
        pass
    return None, None


def _sync_iol(client: IOLClient, db: Session, user_id: str) -> dict:
    """Trae posiciones y operaciones de IOL, upserta en la DB."""
    # En modo mock, las posiciones ya están en la DB desde seed_mock — no sobreescribir
    if os.getenv("MOCK_INTEGRATIONS") == "true":
        logger.info(
            "_sync_iol: MOCK_INTEGRATIONS=true — skip sync real para user=%s", user_id
        )
        return {"positions_synced": 0, "months_synced": 0, "mep": 1430}

    # Obtener MEP actual UNA vez — se usa para conversión ARS→USD y para actualizar budget
    current_mep = client._get_mep()

    positions = client.get_portfolio()

    # Leer enriquecimiento previo ANTES de desactivar — preserva yield real y FCI metadata
    enrichment = _get_enrichment(db, user_id, "IOL")

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

        prior = enrichment.get(p.ticker, {})
        fci_ext_id, fci_cat = (
            _fci_external_id(p.description, ticker=p.ticker) if p.asset_type == "FCI" else (None, None)
        )
        pos = Position(
            user_id=user_id,
            ticker=p.ticker,
            description=p.description,
            asset_type=p.asset_type,
            source="IOL",
            quantity=p.quantity,
            avg_purchase_price_usd=p.avg_price_usd,
            current_price_usd=p.current_price_usd,
            # Preservar yield enriquecido por yield_updater; si no hay, usar el del ALYC
            annual_yield_pct=prior.get("annual_yield_pct") or p.annual_yield_pct,
            snapshot_date=today,
            is_active=True,
            ppc_ars=p.ppc_ars,
            purchase_fx_rate=Decimal(str(round(purchase_fx, 2))),
            current_value_ars=p.valorizado_ars,
            # Preservar external_id/fci_categoria si ya estaban resueltos
            external_id=prior.get("external_id") or fci_ext_id,
            fci_categoria=prior.get("fci_categoria") or fci_cat,
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
        logger.info(
            "Budget fx_rate actualizado a MEP=%.2f para user %s", current_mep, user_id
        )

    # ── Cash disponible IOL ──────────────────────────────────────────────────
    logger.info("CASH_IOL: iniciando sección cash para user %s", user_id)
    try:
        db.query(Position).filter(
            Position.ticker.in_(["CASH_IOL", "CASH_IOL_USD"]),
            Position.user_id == user_id,
        ).update({"is_active": False})

        mep_dec = Decimal(str(current_mep))
        cash = client.get_cash_balances()
        cash_ars = cash["ars"]
        cash_usd_direct = cash["usd"]

        if cash_ars > 0:
            cash_usd = cash_ars / mep_dec if mep_dec > 0 else Decimal("0")
            db.add(
                Position(
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
                )
            )
            logger.info(
                "CASH_IOL: guardado ARS %.2f → USD %.2f",
                float(cash_ars),
                float(cash_usd),
            )
            synced += 1

        if cash_usd_direct > 0:
            db.add(
                Position(
                    user_id=user_id,
                    ticker="CASH_IOL_USD",
                    description="Saldo disponible en dólares · IOL",
                    asset_type="CASH",
                    source="IOL",
                    quantity=Decimal("1"),
                    avg_purchase_price_usd=cash_usd_direct,
                    current_price_usd=cash_usd_direct,
                    annual_yield_pct=Decimal("0"),
                    snapshot_date=today,
                    is_active=True,
                    ppc_ars=cash_usd_direct * mep_dec if mep_dec > 0 else Decimal("0"),
                    purchase_fx_rate=mep_dec,
                    current_value_ars=(
                        cash_usd_direct * mep_dec if mep_dec > 0 else Decimal("0")
                    ),
                )
            )
            logger.info("CASH_IOL_USD: guardado USD %.2f", float(cash_usd_direct))
            synced += 1

    except Exception as e:
        logger.error("CASH_IOL: error en sección cash: %s", e, exc_info=True)

    # Invalidar cache de freedom score para que el próximo request incluya el cash
    try:
        from app.routers.portfolio import _invalidate_score_cache

        _invalidate_score_cache(user_id)
    except Exception:
        pass

    db.flush()

    # ── Reconstrucción histórica de snapshots (best-effort) ──────────────────
    snapshots_created = 0
    try:
        from app.services.historical_reconstructor import reconstruct_portfolio_history

        active_positions = (
            db.query(Position)
            .filter(
                Position.is_active == True,
                Position.user_id == user_id,
                Position.source == "IOL",
            )
            .all()
        )
        snapshots_created = reconstruct_portfolio_history(
            client, db, user_id, active_positions
        )
        if snapshots_created > 0:
            db.flush()
    except Exception as e:
        logger.warning("Reconstruct histórico falló (no crítico): %s", e, exc_info=True)

    # Enriquecer yields inmediatamente post-sync (no esperar al scheduler de 17:30)
    try:
        from app.services.yield_updater import update_yields

        mep_dec = Decimal(str(current_mep))
        yields_updated = update_yields(db, mep=mep_dec)
        logger.info(
            "_sync_iol: yield_updater post-sync → %d posiciones actualizadas",
            yields_updated,
        )
    except Exception as e:
        logger.warning("_sync_iol: yield_updater post-sync falló (no crítico): %s", e)

    return {
        "positions_synced": synced,
        "months_synced": months_synced,
        "mep": round(current_mep, 2),
        "snapshots_reconstructed": snapshots_created,
    }


def _get_purchase_mep_from_operations(client: IOLClient) -> dict[str, float]:
    """
    Para cada ticker con compras en IOL, busca la fecha de la primera/principal
    compra y obtiene el MEP histórico de ese día.
    Retorna {ticker: mep_al_momento_de_compra}.
    """
    from datetime import timedelta

    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime(
        "%Y-%m-%d"
    )
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
        p.ticker: (
            float(p.quantity * p.current_price_usd * Decimal(str(client._get_mep())))
            / float(p.quantity)
            if p.quantity > 0
            else 0
        )
        for p in portfolio
    }

    result: dict[str, float] = {}
    for ticker, fecha in ticker_dates.items():
        # Buscar si es CEDEAR para usar CCL implícito
        pos = next((p for p in portfolio if p.ticker == ticker), None)
        if pos and pos.asset_type == "CEDEAR":
            price_ars = price_ars_by_ticker.get(ticker, 0)
            if price_ars > 0:
                ccl = client.get_cedear_implicit_ccl(
                    ticker, price_ars, purchase_date=fecha
                )
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

    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime(
        "%Y-%m-%d"
    )
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
        existing = (
            db.query(InvestmentMonth)
            .filter(
                InvestmentMonth.month == month_date,
                InvestmentMonth.user_id == user_id,
            )
            .first()
        )
        if not existing:
            note = ", ".join(set(data["tickers"]))[:200]
            db.add(
                InvestmentMonth(
                    user_id=user_id,
                    month=month_date,
                    amount_ars=Decimal(str(round(data["amount_ars"], 2))),
                    source="IOL",
                    note=note,
                )
            )
            synced += 1

    return synced


# ── PPI (Portfolio Personal Inversiones) ──────────────────────────────────────


class ConnectPPIRequest(BaseModel):
    public_key: str
    private_key: str
    account_number: str


@router.post("/ppi/connect")
def connect_ppi(
    body: ConnectPPIRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Autentica con PPI, guarda credenciales y hace el primer sync del portafolio.
    Credenciales: public_key + private_key (se generan en PPI → Gestiones → API).
    account_number: número de cuenta PPI (obtenible con GET /ppi/accounts).
    """
    client = PPIClient(body.public_key, body.private_key)
    try:
        client.authenticate()
    except PPIAuthError as e:
        _log_error(db, current_user, "PPI", "connect", e)
        db.commit()
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        _log_error(db, current_user, "PPI", "connect", e)
        db.commit()
        raise HTTPException(
            status_code=502, detail=f"Error conectando con PPI: {str(e)}"
        )

    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "PPI",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration:
        integration = Integration(
            user_id=current_user,
            provider="PPI",
            provider_type="ALYC",
        )
        db.add(integration)

    # Formato: "public_key:private_key:account_number"
    integration.encrypted_credentials = (
        f"{body.public_key}:{body.private_key}:{body.account_number}"
    )
    integration.is_connected = True
    integration.last_error = ""
    db.flush()

    sync_error = ""
    positions_synced = 0
    try:
        result = _sync_ppi(client, body.account_number, db, current_user)
        positions_synced = result["positions_synced"]
    except Exception as e:
        sync_error = str(e)[:200]
        _log_error(db, current_user, "PPI", "sync", e)
        logger.warning(
            "connect_ppi: sync inicial falló (conexión guardada igual): %s", sync_error
        )

    integration.last_synced_at = datetime.utcnow()
    if sync_error:
        integration.last_error = f"Sync inicial: {sync_error}"
    db.commit()

    msg = f"PPI conectado. {positions_synced} posiciones sincronizadas."
    if sync_error:
        msg += " El portafolio no pudo sincronizarse aún — intentá sincronizar manualmente en unos minutos."
    return {
        "connected": True,
        "positions_synced": positions_synced,
        "message": msg,
    }


@router.post("/ppi/sync")
def sync_ppi(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Re-sincroniza el portafolio PPI con las credenciales guardadas."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "PPI",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="PPI no está conectado")

    try:
        pub, priv, acct = integration.encrypted_credentials.split(":", 2)
        client = PPIClient(pub, priv)
        result = _sync_ppi(client, acct, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        return {"positions_synced": result["positions_synced"]}
    except Exception as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/ppi/accounts")
def list_ppi_accounts(
    public_key: str,
    private_key: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Lista las cuentas disponibles para el par de claves dado.
    Útil para obtener el account_number antes de conectar.
    """
    client = PPIClient(public_key, private_key)
    try:
        client.authenticate()
        accounts = client.get_accounts()
        return {"accounts": accounts}
    except PPIAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/ppi/debug")
def debug_ppi(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Muestra la respuesta raw de PPI sin modificar la DB. Para diagnóstico."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "PPI",
            Integration.user_id == current_user,
            Integration.is_connected == True,
        )
        .first()
    )
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(status_code=400, detail="PPI no está conectado")

    try:
        pub, priv, acct = integration.encrypted_credentials.split(":", 2)
        client = PPIClient(pub, priv)
        mep = client._get_mep()
        raw = client._get(
            "/api/v1/Account/GetBalanceAndPositions",
            params={"accountNumber": acct},
        )
        cash = client.get_cash_balance(acct)

        grouped = raw.get("groupedInstruments", [])
        items = []
        total_usd = 0.0
        for group in grouped:
            for inst in group.get("instruments", []):
                qty = float(inst.get("quantity", inst.get("cantidad", 0)))
                amt = float(inst.get("amount", inst.get("monto", 0)))
                total_usd += amt / mep if mep else 0
                items.append(
                    {
                        "group": group.get("name"),
                        "ticker": inst.get("ticker"),
                        "quantity": qty,
                        "price": inst.get("price", inst.get("precio")),
                        "amount_ars": round(amt, 2),
                        "amount_usd": round(amt / mep, 2) if mep else 0,
                    }
                )

        return {
            "mep": round(mep, 2),
            "account_number": acct,
            "total_usd_estimated": round(total_usd, 2),
            "positions_count": len(items),
            "positions": items,
            "cash_ars": float(cash["ars"]),
            "cash_usd": float(cash["usd"]),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/ppi/disconnect")
def disconnect_ppi(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Desconecta PPI: borra credenciales y desactiva posiciones."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "PPI",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integración PPI no encontrada")

    integration.encrypted_credentials = ""
    integration.is_connected = False
    integration.last_error = ""

    db.query(Position).filter(
        Position.user_id == current_user,
        Position.source == "PPI",
        Position.is_active == True,
    ).update({"is_active": False})

    db.commit()
    return {"disconnected": True}


def _sync_ppi(
    client: PPIClient, account_number: str, db: Session, user_id: str
) -> dict:
    """Trae posiciones de PPI y las upserta en la DB."""
    current_mep = client._get_mep()
    positions = client.get_portfolio(account_number)

    # Leer enriquecimiento previo ANTES de desactivar — preserva yield real y FCI metadata
    enrichment = _get_enrichment(db, user_id, "PPI")

    # Desactivar posiciones PPI anteriores (evitar duplicados en re-sync)
    db.query(Position).filter(
        Position.source == "PPI",
        Position.is_active == True,
        Position.user_id == user_id,
    ).update({"is_active": False})

    today = date.today()
    synced = 0

    # MEP histórico por ticker para cost-basis real
    purchase_mep_by_ticker = _get_purchase_mep_ppi(client, account_number)

    for p in positions:
        if p.quantity <= 0:
            continue

        purchase_fx = purchase_mep_by_ticker.get(p.ticker, 0.0)
        if not purchase_fx:
            purchase_fx = current_mep

        prior = enrichment.get(p.ticker, {})
        fci_ext_id, fci_cat = (
            _fci_external_id(p.description, ticker=p.ticker) if p.asset_type == "FCI" else (None, None)
        )
        db.add(
            Position(
                user_id=user_id,
                ticker=p.ticker,
                description=p.description,
                asset_type=p.asset_type,
                source="PPI",
                quantity=p.quantity,
                avg_purchase_price_usd=p.avg_price_usd,
                current_price_usd=p.current_price_usd,
                # Preservar yield enriquecido por yield_updater; si no hay, usar el del ALYC
                annual_yield_pct=prior.get("annual_yield_pct") or p.annual_yield_pct,
                snapshot_date=today,
                is_active=True,
                ppc_ars=p.ppc_ars,
                purchase_fx_rate=Decimal(str(round(purchase_fx, 2))),
                current_value_ars=p.current_value_ars,
                # Preservar external_id/fci_categoria si ya estaban resueltos
                external_id=prior.get("external_id") or fci_ext_id,
                fci_categoria=prior.get("fci_categoria") or fci_cat,
            )
        )
        synced += 1

    # Cash disponible PPI (ARS y USD por separado)
    try:
        cash = client.get_cash_balance(account_number)
        mep_dec = Decimal(str(current_mep))

        cash_ars = cash["ars"]
        if cash_ars > 0:
            db.query(Position).filter(
                Position.ticker == "CASH_PPI_ARS",
                Position.user_id == user_id,
            ).update({"is_active": False})
            cash_usd = cash_ars / mep_dec if mep_dec > 0 else Decimal("0")
            db.add(
                Position(
                    user_id=user_id,
                    ticker="CASH_PPI_ARS",
                    description="Saldo disponible en pesos · PPI",
                    asset_type="CASH",
                    source="PPI",
                    quantity=Decimal("1"),
                    avg_purchase_price_usd=cash_usd,
                    current_price_usd=cash_usd,
                    annual_yield_pct=Decimal("0"),
                    snapshot_date=today,
                    is_active=True,
                    ppc_ars=cash_ars,
                    purchase_fx_rate=mep_dec,
                    current_value_ars=cash_ars,
                )
            )
            synced += 1
            logger.info(
                "PPI cash ARS: %.2f → USD %.2f", float(cash_ars), float(cash_usd)
            )

        cash_usd_direct = cash["usd"]
        if cash_usd_direct > 0:
            db.query(Position).filter(
                Position.ticker == "CASH_PPI_USD",
                Position.user_id == user_id,
            ).update({"is_active": False})
            db.add(
                Position(
                    user_id=user_id,
                    ticker="CASH_PPI_USD",
                    description="Saldo disponible en dólares · PPI",
                    asset_type="CASH",
                    source="PPI",
                    quantity=Decimal("1"),
                    avg_purchase_price_usd=cash_usd_direct,
                    current_price_usd=cash_usd_direct,
                    annual_yield_pct=Decimal("0"),
                    snapshot_date=today,
                    is_active=True,
                    ppc_ars=Decimal("0"),
                    purchase_fx_rate=mep_dec,
                    current_value_ars=cash_usd_direct * mep_dec,
                )
            )
            synced += 1
            logger.info("PPI cash USD: %.2f", float(cash_usd_direct))

    except Exception as e:
        logger.error("PPI: error al sincronizar cash: %s", e, exc_info=True)

    # Meses de inversión PPI
    months_synced = _sync_investment_months_ppi(client, account_number, db, user_id)

    # Invalidar cache de freedom score
    try:
        from app.routers.portfolio import _invalidate_score_cache

        _invalidate_score_cache(user_id)
    except Exception:
        pass

    # Enriquecer yields inmediatamente post-sync (no esperar al scheduler de 17:30)
    try:
        from app.services.yield_updater import update_yields

        mep_dec = Decimal(str(current_mep))
        yields_updated = update_yields(db, mep=mep_dec)
        logger.info(
            "_sync_ppi: yield_updater post-sync → %d posiciones actualizadas",
            yields_updated,
        )
    except Exception as e:
        logger.warning("_sync_ppi: yield_updater post-sync falló (no crítico): %s", e)

    db.flush()
    return {
        "positions_synced": synced,
        "months_synced": months_synced,
        "mep": round(current_mep, 2),
    }


def _get_purchase_mep_ppi(client: PPIClient, account_number: str) -> dict[str, float]:
    """
    MEP histórico al momento de compra de cada ticker PPI.
    Mismo patrón que _get_purchase_mep_from_operations para IOL.
    PPI: operaciones con campos date/ticker/type (COMPRA/VENTA).
    """
    from datetime import timedelta

    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime(
        "%Y-%m-%d"
    )
    operations = client.get_operations(account_number, fecha_desde=fecha_desde)

    ticker_dates: dict[str, str] = {}
    for op in operations:
        tipo = str(op.get("type", op.get("tipo", ""))).upper()
        if "COMPRA" not in tipo and "BUY" not in tipo:
            continue
        raw_date = op.get("date", op.get("fecha", op.get("fechaOrden", "")))
        ticker = str(op.get("ticker", op.get("simbolo", ""))).upper()
        if raw_date and ticker:
            fecha = str(raw_date)[:10]
            if ticker not in ticker_dates or fecha > ticker_dates[ticker]:
                ticker_dates[ticker] = fecha

    result: dict[str, float] = {}
    for ticker, fecha in ticker_dates.items():
        mep = client.get_historical_mep(fecha)
        result[ticker] = mep
        logger.info("PPI MEP compra %s en %s = %.2f", ticker, fecha, mep)

    return result


def _sync_investment_months_ppi(
    client: PPIClient,
    account_number: str,
    db: Session,
    user_id: str,
) -> int:
    """Registra meses con compras PPI en investment_months."""
    from datetime import timedelta

    fecha_desde = (date.today().replace(day=1) - timedelta(days=365)).strftime(
        "%Y-%m-%d"
    )
    operations = client.get_operations(account_number, fecha_desde=fecha_desde)

    months_found: dict[date, dict] = {}
    for op in operations:
        tipo = str(op.get("type", op.get("tipo", ""))).upper()
        if "COMPRA" not in tipo and "BUY" not in tipo:
            continue
        raw_date = op.get("date", op.get("fecha", op.get("fechaOrden", "")))
        if not raw_date:
            continue
        try:
            from datetime import datetime as _dt

            op_date = _dt.fromisoformat(str(raw_date)[:10]).date()
        except ValueError:
            continue

        month_key = op_date.replace(day=1)
        monto = float(op.get("amount", op.get("monto", op.get("montoOperado", 0))) or 0)
        ticker = str(op.get("ticker", op.get("simbolo", ""))).upper()

        if month_key not in months_found:
            months_found[month_key] = {"amount_ars": 0.0, "tickers": []}
        months_found[month_key]["amount_ars"] += monto
        if ticker:
            months_found[month_key]["tickers"].append(ticker)

    synced = 0
    for month_date, data in months_found.items():
        existing = (
            db.query(InvestmentMonth)
            .filter(
                InvestmentMonth.month == month_date,
                InvestmentMonth.user_id == user_id,
            )
            .first()
        )
        if not existing:
            note = ", ".join(set(data["tickers"]))[:200]
            db.add(
                InvestmentMonth(
                    user_id=user_id,
                    month=month_date,
                    amount_ars=Decimal(str(round(data["amount_ars"], 2))),
                    source="PPI",
                    note=note,
                )
            )
            synced += 1

    return synced


# ── Cocos Capital ─────────────────────────────────────────────────────────────


class SaveCocosCredentialsRequest(BaseModel):
    email: str
    password: str
    totp_secret: str = ""


class ConnectCocosRequest(BaseModel):
    code: str


class SyncCocosRequest(BaseModel):
    code: str = ""


class UpdateCocosTotp(BaseModel):
    totp_secret: str


@router.post("/cocos/save-credentials")
def save_cocos_credentials(
    body: SaveCocosCredentialsRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Guarda email + password + TOTP secret sin autenticar todavía.
    Permite que el paso de 2FA solo necesite el código de 6 dígitos.
    """
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "COCOS",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration:
        integration = Integration(
            user_id=current_user,
            provider="COCOS",
            provider_type="ALYC",
        )
        db.add(integration)

    integration.encrypted_credentials = (
        f"{body.email}:{body.password}:{body.totp_secret}"
    )
    integration.is_connected = False
    db.commit()
    return {"saved": True}


@router.post("/cocos/connect")
def connect_cocos(
    body: ConnectCocosRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Conecta Cocos usando las credenciales ya guardadas + el código 2FA del momento.
    Llamar save-credentials primero.
    """
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "COCOS",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(
            status_code=400, detail="Primero guardá tus credenciales de Cocos."
        )

    parts = integration.encrypted_credentials.split(":", 2)
    if len(parts) < 2:
        raise HTTPException(
            status_code=400, detail="Credenciales incompletas. Volvé al paso 1."
        )
    email, password = parts[0], parts[1]
    totp_secret = parts[2] if len(parts) == 3 else ""

    client = CocosClient(email, password, totp_secret=totp_secret)
    try:
        client.authenticate(code=body.code)
    except CocosAuthError as e:
        raise HTTPException(
            status_code=401, detail=f"Error autenticando con Cocos: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Error conectando con Cocos: {str(e)}"
        )

    integration.is_connected = True
    integration.last_error = ""
    db.flush()

    result = _sync_cocos(client, db, current_user)
    integration.last_synced_at = datetime.utcnow()
    db.commit()

    try:
        _upsert_today_snapshot(db, current_user)
        db.commit()
    except Exception as e:
        logger.warning("connect_cocos: snapshot upsert falló (no crítico): %s", e)
        db.rollback()

    auto_sync = bool(totp_secret)
    return {
        "connected": True,
        "auto_sync_enabled": auto_sync,
        "positions_synced": result["positions_synced"],
        "message": (
            f"Cocos conectado. {result['positions_synced']} posiciones sincronizadas. "
            + (
                "Auto-sync habilitado."
                if auto_sync
                else "Sync manual — agregá el TOTP secret para auto-sync."
            )
        ),
    }


@router.post("/cocos/sync")
def sync_cocos(
    body: SyncCocosRequest = SyncCocosRequest(),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Re-sincroniza Cocos. Si tiene TOTP secret → auto. Si no → requiere código en body.
    """
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "COCOS",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration or not integration.is_connected:
        raise HTTPException(status_code=400, detail="Cocos no está conectado")

    try:
        parts = (integration.encrypted_credentials or "").split(":", 2)
        if len(parts) < 2:
            raise CocosAuthError("Credenciales Cocos inválidas en DB")
        email, password = parts[0], parts[1]
        totp_secret = parts[2] if len(parts) == 3 else ""

        if not totp_secret and not body.code:
            raise HTTPException(
                status_code=400,
                detail="Cocos requiere código 2FA. Pasá 'code' en el body o configurá el TOTP secret.",
            )

        client = CocosClient(email, password, totp_secret=totp_secret)
        client.authenticate(code=body.code)
        result = _sync_cocos(client, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()

        try:
            _upsert_today_snapshot(db, current_user)
            db.commit()
        except Exception as snap_err:
            logger.warning(
                "sync_cocos: snapshot upsert falló (no crítico): %s", snap_err
            )
            db.rollback()

        return {"positions_synced": result["positions_synced"]}
    except HTTPException:
        raise
    except CocosAuthError as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        integration.last_error = str(e)[:200]
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cocos/update-totp")
def update_cocos_totp(
    body: UpdateCocosTotp,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Agrega el TOTP secret sin reconectar. Habilita auto-sync."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "COCOS",
            Integration.user_id == current_user,
            Integration.is_connected == True,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=400, detail="Cocos no está conectado")

    try:
        import pyotp

        pyotp.TOTP(body.totp_secret).now()
    except Exception:
        raise HTTPException(
            status_code=400, detail="TOTP secret inválido. Debe ser un código BASE32."
        )

    parts = (integration.encrypted_credentials or "").split(":", 2)
    email = parts[0] if len(parts) > 0 else ""
    password = parts[1] if len(parts) > 1 else ""
    integration.encrypted_credentials = f"{email}:{password}:{body.totp_secret}"
    db.commit()
    return {
        "auto_sync_enabled": True,
        "message": "TOTP secret guardado. Auto-sync habilitado.",
    }


@router.post("/cocos/disconnect")
def disconnect_cocos(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Desconecta Cocos: borra credenciales y desactiva posiciones."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == "COCOS",
            Integration.user_id == current_user,
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integración Cocos no encontrada")

    integration.encrypted_credentials = ""
    integration.is_connected = False
    integration.last_error = ""

    db.query(Position).filter(
        Position.user_id == current_user,
        Position.source == "COCOS",
        Position.is_active == True,
    ).update({"is_active": False})

    db.commit()
    return {"disconnected": True}


@router.get("/discovery")
def get_discovery(
    provider: str | None = None,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Lista instrument_types desconocidos capturados en syncs.
    Útil para iterar el mapper sin perder información.
    Filtrá por provider= para ver solo los de un ALYC específico.
    """
    q = db.query(IntegrationDiscovery)
    if provider:
        q = q.filter(IntegrationDiscovery.provider == provider.upper())
    items = q.order_by(
        IntegrationDiscovery.provider,
        IntegrationDiscovery.seen_count.desc(),
    ).all()
    return [
        {
            "provider": i.provider,
            "raw_instrument_type": i.raw_instrument_type,
            "ticker": i.ticker,
            "name": i.name,
            "seen_count": i.seen_count,
            "first_seen_at": i.first_seen_at,
            "last_seen_at": i.last_seen_at,
            "raw_data": json.loads(i.raw_data) if i.raw_data else {},
        }
        for i in items
    ]


def _upsert_today_snapshot(db: Session, user_id: str) -> None:
    """
    Crea o actualiza el snapshot de hoy para un usuario específico.
    Siempre guarda fx_mep: budget → dolarapi.com → 1430.
    """
    from app.services.freedom_calculator import calculate_freedom_score
    from app.services.mep import get_mep

    positions = (
        db.query(Position)
        .filter(
            Position.is_active == True,
            Position.user_id == user_id,
        )
        .all()
    )
    if not positions:
        return

    budget = (
        db.query(BudgetConfig)
        .filter(
            BudgetConfig.user_id == user_id,
        )
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )

    monthly_expenses = budget.total_monthly_usd if budget else Decimal("2000")
    fx_mep = get_mep(budget)  # nunca retorna 0

    score = calculate_freedom_score(positions, monthly_expenses)
    cost_basis = sum(p.cost_basis_usd for p in positions)
    today = date.today()

    existing = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_date == today,
        )
        .first()
    )

    if existing:
        existing.total_usd = score["portfolio_total_usd"]
        existing.monthly_return_usd = score["monthly_return_usd"]
        existing.positions_count = len(positions)
        existing.cost_basis_usd = cost_basis
        existing.fx_mep = fx_mep
    else:
        db.add(
            PortfolioSnapshot(
                user_id=user_id,
                snapshot_date=today,
                total_usd=score["portfolio_total_usd"],
                monthly_return_usd=score["monthly_return_usd"],
                positions_count=len(positions),
                fx_mep=fx_mep,
                cost_basis_usd=cost_basis,
            )
        )

    logger.info(
        "_upsert_today_snapshot: snapshot %s user=%s USD=%.2f MEP=%.0f",
        today,
        user_id,
        float(score["portfolio_total_usd"]),
        float(fx_mep),
    )


def _record_discovery(db: Session, provider: str, pos, user_id: str) -> None:
    """Upserta un instrumento desconocido en IntegrationDiscovery para iterar el mapper."""
    existing = (
        db.query(IntegrationDiscovery)
        .filter(
            IntegrationDiscovery.provider == provider,
            IntegrationDiscovery.raw_instrument_type == pos.raw_instrument_type,
            IntegrationDiscovery.ticker == pos.ticker,
        )
        .first()
    )

    if existing:
        existing.seen_count += 1
        existing.last_seen_at = datetime.utcnow()
        logger.info(
            "Discovery: %s/%s ya registrado (seen=%d)",
            provider,
            pos.raw_instrument_type,
            existing.seen_count,
        )
    else:
        db.add(
            IntegrationDiscovery(
                provider=provider,
                raw_instrument_type=pos.raw_instrument_type,
                ticker=pos.ticker,
                name=pos.description,
                raw_data=json.dumps(pos.raw_data, default=str),
                user_id=user_id,
            )
        )
        logger.warning(
            "Discovery: nuevo instrument_type '%s' ticker=%s — guardado para mapear",
            pos.raw_instrument_type,
            pos.ticker,
        )


def _sync_cocos(client: CocosClient, db: Session, user_id: str) -> dict:
    """
    Trae posiciones y cash de Cocos.
    - asset_type conocido → Position (portafolio visible).
    - asset_type None (instrument_type desconocido) → IntegrationDiscovery (skip portafolio).
    """
    positions = client.get_positions()
    cash = client.get_cash()

    # Leer enriquecimiento previo ANTES de desactivar — preserva yield real, FCI metadata y MEP
    enrichment = _get_enrichment(db, user_id, "COCOS")
    existing_fx: dict[str, Decimal] = {
        row.ticker: row.purchase_fx_rate
        for row in db.query(Position.ticker, Position.purchase_fx_rate)
        .filter(
            Position.source == "COCOS",
            Position.user_id == user_id,
            Position.is_active == True,
            Position.purchase_fx_rate > 0,
        )
        .all()
    }

    db.query(Position).filter(
        Position.source == "COCOS",
        Position.is_active == True,
        Position.user_id == user_id,
    ).update({"is_active": False})

    today = date.today()
    synced = 0
    discovered = 0

    for p in positions:
        if p.asset_type is None:
            _record_discovery(db, "COCOS", p, user_id)
            discovered += 1
            continue

        # Preservar MEP histórico si ya conocíamos esta posición.
        if p.ticker in existing_fx:
            purchase_fx_rate = existing_fx[p.ticker]
        elif p.ppc_ars > 0 and p.avg_purchase_price_usd > 0:
            purchase_fx_rate = p.ppc_ars / p.avg_purchase_price_usd
        else:
            purchase_fx_rate = Decimal("0")

        prior = enrichment.get(p.ticker, {})
        fci_ext_id, fci_cat = (
            _fci_external_id(p.description, ticker=p.ticker) if p.asset_type == "FCI" else (None, None)
        )
        db.add(
            Position(
                user_id=user_id,
                ticker=p.ticker,
                description=p.description,
                asset_type=p.asset_type,
                source="COCOS",
                quantity=p.quantity,
                avg_purchase_price_usd=p.avg_purchase_price_usd,
                current_price_usd=p.current_price_usd,
                # Preservar yield enriquecido por yield_updater; si no hay, usar el del ALYC
                annual_yield_pct=prior.get("annual_yield_pct") or p.annual_yield_pct,
                snapshot_date=today,
                is_active=True,
                ppc_ars=p.ppc_ars,
                purchase_fx_rate=purchase_fx_rate,
                current_value_ars=p.current_value_ars,
                # Preservar external_id/fci_categoria si ya estaban resueltos
                external_id=prior.get("external_id") or fci_ext_id,
                fci_categoria=prior.get("fci_categoria") or fci_cat,
            )
        )
        synced += 1

    if cash["ars"] > 0:
        mep = client._get_mep()
        mep_dec = Decimal(str(mep))
        cash_usd = cash["ars"] / mep_dec if mep_dec > 0 else Decimal("0")
        db.add(
            Position(
                user_id=user_id,
                ticker="CASH_COCOS",
                description="Saldo disponible en pesos · Cocos",
                asset_type="CASH",
                source="COCOS",
                quantity=Decimal("1"),
                avg_purchase_price_usd=cash_usd,
                current_price_usd=cash_usd,
                annual_yield_pct=Decimal("0"),
                snapshot_date=today,
                is_active=True,
                ppc_ars=cash["ars"],
                purchase_fx_rate=mep_dec,
                current_value_ars=cash["ars"],
            )
        )
        synced += 1

    if cash["usd"] > 0:
        db.add(
            Position(
                user_id=user_id,
                ticker="CASH_COCOS_USD",
                description="Saldo disponible en dólares · Cocos",
                asset_type="CASH",
                source="COCOS",
                quantity=Decimal("1"),
                avg_purchase_price_usd=cash["usd"],
                current_price_usd=cash["usd"],
                annual_yield_pct=Decimal("0"),
                snapshot_date=today,
                is_active=True,
                ppc_ars=Decimal("0"),
                purchase_fx_rate=Decimal("0"),
                current_value_ars=Decimal("0"),
            )
        )
        synced += 1

    # Marcar el mes actual como invertido si hay posiciones con valor real.
    # No podemos reconstruir meses históricos (Cocos no expone operaciones),
    # pero sí podemos confirmar que el usuario está invertido este mes.
    _mark_cocos_investment_month(db, positions, user_id, today)

    # Enriquecer yields inmediatamente post-sync (no esperar al scheduler de 17:30)
    try:
        from app.services.yield_updater import update_yields
        from app.services.mep import get_mep

        mep_dec = Decimal(str(get_mep()))
        yields_updated = update_yields(db, mep=mep_dec)
        logger.info(
            "_sync_cocos: yield_updater post-sync → %d posiciones actualizadas",
            yields_updated,
        )
    except Exception as e:
        logger.warning("_sync_cocos: yield_updater post-sync falló (no crítico): %s", e)

    db.flush()
    if discovered:
        logger.info(
            "_sync_cocos: %d posiciones, %d instrument_types desconocidos → discovery",
            synced,
            discovered,
        )
    return {"positions_synced": synced, "discovered": discovered}


def _mark_cocos_investment_month(
    db: Session, positions, user_id: str, today: date
) -> None:
    """
    Registra el mes actual como mes de inversión si el usuario tiene posiciones
    Cocos con valor real (ppc_ars > 0).
    No es historial — es confirmación de que está invertido en el mes del sync.
    Cocos no expone operaciones históricas, así que meses anteriores quedan sin datos.
    """
    has_real_positions = any(
        p.asset_type is not None and p.ppc_ars > 0 for p in positions
    )
    if not has_real_positions:
        return

    month_key = today.replace(day=1)
    existing = (
        db.query(InvestmentMonth)
        .filter(
            InvestmentMonth.user_id == user_id,
            InvestmentMonth.month == month_key,
        )
        .first()
    )

    total_ars = sum(
        p.ppc_ars * p.quantity for p in positions if p.asset_type is not None
    )

    if existing:
        # Si ya existe (posiblemente de IOL/PPI), no sobreescribir — solo log
        logger.info(
            "_mark_cocos_investment_month: mes %s ya registrado (source=%s) — skip",
            month_key,
            existing.source,
        )
    else:
        db.add(
            InvestmentMonth(
                user_id=user_id,
                month=month_key,
                amount_ars=total_ars,
                amount_usd=Decimal("0"),  # sin MEP confiable para el mes histórico
                source="COCOS",
                note="Sync automático Cocos — posiciones activas al momento del sync",
            )
        )
        logger.info(
            "_mark_cocos_investment_month: mes %s marcado como invertido (ARS %.0f)",
            month_key,
            float(total_ars),
        )


# ── Binance ───────────────────────────────────────────────────────────────────


class BinanceConnectRequest(BaseModel):
    api_key: str
    secret_key: str


def _sync_binance(client: BinanceClient, db: Session, user_id: str) -> dict:
    """Trae posiciones de Binance y hace upsert en DB. Retorna positions_synced."""
    from app.services.mep import get_mep

    mep = float(get_mep())
    positions = client.get_positions()

    # Desactivar posiciones Binance anteriores
    db.query(Position).filter(
        Position.source == "BINANCE",
        Position.is_active == True,  # noqa: E712
        Position.user_id == user_id,
    ).update({"is_active": False})

    today = date.today()
    synced = 0

    for p in positions:
        ppc_usd = client._get_ppc_usd(p.ticker, mep=mep)
        current_value_ars = Decimal(
            str(float(p.quantity) * float(p.current_price_usd) * mep)
        )

        db.add(
            Position(
                user_id=user_id,
                ticker=p.ticker,
                description=p.ticker,
                asset_type=p.asset_type,
                source="BINANCE",
                quantity=p.quantity,
                avg_purchase_price_usd=Decimal(str(round(ppc_usd, 6))),
                current_price_usd=p.current_price_usd,
                annual_yield_pct=p.annual_yield_pct,
                snapshot_date=today,
                is_active=True,
                ppc_ars=Decimal("0"),
                purchase_fx_rate=Decimal(str(round(mep, 2))),
                current_value_ars=current_value_ars,
            )
        )
        synced += 1

    logger.info("_sync_binance: %d posiciones para user=%s", synced, user_id)
    return {"positions_synced": synced}


def _sync_binance_history(client: BinanceClient, db: Session, user_id: str) -> int:
    """
    Crea PortfolioSnapshots históricos desde accountSnapshot de Binance.
    Usa upsert aditivo — suma al snapshot existente si ya hay uno del mismo día.
    """
    from app.services.crypto_prices import get_price_usd
    from app.services.mep import get_mep

    mep = float(get_mep())
    history = client.get_snapshot_history()
    if not history:
        return 0

    # Precios actuales para los assets que aparecen en snapshots
    all_assets: set[str] = set()
    for snap in history:
        all_assets.update(snap["balances"].keys())

    from app.services.binance_client import _COINGECKO_ID, _STABLECOINS

    price_cache: dict[str, float] = {}
    for asset in all_assets:
        if asset in _STABLECOINS:
            price_cache[asset] = 1.0
        elif asset in _COINGECKO_ID:
            p = get_price_usd(_COINGECKO_ID[asset])
            if p:
                price_cache[asset] = p

    created = 0
    for snap in history:
        snap_date = snap["date"]
        crypto_usd = sum(
            qty * price_cache.get(asset, 0.0) for asset, qty in snap["balances"].items()
        )
        if crypto_usd <= 0:
            continue

        existing = (
            db.query(PortfolioSnapshot)
            .filter(
                PortfolioSnapshot.user_id == user_id,
                PortfolioSnapshot.snapshot_date == snap_date,
            )
            .first()
        )

        if existing:
            existing.total_usd += Decimal(str(round(crypto_usd, 2)))
            existing.positions_count += len(snap["balances"])
        else:
            db.add(
                PortfolioSnapshot(
                    user_id=user_id,
                    snapshot_date=snap_date,
                    total_usd=Decimal(str(round(crypto_usd, 2))),
                    monthly_return_usd=Decimal("0"),
                    positions_count=len(snap["balances"]),
                    fx_mep=Decimal(str(round(mep, 2))),
                    cost_basis_usd=Decimal("0"),
                )
            )
            created += 1

    try:
        db.flush()
    except Exception as e:
        db.rollback()
        logger.warning("_sync_binance_history flush falló: %s", e)

    logger.info(
        "_sync_binance_history: %d nuevos snapshots para user=%s", created, user_id
    )
    return created


@router.post("/binance/connect")
def connect_binance(
    body: BinanceConnectRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Valida API Key + Secret, primer sync de posiciones e historial 30d."""
    client = BinanceClient(api_key=body.api_key, secret=body.secret_key)
    try:
        client.validate()
    except BinanceAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == current_user,
            Integration.provider == "BINANCE",
        )
        .first()
    )
    if not integration:
        integration = Integration(
            user_id=current_user,
            provider="BINANCE",
            provider_type="EXCHANGE",
            is_active=True,
        )
        db.add(integration)

    integration.encrypted_credentials = f"{body.api_key}:{body.secret_key}"
    integration.is_connected = True
    integration.last_error = ""

    result = _sync_binance(client, db, current_user)
    _sync_binance_history(client, db, current_user)
    integration.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "connected": True,
        "positions_synced": result["positions_synced"],
        "message": f"Conectado. {result['positions_synced']} posiciones sincronizadas.",
    }


@router.post("/binance/sync")
def sync_binance(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Re-sync de posiciones Binance."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == current_user,
            Integration.provider == "BINANCE",
            Integration.is_connected == True,  # noqa: E712
        )
        .first()
    )
    if not integration or not integration.encrypted_credentials:
        raise HTTPException(status_code=404, detail="Binance no conectado")

    api_key, secret = integration.encrypted_credentials.split(":", 1)
    client = BinanceClient(api_key=api_key, secret=secret)
    try:
        result = _sync_binance(client, db, current_user)
        integration.last_synced_at = datetime.utcnow()
        integration.last_error = ""
        db.commit()
        return {"positions_synced": result["positions_synced"]}
    except BinanceAuthError as e:
        integration.is_connected = False
        integration.last_error = str(e)
        db.commit()
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/binance/disconnect")
def disconnect_binance(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Desconecta Binance y desactiva todas sus posiciones."""
    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == current_user,
            Integration.provider == "BINANCE",
        )
        .first()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Binance no conectado")

    integration.is_connected = False
    integration.encrypted_credentials = ""
    integration.last_error = ""

    db.query(Position).filter(
        Position.user_id == current_user,
        Position.source == "BINANCE",
    ).update({"is_active": False})

    db.commit()
    return {"disconnected": True}


# ── Diagnóstico de errores multi-usuario ─────────────────────────────────────


@router.get("/errors")
def get_integration_errors(
    provider: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """
    Retorna los últimos errores de integraciones del usuario actual.
    Útil para auto-diagnóstico y para que soporte identifique qué falló.
    """
    q = db.query(IntegrationErrorLog).filter(
        IntegrationErrorLog.user_id == current_user,
    )
    if provider:
        q = q.filter(IntegrationErrorLog.provider == provider.upper())
    errors = q.order_by(IntegrationErrorLog.occurred_at.desc()).limit(limit).all()
    return [
        {
            "provider": e.provider,
            "operation": e.operation,
            "error_code": e.error_code,
            "error_message": e.error_message,
            "occurred_at": e.occurred_at.isoformat(),
        }
        for e in errors
    ]
