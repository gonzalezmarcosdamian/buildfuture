"""
Tests de integración de los endpoints PPI.
Usa TestClient de FastAPI + DB SQLite en memoria.

Los tests de lógica de negocio (_sync_ppi, _get_purchase_mep_ppi, etc.)
están en test_ppi_sync.py. Acá se testea que los endpoints:
  - Llaman a las funciones correctas con los parámetros correctos
  - Propagan errores en los HTTP status codes adecuados
  - No modifican la DB en endpoints de lectura (debug)

Setup: se parchea startup() para evitar que el TestClient toque la DB de prod.
"""
import os
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Integration, Position
from app.database import get_db
from app.auth import get_current_user
from app.services.ppi_client import PPIAuthError


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_engine():
    # StaticPool: todas las conexiones comparten la misma conexión subyacente.
    # Necesario con sqlite:///:memory: para que create_all y los sessions vean
    # las mismas tablas.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(db_session):
    """
    TestClient con:
    - DB inyectada (SQLite en memoria)
    - Auth fake (user_id fijo)
    - startup/shutdown patched para no tocar DB de prod
    """
    from app.main import app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: "test-user-id"

    with patch("app.main.Base.metadata.create_all"), \
         patch("app.main._run_migrations"), \
         patch("app.main.seed"), \
         patch("app.main.start_scheduler"), \
         patch("app.main.stop_scheduler"):
        yield TestClient(app, raise_server_exceptions=False)

    app.dependency_overrides.clear()


CONNECT_PAYLOAD = {
    "public_key": "test-pub-key",
    "private_key": "test-priv-key",
    "account_number": "99887766",
}


# ── Tests de connect ───────────────────────────────────────────────────────────

class TestConnectPPI:
    def test_connect_success_returns_200(self, client):
        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance.authenticate.return_value = None
            with patch("app.routers.integrations._sync_ppi", return_value={
                "positions_synced": 2, "months_synced": 1, "mep": 1430.0
            }):
                resp = client.post("/integrations/ppi/connect", json=CONNECT_PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["positions_synced"] == 2

    def test_connect_invalid_credentials_returns_401(self, client):
        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance.authenticate.side_effect = PPIAuthError("Credenciales inválidas")
            resp = client.post("/integrations/ppi/connect", json=CONNECT_PAYLOAD)

        assert resp.status_code == 401
        assert resp.json()["detail"]  # mensaje de error presente

    def test_connect_network_error_returns_502(self, client):
        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance.authenticate.side_effect = Exception("Connection refused")
            resp = client.post("/integrations/ppi/connect", json=CONNECT_PAYLOAD)

        assert resp.status_code == 502

    def test_connect_stores_credentials_in_db(self, client, db_session):
        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance.authenticate.return_value = None
            with patch("app.routers.integrations._sync_ppi", return_value={
                "positions_synced": 1, "months_synced": 0, "mep": 1430.0
            }):
                resp = client.post("/integrations/ppi/connect", json=CONNECT_PAYLOAD)

        assert resp.status_code == 200
        integration = db_session.query(Integration).filter_by(
            provider="PPI", user_id="test-user-id"
        ).first()
        assert integration is not None
        assert integration.is_connected is True
        creds = integration.encrypted_credentials
        assert "test-pub-key" in creds
        assert "test-priv-key" in creds
        assert "99887766" in creds
        # Formato: public_key:private_key:account_number (3 partes)
        assert len(creds.split(":")) == 3

    def test_connect_calls_sync_ppi_after_auth(self, client):
        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance.authenticate.return_value = None
            with patch("app.routers.integrations._sync_ppi", return_value={
                "positions_synced": 0, "months_synced": 0, "mep": 1430.0
            }) as mock_sync:
                client.post("/integrations/ppi/connect", json=CONNECT_PAYLOAD)

        mock_sync.assert_called_once()
        _, account_number_arg, _, user_id_arg = mock_sync.call_args[0]
        assert account_number_arg == "99887766"
        assert user_id_arg == "test-user-id"


# ── Tests de sync ──────────────────────────────────────────────────────────────

class TestSyncPPI:
    def _create_connected_integration(self, db_session):
        # Limpiar integraciones PPI previas
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.commit()

        integration = Integration(
            user_id="test-user-id",
            provider="PPI",
            provider_type="ALYC",
            encrypted_credentials="pub:priv:12345",
            is_connected=True,
            last_error="",
        )
        db_session.add(integration)
        db_session.commit()
        return integration

    def test_sync_not_connected_returns_400(self, client, db_session):
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.commit()
        resp = client.post("/integrations/ppi/sync")
        assert resp.status_code == 400
        assert "no está conectado" in resp.json()["detail"]

    def test_sync_connected_returns_positions_synced(self, client, db_session):
        self._create_connected_integration(db_session)
        with patch("app.routers.integrations.PPIClient"):
            with patch("app.routers.integrations._sync_ppi", return_value={
                "positions_synced": 3, "months_synced": 1, "mep": 1430.0
            }):
                resp = client.post("/integrations/ppi/sync")

        assert resp.status_code == 200
        assert resp.json()["positions_synced"] == 3

    def test_sync_error_returns_502(self, client, db_session):
        self._create_connected_integration(db_session)
        with patch("app.routers.integrations.PPIClient"):
            with patch("app.routers.integrations._sync_ppi", side_effect=Exception("API Error")):
                resp = client.post("/integrations/ppi/sync")

        assert resp.status_code == 502

    def test_sync_parses_credentials_correctly(self, client, db_session):
        """Verifica que las creds 'pub:priv:acct' se spliteen bien."""
        self._create_connected_integration(db_session)
        with patch("app.routers.integrations.PPIClient") as MockClient:
            with patch("app.routers.integrations._sync_ppi", return_value={
                "positions_synced": 0, "months_synced": 0, "mep": 1430.0
            }) as mock_sync:
                client.post("/integrations/ppi/sync")

        # PPIClient fue instanciado con pub y priv correctos
        MockClient.assert_called_once_with("pub", "priv")
        # _sync_ppi recibió el account_number correcto
        _, account_arg, _, _ = mock_sync.call_args[0]
        assert account_arg == "12345"


# ── Tests de disconnect ────────────────────────────────────────────────────────

class TestDisconnectPPI:
    def _setup(self, db_session):
        # Limpiar datos previos
        db_session.query(Position).filter_by(source="PPI", user_id="test-user-id").delete()
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.commit()

        integration = Integration(
            user_id="test-user-id",
            provider="PPI",
            provider_type="ALYC",
            encrypted_credentials="pub:priv:12345",
            is_connected=True,
            last_error="",
        )
        db_session.add(integration)

        pos = Position(
            user_id="test-user-id",
            ticker="QQQ",
            description="QQQ PPI",
            asset_type="CEDEAR",
            source="PPI",
            quantity=Decimal("5"),
            avg_purchase_price_usd=Decimal("575"),
            current_price_usd=Decimal("590"),
            annual_yield_pct=Decimal("0.10"),
            snapshot_date=date.today(),
            is_active=True,
        )
        db_session.add(pos)
        db_session.commit()
        return integration, pos

    def test_disconnect_returns_200(self, client, db_session):
        self._setup(db_session)
        resp = client.post("/integrations/ppi/disconnect")
        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True

    def test_disconnect_clears_credentials(self, client, db_session):
        integration, _ = self._setup(db_session)
        client.post("/integrations/ppi/disconnect")
        db_session.expire(integration)
        db_session.refresh(integration)
        assert integration.is_connected is False
        assert integration.encrypted_credentials == ""

    def test_disconnect_deactivates_ppi_positions(self, client, db_session):
        _, pos = self._setup(db_session)
        client.post("/integrations/ppi/disconnect")
        db_session.expire(pos)
        db_session.refresh(pos)
        assert pos.is_active is False

    def test_disconnect_not_found_returns_404(self, client, db_session):
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.commit()
        resp = client.post("/integrations/ppi/disconnect")
        assert resp.status_code == 404

    def test_disconnect_does_not_touch_iol_positions(self, client, db_session):
        self._setup(db_session)
        iol_pos = Position(
            user_id="test-user-id",
            ticker="GGAL",
            description="GGAL IOL",
            asset_type="CEDEAR",
            source="IOL",
            quantity=Decimal("100"),
            avg_purchase_price_usd=Decimal("10"),
            current_price_usd=Decimal("11"),
            annual_yield_pct=Decimal("0.10"),
            snapshot_date=date.today(),
            is_active=True,
        )
        db_session.add(iol_pos)
        db_session.commit()

        client.post("/integrations/ppi/disconnect")
        db_session.expire(iol_pos)
        db_session.refresh(iol_pos)
        assert iol_pos.is_active is True


# ── Tests de debug ─────────────────────────────────────────────────────────────

class TestDebugPPI:
    def test_debug_not_connected_returns_400(self, client, db_session):
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.commit()
        resp = client.get("/integrations/ppi/debug")
        assert resp.status_code == 400

    def test_debug_returns_raw_data_without_modifying_db(self, client, db_session):
        db_session.query(Integration).filter_by(provider="PPI", user_id="test-user-id").delete()
        db_session.query(Position).filter_by(source="PPI", user_id="test-user-id").delete()
        db_session.commit()

        integration = Integration(
            user_id="test-user-id",
            provider="PPI",
            provider_type="ALYC",
            encrypted_credentials="pub:priv:12345",
            is_connected=True,
            last_error="",
        )
        db_session.add(integration)
        db_session.commit()

        initial_position_count = db_session.query(Position).filter_by(user_id="test-user-id").count()

        raw_data = {
            "groupedInstruments": [
                {
                    "name": "CEDEARS",
                    "instruments": [
                        {"ticker": "QQQ", "quantity": 5, "price": 845000.0, "amount": 4225000.0}
                    ],
                }
            ]
        }

        with patch("app.routers.integrations.PPIClient") as MockClient:
            instance = MockClient.return_value
            instance._get_mep.return_value = 1430.0
            instance._get.return_value = raw_data
            instance.get_cash_balance.return_value = {
                "ars": Decimal("5000"), "usd": Decimal("100")
            }
            resp = client.get("/integrations/ppi/debug")

        assert resp.status_code == 200
        data = resp.json()
        assert "mep" in data
        assert "positions" in data
        assert len(data["positions"]) == 1
        assert data["positions"][0]["ticker"] == "QQQ"

        # DB no modificada
        final_count = db_session.query(Position).filter_by(user_id="test-user-id").count()
        assert final_count == initial_position_count
