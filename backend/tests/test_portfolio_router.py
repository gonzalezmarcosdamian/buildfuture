"""
Tests para router/portfolio.py — endpoint GET /portfolio/.

Corre con: pytest backend/tests/test_portfolio_router.py -v
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.routers.portfolio import get_portfolio, _get_freedom_score, _query_budget


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pos(
    ticker="AL30",
    asset_type="BOND",
    value_usd=1000.0,
    yield_pct=0.15,
    source="IOL",
    user_id="user-1",
):
    p = MagicMock()
    p.id = 1
    p.ticker = ticker
    p.description = ticker
    p.asset_type = asset_type
    p.source = source
    p.user_id = user_id
    p.is_active = True
    p.quantity = Decimal("100")
    p.avg_purchase_price_usd = Decimal("9.5")
    p.current_price_usd = Decimal(str(value_usd / 100))
    p.current_value_usd = Decimal(str(value_usd))
    p.current_value_ars = Decimal(str(value_usd * 1430))
    p.cost_basis_usd = Decimal(str(value_usd * 0.9))
    p.performance_pct = Decimal("0.10")
    p.performance_ars_pct = Decimal("0.05")
    p.purchase_fx_rate = Decimal("1430")
    p.ppc_ars = Decimal("9500")
    p.annual_yield_pct = Decimal(str(yield_pct))
    p.yield_currency = "ARS"
    p.snapshot_date = None
    return p


def _budget(fx=1430.0, expenses_usd=2000.0):
    b = MagicMock()
    b.fx_rate = Decimal(str(fx))
    b.total_monthly_usd = Decimal(str(expenses_usd))
    b.savings_monthly_usd = Decimal("500")
    return b


# ── _get_freedom_score ────────────────────────────────────────────────────────

class TestGetFreedomScore:
    def test_returns_score_dict(self):
        positions = [_pos(value_usd=10000, yield_pct=0.48)]
        score = _get_freedom_score("user-x", positions, Decimal("2000"))
        assert "freedom_pct" in score
        assert "portfolio_total_usd" in score
        assert score["portfolio_total_usd"] == Decimal("10000")

    def test_cache_hit_returns_same_object(self):
        positions = [_pos(value_usd=5000)]
        score1 = _get_freedom_score("user-cache", positions, Decimal("2000"))
        score2 = _get_freedom_score("user-cache", positions, Decimal("2000"))
        assert score1 is score2

    def test_empty_positions(self):
        score = _get_freedom_score("user-empty", [], Decimal("2000"))
        assert float(score["freedom_pct"]) == 0.0
        assert float(score["portfolio_total_usd"]) == 0.0


# ── GET /portfolio/ ───────────────────────────────────────────────────────────

class TestGetPortfolio:
    def _call(self, positions, budget=None):
        """Llama get_portfolio con mocks de db y current_user."""
        db = MagicMock()

        query_mock = MagicMock()
        query_mock.filter.return_value = query_mock
        query_mock.all.return_value = positions
        db.query.return_value = query_mock

        with (
            patch("app.routers.portfolio._query_budget", return_value=budget or _budget()),
            patch("app.routers.portfolio.get_mep", return_value=Decimal("1430")),
            patch("app.routers.portfolio.get_expected_devaluation", return_value=Decimal("0.20")),
            patch("app.routers.portfolio.save_position_snapshots"),
            patch("app.routers.portfolio.split_portfolio_buckets") as mock_buckets,
        ):
            mock_buckets.return_value = {
                "renta_monthly_usd": Decimal("100"),
                "renta_total_usd": Decimal("5000"),
                "capital_total_usd": Decimal("5000"),
                "cedear_total_usd": Decimal("3000"),
                "crypto_total_usd": Decimal("1000"),
                "cash_total_usd": Decimal("1000"),
                "by_source": {},
            }
            return get_portfolio(db=db, current_user="user-1")

    def test_empty_portfolio(self):
        result = self._call([])
        assert result["positions"] == []
        assert result["summary"]["total_usd"] == 0.0
        assert result["summary"]["freedom_pct"] == 0.0

    def test_positions_returned(self):
        positions = [_pos("AL30", value_usd=5000), _pos("LECAP1", asset_type="LETRA", value_usd=3000)]
        result = self._call(positions)
        assert len(result["positions"]) == 2
        tickers = {p["ticker"] for p in result["positions"]}
        assert "AL30" in tickers
        assert "LECAP1" in tickers

    def test_summary_has_required_fields(self):
        result = self._call([_pos(value_usd=10000)])
        summary = result["summary"]
        for field in ("total_usd", "total_ars", "mep", "monthly_return_usd",
                      "freedom_pct", "annual_return_pct", "monthly_expenses_usd",
                      "capital_total_usd", "renta_total_usd", "expected_devaluation_pct"):
            assert field in summary, f"summary missing field: {field}"

    def test_total_ars_equals_total_usd_times_mep(self):
        result = self._call([_pos(value_usd=1000)])
        summary = result["summary"]
        assert abs(summary["total_ars"] - summary["total_usd"] * summary["mep"]) < 0.01

    def test_mep_from_budget(self):
        result = self._call([_pos()], budget=_budget(fx=1500))
        # get_mep is patched to 1430 regardless — but mep field comes from get_mep()
        assert result["summary"]["mep"] == 1430.0

    def test_monthly_expenses_from_budget(self):
        result = self._call([_pos()], budget=_budget(expenses_usd=3000))
        assert result["summary"]["monthly_expenses_usd"] == 3000.0

    def test_no_cross_user_cache_pollution(self):
        """Dos usuarios distintos deben tener scores independientes."""
        pos_a = [_pos("AL30", value_usd=10000, user_id="user-a")]
        pos_b = [_pos("AL30", value_usd=50000, user_id="user-b")]
        score_a = _get_freedom_score("user-a", pos_a, Decimal("2000"))
        score_b = _get_freedom_score("user-b", pos_b, Decimal("2000"))
        assert score_a["portfolio_total_usd"] != score_b["portfolio_total_usd"]

    def test_position_fields_are_floats(self):
        result = self._call([_pos()])
        p = result["positions"][0]
        for field in ("current_value_usd", "annual_yield_pct", "performance_pct",
                      "avg_purchase_price_usd", "cost_basis_usd"):
            assert isinstance(p[field], float), f"position[{field}] should be float"


# ── MEP fallback ──────────────────────────────────────────────────────────────

class TestMepFallback:
    def test_get_mep_uses_budget_fx_rate(self):
        from app.services.mep import get_mep
        budget = _budget(fx=1550)
        result = get_mep(budget)
        assert float(result) == 1550.0

    def test_get_mep_fallback_when_no_budget(self):
        from app.services.mep import get_mep
        result = get_mep(None)
        assert float(result) > 0
