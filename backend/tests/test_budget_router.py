"""
Tests para router/budget.py — lógica de presupuesto y tipo de cambio.

Corre con: pytest backend/tests/test_budget_router.py -v
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.routers.budget import (
    _fetch_fx_rate,
    _serialize,
    update_budget,
    get_budget,
    BudgetIn,
    CategoryIn,
)
from app.models import BudgetConfig, BudgetCategory


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_budget(income=1_000_000, fx=1430, expense_pct=0.6, vacation_pct=0.05):
    b = MagicMock(spec=BudgetConfig)
    b.id = 1
    b.effective_month = MagicMock()
    b.effective_month.isoformat.return_value = "2026-04-01"
    b.income_monthly_ars = Decimal(str(income))
    b.income_monthly_usd = Decimal(str(round(income / fx, 2)))
    b.total_monthly_ars = Decimal(str(income * expense_pct))
    b.total_monthly_usd = Decimal(str(round(income * expense_pct / fx, 2)))
    b.fx_rate = Decimal(str(fx))
    b.savings_monthly_ars = Decimal(str(income * (1 - expense_pct - vacation_pct)))
    b.savings_monthly_usd = Decimal(str(round(income * (1 - expense_pct - vacation_pct) / fx, 2)))
    b.expenses_pct = Decimal(str(expense_pct))
    b.vacation_pct = Decimal(str(vacation_pct))

    cat = MagicMock(spec=BudgetCategory)
    cat.id = 1
    cat.name = "Alimentación"
    cat.percentage = Decimal("0.25")
    cat.amount_ars = Decimal("250000")
    cat.amount_usd = Decimal("174.8")
    cat.icon = "🛒"
    cat.color = "#3B82F6"
    cat.is_vacation = False
    b.categories = [cat]
    return b


# ── _serialize ────────────────────────────────────────────────────────────────

class TestSerialize:
    def test_serialize_returns_float_fields(self):
        budget = _make_budget()
        result = _serialize(budget)
        assert isinstance(result["income_monthly_ars"], float)
        assert isinstance(result["fx_rate"], float)
        assert isinstance(result["expenses_pct"], float)

    def test_serialize_categories(self):
        budget = _make_budget()
        result = _serialize(budget)
        assert len(result["categories"]) == 1
        cat = result["categories"][0]
        assert cat["name"] == "Alimentación"
        assert isinstance(cat["percentage"], float)
        assert cat["icon"] == "🛒"
        assert cat["is_vacation"] is False

    def test_serialize_effective_month_is_string(self):
        budget = _make_budget()
        result = _serialize(budget)
        assert isinstance(result["effective_month"], str)


# ── _fetch_fx_rate ────────────────────────────────────────────────────────────

class TestFetchFxRate:
    def test_uses_dolarapi_when_available(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"venta": 1450.5, "compra": 1440.0}
        with patch("app.routers.budget.httpx.get", return_value=mock_resp):
            result = _fetch_fx_rate()
        assert result["fx_rate"] == 1450.5
        assert result["source"] == "dolarapi"

    def test_falls_back_to_bluelytics_on_dolarapi_failure(self):
        def fake_get(url, **_):
            if "dolarapi" in url:
                raise RuntimeError("timeout")
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"blue": {"value_sell": 1420.0}}
            return mock_resp

        with patch("app.routers.budget.httpx.get", side_effect=fake_get):
            result = _fetch_fx_rate()
        assert result["fx_rate"] == 1420.0
        assert result["source"] == "bluelytics_blue"

    def test_returns_fallback_when_both_sources_fail(self):
        with patch("app.routers.budget.httpx.get", side_effect=RuntimeError("network error")):
            result = _fetch_fx_rate()
        assert result["fx_rate"] == 1431.0
        assert result["source"] == "fallback"

    def test_uses_compra_when_venta_missing(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"venta": None, "compra": 1435.0}
        with patch("app.routers.budget.httpx.get", return_value=mock_resp):
            result = _fetch_fx_rate()
        assert result["fx_rate"] == 1435.0


# ── update_budget ─────────────────────────────────────────────────────────────

class TestUpdateBudget:
    def _make_db(self, existing_budget=None):
        db = MagicMock()
        query_chain = db.query.return_value.filter.return_value.order_by.return_value
        query_chain.first.return_value = existing_budget
        return db

    def test_expense_pct_excludes_vacation(self):
        """La suma de expense_pct no debe incluir categorías de vacaciones."""
        existing = _make_budget()
        existing.categories = []
        db = self._make_db(existing_budget=existing)
        db.refresh.side_effect = lambda b: None

        body = BudgetIn(
            income_monthly_ars=1_000_000,
            fx_rate=1430,
            categories=[
                CategoryIn(name="Alimentación", percentage=0.30, icon="🛒", color="#3B82F6", is_vacation=False),
                CategoryIn(name="Vacaciones",   percentage=0.10, icon="🏖️", color="#0EA5E9", is_vacation=True),
            ],
        )
        update_budget(body=body, db=db, current_user="user-123")

        # total_monthly_ars should be income * expense_pct (0.30), NOT 0.40
        expected_total = Decimal("1000000") * Decimal("0.3")
        assert existing.total_monthly_ars == expected_total

    def test_creates_budget_if_none_exists(self):
        db = self._make_db(existing_budget=None)
        db.refresh.side_effect = lambda b: None

        body = BudgetIn(
            income_monthly_ars=800_000,
            fx_rate=1430,
            categories=[
                CategoryIn(name="Vivienda", percentage=0.30, icon="🏠", color="#8B5CF6", is_vacation=False),
            ],
        )
        update_budget(body=body, db=db, current_user="user-123")
        db.add.assert_called()

    def test_replaces_existing_categories(self):
        """Las categorías viejas deben eliminarse antes de insertar las nuevas."""
        old_cat = MagicMock(spec=BudgetCategory)
        existing = _make_budget()
        existing.categories = [old_cat]
        db = self._make_db(existing_budget=existing)
        db.refresh.side_effect = lambda b: None

        body = BudgetIn(
            income_monthly_ars=1_000_000,
            fx_rate=1430,
            categories=[
                CategoryIn(name="Transporte", percentage=0.10, icon="🚗", color="#10B981", is_vacation=False),
            ],
        )
        update_budget(body=body, db=db, current_user="user-123")
        db.delete.assert_called_with(old_cat)


# ── get_budget ────────────────────────────────────────────────────────────────

class TestGetBudget:
    def test_returns_none_when_no_budget(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = get_budget(db=db, current_user="user-no-budget")
        assert result is None

    def test_returns_serialized_budget(self):
        budget = _make_budget(income=500_000)
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = budget
        result = get_budget(db=db, current_user="user-123")
        assert result is not None
        assert result["income_monthly_ars"] == 500_000.0
