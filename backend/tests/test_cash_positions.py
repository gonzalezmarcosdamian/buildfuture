"""
Tests para create/update de posiciones CASH manuales.

Verifica que current_value_ars se calcule y actualice correctamente
para evitar el bug donde capital ARS > total ARS en el dashboard.

Corre con: pytest backend/tests/test_cash_positions.py -v
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.routers.positions import create_manual_position, update_manual_position, ManualPositionCreate, ManualPositionUpdate
from app.models import Position


MEP = 1500.0  # MEP usado en tests


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_db(pos=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = pos
    db.refresh.side_effect = lambda obj: None
    return db


def _make_cash_pos(ticker="CASH_ARS", qty=1000, price=1.0, value_ars=Decimal("1500000")):
    pos = MagicMock(spec=Position)
    pos.id = 1
    pos.ticker = ticker
    pos.asset_type = "CASH"
    pos.source = "MANUAL"
    pos.quantity = Decimal(str(qty))
    pos.current_price_usd = Decimal(str(price))
    pos.current_value_usd = Decimal(str(qty)) * Decimal(str(price))
    pos.current_value_ars = value_ars
    pos.ppc_ars = value_ars
    pos.purchase_fx_rate = Decimal(str(MEP))
    pos.cost_basis_usd = Decimal(str(qty))
    pos.annual_yield_pct = Decimal("0")
    pos.description = "Efectivo en pesos"
    pos.snapshot_date = None
    pos.is_active = True
    pos.external_id = None
    pos.fci_categoria = None
    return pos


# ── Tests: CREATE ─────────────────────────────────────────────────────────────

class TestCreateCashARS:
    """CASH_ARS: el usuario ingresa monto en pesos."""

    def test_current_value_ars_set_from_ppc_ars(self):
        """Cuando se crea CASH_ARS, current_value_ars debe ser el monto ARS ingresado."""
        db = _make_db()
        created_pos = None

        def capture_add(obj):
            nonlocal created_pos
            created_pos = obj

        db.add.side_effect = capture_add
        db.refresh.side_effect = lambda obj: None

        body = ManualPositionCreate(
            asset_type="CASH",
            ticker="CASH_ARS",
            description="Efectivo en pesos",
            quantity=1000.0,          # ARS 1.500.000 / MEP 1500
            purchase_price_usd=1.0,
            ppc_ars=1_500_000.0,      # monto ARS ingresado por el usuario
            purchase_fx_rate=MEP,
        )

        with patch("app.routers.positions._get_live_price_and_yield", return_value=(1.0, 0.0)):
            create_manual_position(body, db=db, user_id="user-1")

        assert created_pos is not None, "Position no fue creada"
        assert created_pos.current_value_ars == Decimal("1500000"), (
            f"current_value_ars debería ser 1500000, got {created_pos.current_value_ars}"
        )

    def test_current_value_usd_correct(self):
        """Para CASH_ARS: current_value_usd = ppc_ars / mep."""
        db = _make_db()
        created_pos = None

        def capture_add(obj):
            nonlocal created_pos
            created_pos = obj

        db.add.side_effect = capture_add

        body = ManualPositionCreate(
            asset_type="CASH",
            ticker="CASH_ARS",
            description="Efectivo en pesos",
            quantity=1000.0,
            purchase_price_usd=1.0,
            ppc_ars=1_500_000.0,
            purchase_fx_rate=MEP,
        )

        with patch("app.routers.positions._get_live_price_and_yield", return_value=(1.0, 0.0)):
            create_manual_position(body, db=db, user_id="user-1")

        # current_value_usd = quantity * current_price_usd = 1000 * 1.0 = 1000
        assert float(created_pos.quantity) == pytest.approx(1000.0)


class TestCreateCashUSD:
    """CASH_USD: el usuario ingresa monto en dólares."""

    def test_current_value_ars_set_from_quantity_times_mep(self):
        """Cuando se crea CASH_USD, current_value_ars = quantity * purchase_fx_rate."""
        db = _make_db()
        created_pos = None

        def capture_add(obj):
            nonlocal created_pos
            created_pos = obj

        db.add.side_effect = capture_add

        body = ManualPositionCreate(
            asset_type="CASH",
            ticker="CASH_USD",
            description="Efectivo en dólares",
            quantity=500.0,             # USD 500
            purchase_price_usd=1.0,
            ppc_ars=500.0 * MEP,        # equivalente ARS (frontend lo calcula)
            purchase_fx_rate=MEP,
        )

        with patch("app.routers.positions._get_live_price_and_yield", return_value=(1.0, 0.0)):
            create_manual_position(body, db=db, user_id="user-1")

        assert created_pos is not None
        # ppc_ars > 0 → usa ppc_ars como current_value_ars
        expected_ars = Decimal(str(500.0 * MEP))
        assert created_pos.current_value_ars == expected_ars, (
            f"current_value_ars debería ser {expected_ars}, got {created_pos.current_value_ars}"
        )

    def test_current_value_ars_fallback_to_qty_times_fx(self):
        """Si ppc_ars = 0, usa quantity * purchase_fx_rate como fallback."""
        db = _make_db()
        created_pos = None

        def capture_add(obj):
            nonlocal created_pos
            created_pos = obj

        db.add.side_effect = capture_add

        body = ManualPositionCreate(
            asset_type="CASH",
            ticker="CASH_USD",
            description="Efectivo en dólares",
            quantity=500.0,
            purchase_price_usd=1.0,
            ppc_ars=0.0,            # sin ppc_ars (caso legacy/edge)
            purchase_fx_rate=MEP,
        )

        with patch("app.routers.positions._get_live_price_and_yield", return_value=(1.0, 0.0)):
            create_manual_position(body, db=db, user_id="user-1")

        expected_ars = Decimal("500.0") * Decimal(str(MEP))
        assert created_pos.current_value_ars == expected_ars


# ── Tests: UPDATE ─────────────────────────────────────────────────────────────

class TestUpdateCashARS:
    """Editar CASH_ARS actualiza current_value_ars."""

    def test_update_recalculates_current_value_ars(self):
        """Editar CASH_ARS con nuevo monto ARS actualiza current_value_ars."""
        old_ars = Decimal("1500000")
        new_ars = 2_000_000.0
        new_qty = new_ars / MEP

        pos = _make_cash_pos(ticker="CASH_ARS", qty=1000, value_ars=old_ars)
        pos.ppc_ars = old_ars  # valor viejo
        pos.purchase_fx_rate = Decimal(str(MEP))

        db = _make_db(pos=pos)

        body = ManualPositionUpdate(
            quantity=new_qty,
            ppc_ars=new_ars,
            purchase_fx_rate=MEP,
        )

        update_manual_position(1, body, db=db, user_id="user-1")

        assert pos.current_value_ars == Decimal(str(new_ars)), (
            f"current_value_ars debería actualizarse a {new_ars}, got {pos.current_value_ars}"
        )

    def test_update_does_not_leave_stale_ars_value(self):
        """Después de editar, current_value_ars NO debe ser el valor viejo."""
        old_ars = Decimal("1500000")
        pos = _make_cash_pos(ticker="CASH_ARS", qty=1000, value_ars=old_ars)
        pos.ppc_ars = old_ars
        pos.purchase_fx_rate = Decimal(str(MEP))

        db = _make_db(pos=pos)

        body = ManualPositionUpdate(quantity=2000 / MEP, ppc_ars=2_000_000.0, purchase_fx_rate=MEP)
        update_manual_position(1, body, db=db, user_id="user-1")

        assert pos.current_value_ars != old_ars, "current_value_ars no debe quedar con el valor viejo"


class TestUpdateCashUSD:
    """Editar CASH_USD actualiza current_value_ars."""

    def test_update_usd_recalculates_ars(self):
        """Editar CASH_USD con nuevo monto recalcula current_value_ars."""
        old_ars = Decimal("750000")  # 500 USD * 1500
        new_qty = 800.0              # 800 USD
        new_ppc_ars = new_qty * MEP  # frontend calcula este valor

        pos = _make_cash_pos(ticker="CASH_USD", qty=500, value_ars=old_ars)
        pos.ppc_ars = old_ars
        pos.purchase_fx_rate = Decimal(str(MEP))

        db = _make_db(pos=pos)

        body = ManualPositionUpdate(
            quantity=new_qty,
            ppc_ars=new_ppc_ars,
            purchase_fx_rate=MEP,
        )

        update_manual_position(1, body, db=db, user_id="user-1")

        expected_ars = Decimal(str(new_ppc_ars))
        assert pos.current_value_ars == expected_ars, (
            f"current_value_ars debería ser {expected_ars}, got {pos.current_value_ars}"
        )


# ── Tests: INVARIANTE — capital nunca supera total ────────────────────────────

class TestCapitalBelowTotal:
    """current_value_ars de CASH nunca debe superar el total_usd * mep."""

    def test_cash_ars_value_consistent_with_usd(self):
        """current_value_ars / purchase_fx_rate ≈ current_value_usd (tolerancia 1%)."""
        db = _make_db()
        created_pos = None

        def capture_add(obj):
            nonlocal created_pos
            created_pos = obj

        db.add.side_effect = capture_add

        ars_amount = 3_000_000.0
        mep = 1500.0
        qty_usd = ars_amount / mep  # 2000 USD

        body = ManualPositionCreate(
            asset_type="CASH",
            ticker="CASH_ARS",
            description="Efectivo",
            quantity=qty_usd,
            purchase_price_usd=1.0,
            ppc_ars=ars_amount,
            purchase_fx_rate=mep,
        )

        with patch("app.routers.positions._get_live_price_and_yield", return_value=(1.0, 0.0)):
            create_manual_position(body, db=db, user_id="user-1")

        implied_usd = float(created_pos.current_value_ars) / mep
        actual_usd = float(created_pos.quantity)  # quantity = qty_usd

        assert abs(implied_usd - actual_usd) / actual_usd < 0.01, (
            f"Inconsistencia ARS/USD: implied={implied_usd:.2f} vs actual={actual_usd:.2f}"
        )
