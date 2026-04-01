"""
Tests de _sync_ppi() y helpers de sincronización PPI.
Usa SQLite en memoria para no tocar la DB real.
Corre con: pytest backend/tests/test_ppi_sync.py -v
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base, Position, Integration, InvestmentMonth
from app.services.ppi_client import PPIClient, PPIPosition
from app.routers.integrations import _sync_ppi


# ── Fixtures DB ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_ppi_position(
    ticker="QQQ",
    asset_type="CEDEAR",
    quantity=Decimal("5"),
    current_price_usd=Decimal("590.00"),
    annual_yield_pct=Decimal("0.10"),
) -> PPIPosition:
    return PPIPosition(
        ticker=ticker,
        description=f"{ticker} description",
        asset_type=asset_type,
        quantity=quantity,
        current_price_usd=current_price_usd,
        avg_price_usd=current_price_usd,
        annual_yield_pct=annual_yield_pct,
        ppc_ars=Decimal("843500"),
        current_value_ars=Decimal("4217500"),
    )


def _make_ppi_client(positions=None, cash=None, operations=None) -> PPIClient:
    client = MagicMock(spec=PPIClient)
    client._get_mep.return_value = 1430.0
    client.get_historical_mep.return_value = 1420.0
    client.get_portfolio.return_value = positions or [_make_ppi_position()]
    client.get_cash_balance.return_value = cash or {"ars": Decimal("0"), "usd": Decimal("0")}
    client.get_operations.return_value = operations or []
    return client


USER_ID = "user-abc-123"


# ── Tests de _sync_ppi ─────────────────────────────────────────────────────────

class TestSyncPPI:
    def test_creates_positions_with_source_ppi(self, db):
        client = _make_ppi_client()
        _sync_ppi(client, "12345", db, USER_ID)

        positions = db.query(Position).filter_by(source="PPI", is_active=True).all()
        assert len(positions) == 1
        assert positions[0].ticker == "QQQ"
        assert positions[0].source == "PPI"

    def test_deactivates_old_ppi_positions_on_resync(self, db):
        # Primera sync
        client = _make_ppi_client(positions=[_make_ppi_position("QQQ")])
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        # Segunda sync con diferente posición
        client2 = _make_ppi_client(positions=[_make_ppi_position("GGAL", "STOCK")])
        _sync_ppi(client2, "12345", db, USER_ID)
        db.commit()

        active = db.query(Position).filter_by(source="PPI", is_active=True).all()
        active_tickers = [p.ticker for p in active]
        assert "GGAL" in active_tickers
        assert "QQQ" not in active_tickers  # desactivado

    def test_does_not_touch_iol_positions(self, db):
        # Crear una posición IOL preexistente
        iol_pos = Position(
            user_id=USER_ID,
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
        db.add(iol_pos)
        db.commit()

        client = _make_ppi_client(positions=[_make_ppi_position("QQQ")])
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        # IOL debe seguir activa
        iol_check = db.query(Position).filter_by(source="IOL", ticker="GGAL").first()
        assert iol_check is not None
        assert iol_check.is_active is True

    def test_does_not_touch_manual_positions(self, db):
        manual_pos = Position(
            user_id=USER_ID,
            ticker="BTC",
            description="Bitcoin",
            asset_type="CRYPTO",
            source="MANUAL",
            quantity=Decimal("0.5"),
            avg_purchase_price_usd=Decimal("60000"),
            current_price_usd=Decimal("85000"),
            annual_yield_pct=Decimal("0.04"),
            snapshot_date=date.today(),
            is_active=True,
        )
        db.add(manual_pos)
        db.commit()

        client = _make_ppi_client()
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        btc = db.query(Position).filter_by(source="MANUAL", ticker="BTC").first()
        assert btc is not None
        assert btc.is_active is True

    def test_does_not_touch_other_users_positions(self, db):
        other_user_pos = Position(
            user_id="other-user-999",
            ticker="QQQ",
            description="QQQ otro usuario",
            asset_type="CEDEAR",
            source="PPI",
            quantity=Decimal("10"),
            avg_purchase_price_usd=Decimal("580"),
            current_price_usd=Decimal("590"),
            annual_yield_pct=Decimal("0.10"),
            snapshot_date=date.today(),
            is_active=True,
        )
        db.add(other_user_pos)
        db.commit()

        client = _make_ppi_client(positions=[_make_ppi_position("GGAL", "STOCK")])
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        other = db.query(Position).filter_by(user_id="other-user-999", ticker="QQQ").first()
        assert other.is_active is True  # intacto

    def test_cash_ars_creates_cash_ppi_ars_position(self, db):
        cash = {"ars": Decimal("50000"), "usd": Decimal("0")}
        client = _make_ppi_client(positions=[], cash=cash)
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        cash_pos = db.query(Position).filter_by(ticker="CASH_PPI_ARS", is_active=True).first()
        assert cash_pos is not None
        assert cash_pos.asset_type == "CASH"
        assert cash_pos.source == "PPI"
        assert cash_pos.current_value_ars == Decimal("50000")

    def test_cash_usd_creates_cash_ppi_usd_position(self, db):
        cash = {"ars": Decimal("0"), "usd": Decimal("1500")}
        client = _make_ppi_client(positions=[], cash=cash)
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        cash_pos = db.query(Position).filter_by(ticker="CASH_PPI_USD", is_active=True).first()
        assert cash_pos is not None
        assert cash_pos.current_price_usd == Decimal("1500")

    def test_zero_cash_does_not_create_cash_position(self, db):
        cash = {"ars": Decimal("0"), "usd": Decimal("0")}
        client = _make_ppi_client(positions=[], cash=cash)
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        count = db.query(Position).filter(
            Position.ticker.in_(["CASH_PPI_ARS", "CASH_PPI_USD"])
        ).count()
        assert count == 0

    def test_purchase_fx_rate_set_from_historical_mep(self, db):
        operations = [{
            "date": "2026-03-15",
            "type": "COMPRA",
            "ticker": "QQQ",
            "quantity": 5,
            "price": 820000.0,
            "amount": 4100000.0,
        }]
        client = _make_ppi_client(operations=operations)
        client.get_historical_mep.return_value = 1420.0

        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        qqq = db.query(Position).filter_by(ticker="QQQ", source="PPI").first()
        assert qqq is not None
        assert qqq.purchase_fx_rate == Decimal("1420.00")

    def test_investment_months_recorded_from_buy_operations(self, db):
        operations = [
            {
                "date": "2026-03-15",
                "type": "COMPRA",
                "ticker": "QQQ",
                "quantity": 5,
                "price": 820000.0,
                "amount": 4100000.0,
            },
            {
                "date": "2026-02-10",
                "type": "COMPRA",
                "ticker": "AL30",
                "quantity": 100,
                "price": 72.0,
                "amount": 7200.0,
            },
            {
                "date": "2026-03-20",
                "type": "VENTA",  # ventas no se cuentan
                "ticker": "GGAL",
                "quantity": 50,
                "price": 4500.0,
                "amount": 225000.0,
            },
        ]
        client = _make_ppi_client(operations=operations)
        _sync_ppi(client, "12345", db, USER_ID)
        db.commit()

        months = db.query(InvestmentMonth).filter_by(user_id=USER_ID, source="PPI").all()
        months_dates = [m.month for m in months]
        assert date(2026, 3, 1) in months_dates
        assert date(2026, 2, 1) in months_dates
        assert len(months) == 2  # venta no cuenta

    def test_returns_dict_with_positions_synced_count(self, db):
        positions = [
            _make_ppi_position("QQQ"),
            _make_ppi_position("AL30", "BOND"),
            _make_ppi_position("GGAL", "STOCK"),
        ]
        client = _make_ppi_client(positions=positions)
        result = _sync_ppi(client, "12345", db, USER_ID)

        assert result["positions_synced"] >= 3
        assert "months_synced" in result
        assert "mep" in result
