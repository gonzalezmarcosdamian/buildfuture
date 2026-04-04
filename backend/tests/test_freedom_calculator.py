"""
Tests para freedom_calculator.py — lógica central de libertad financiera.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.freedom_calculator import (
    split_portfolio_buckets,
    calculate_freedom_score,
    calculate_milestone_projections,
    RENTA_ASSET_TYPES,
    CAPITAL_ASSET_TYPES,
    AMBOS_ASSET_TYPES,
)


def pos(asset_type: str, value: float, yield_pct: float = 0.0, source: str = "IOL"):
    """Helper: crea un objeto Position mínimo para los tests."""
    return SimpleNamespace(
        asset_type=asset_type,
        current_value_usd=Decimal(str(value)),
        annual_yield_pct=Decimal(str(yield_pct)),
        source=source,
    )


# ── split_portfolio_buckets ────────────────────────────────────────────────────

class TestSplitBuckets:
    def test_empty_positions(self):
        b = split_portfolio_buckets([])
        assert b["renta_monthly_usd"] == 0
        assert b["renta_total_usd"] == 0
        assert b["capital_total_usd"] == 0
        assert b["cash_total_usd"] == 0
        assert b["crypto_total_usd"] == 0
        assert b["by_source"] == {}

    def test_letra_goes_to_renta(self):
        b = split_portfolio_buckets([pos("LETRA", 1200, 0.60)])
        assert b["renta_total_usd"] == Decimal("1200")
        assert b["capital_total_usd"] == 0
        # renta mensual = 1200 * 0.60 / 12 = 60
        assert b["renta_monthly_usd"] == Decimal("60")

    def test_fci_goes_to_renta(self):
        b = split_portfolio_buckets([pos("FCI", 1000, 0.48)])
        assert b["renta_total_usd"] == Decimal("1000")
        assert b["renta_monthly_usd"] == Decimal("40")  # 1000*0.48/12

    def test_cedear_goes_to_capital(self):
        b = split_portfolio_buckets([pos("CEDEAR", 5000, 0.10)])
        assert b["capital_total_usd"] == Decimal("5000")
        assert b["renta_total_usd"] == 0
        assert b["renta_monthly_usd"] == 0  # CEDEAR no genera renta

    def test_crypto_goes_to_capital_and_crypto_subset(self):
        b = split_portfolio_buckets([pos("CRYPTO", 2000, 0.20)])
        assert b["capital_total_usd"] == Decimal("2000")
        assert b["crypto_total_usd"] == Decimal("2000")
        assert b["renta_monthly_usd"] == 0

    def test_cash_goes_to_capital_and_cash_subset(self):
        b = split_portfolio_buckets([pos("CASH", 500, 0.0, source="MANUAL")])
        assert b["capital_total_usd"] == Decimal("500")
        assert b["cash_total_usd"] == Decimal("500")
        assert b["renta_monthly_usd"] == 0

    def test_bond_splits_50_50(self):
        """BOND: 50% va a renta, 50% va a capital."""
        b = split_portfolio_buckets([pos("BOND", 1000, 0.12)])
        assert b["renta_total_usd"] == Decimal("500")
        assert b["capital_total_usd"] == Decimal("500")
        # renta mensual = 1000 * 0.12 / 12 * 0.5 = 5
        assert b["renta_monthly_usd"] == Decimal("5")

    def test_on_splits_50_50(self):
        """ON (Obligaciones Negociables): mismo tratamiento que BOND."""
        b = split_portfolio_buckets([pos("ON", 2000, 0.08)])
        assert b["renta_total_usd"] == Decimal("1000")
        assert b["capital_total_usd"] == Decimal("1000")

    def test_stock_is_neutral(self):
        """STOCK no va a renta ni a capital."""
        b = split_portfolio_buckets([pos("STOCK", 3000, 0.05)])
        assert b["renta_total_usd"] == 0
        assert b["capital_total_usd"] == 0
        assert b["renta_monthly_usd"] == 0

    def test_mixed_portfolio(self):
        positions = [
            pos("LETRA", 1000, 0.60),   # renta
            pos("CEDEAR", 2000, 0.10),  # capital
            pos("CASH", 500, 0.0, source="MANUAL"),   # cash
            pos("BOND", 1000, 0.12),    # 50/50
        ]
        b = split_portfolio_buckets(positions)
        # renta_total = 1000 (letra) + 500 (bond*50%)
        assert b["renta_total_usd"] == Decimal("1500")
        # capital_total = 2000 (cedear) + 500 (bond*50%) + 500 (cash)
        assert b["capital_total_usd"] == Decimal("3000")
        assert b["cash_total_usd"] == Decimal("500")

    def test_by_source_groups_correctly(self):
        positions = [
            pos("LETRA", 1000, 0.60, source="IOL"),
            pos("CEDEAR", 2000, 0.0, source="IOL"),
            pos("CASH", 500, 0.0, source="MANUAL"),
        ]
        b = split_portfolio_buckets(positions)
        assert "IOL" in b["by_source"]
        assert "MANUAL" in b["by_source"]
        assert b["by_source"]["IOL"]["total_usd"] == Decimal("3000")
        assert b["by_source"]["MANUAL"]["total_usd"] == Decimal("500")

    def test_asset_type_case_insensitive(self):
        """asset_type se normaliza a upper."""
        b = split_portfolio_buckets([pos("letra", 1000, 0.60)])
        assert b["renta_total_usd"] == Decimal("1000")


# ── calculate_freedom_score ────────────────────────────────────────────────────

class TestFreedomScore:
    def test_empty_positions_returns_zero(self):
        score = calculate_freedom_score([], Decimal("1000"))
        assert score["portfolio_total_usd"] == 0
        assert score["freedom_pct"] == 0

    def test_zero_expenses_returns_zero(self):
        score = calculate_freedom_score([pos("LETRA", 1000, 0.60)], Decimal("0"))
        assert score["freedom_pct"] == 0

    def test_portfolio_total_includes_all_positions(self):
        """portfolio_total_usd es la suma de todas las posiciones, incluyendo CASH."""
        positions = [
            pos("LETRA", 1000, 0.60),
            pos("CEDEAR", 2000, 0.10),
            pos("CASH", 500, 0.0, source="MANUAL"),
        ]
        score = calculate_freedom_score(positions, Decimal("500"))
        assert score["portfolio_total_usd"] == Decimal("3500")

    def test_freedom_pct_only_from_renta(self):
        """CEDEAR no contribuye a freedom_pct; solo activos de renta."""
        positions = [
            pos("LETRA", 1200, 0.60),  # mensual = 60
            pos("CEDEAR", 10000, 0.20),  # no renta
        ]
        score = calculate_freedom_score(positions, Decimal("120"))
        # freedom = 60/120 = 0.5
        assert score["freedom_pct"] == Decimal("60") / Decimal("120")
        assert score["monthly_return_usd"] == Decimal("60")

    def test_freedom_pct_above_100pct(self):
        """Si el portafolio cubre más que los gastos, freedom_pct > 1."""
        positions = [pos("LETRA", 2400, 1.0)]  # mensual = 200
        score = calculate_freedom_score(positions, Decimal("100"))
        assert score["freedom_pct"] == Decimal("2")

    def test_annual_return_pct_calculated_from_renta_only(self):
        positions = [pos("FCI", 1200, 0.48)]  # renta mensual = 48, anual = 576
        score = calculate_freedom_score(positions, Decimal("200"))
        # annual_return_pct = (48*12) / 1200 = 576/1200 = 0.48
        assert abs(float(score["annual_return_pct"]) - 0.48) < 0.001

    def test_zero_portfolio_total_returns_zero(self):
        positions = [pos("CEDEAR", 0, 0.10)]
        score = calculate_freedom_score(positions, Decimal("500"))
        assert score["freedom_pct"] == 0

    def test_cash_included_in_total_but_not_renta(self):
        positions = [
            pos("CASH", 6000, 0.0, source="MANUAL"),
            pos("LETRA", 1200, 0.60),  # mensual = 60
        ]
        score = calculate_freedom_score(positions, Decimal("120"))
        assert score["portfolio_total_usd"] == Decimal("7200")
        assert score["monthly_return_usd"] == Decimal("60")
        assert score["freedom_pct"] == Decimal("0.5")


# ── calculate_milestone_projections ───────────────────────────────────────────

class TestMilestoneProjections:
    def _run(self, portfolio, savings, expenses, return_pct, milestones=None):
        args = [
            Decimal(str(portfolio)),
            Decimal(str(savings)),
            Decimal(str(expenses)),
            Decimal(str(return_pct)),
        ]
        if milestones:
            args.append([Decimal(str(m)) for m in milestones])
        return calculate_milestone_projections(*args)

    def test_already_reached_milestone(self):
        """Si el portafolio ya cubre el milestone, months_to_reach = 0 y reached = True."""
        results = self._run(100000, 1000, 1000, 0.12, [0.25])
        assert results[0]["reached"] is True
        assert results[0]["months_to_reach"] == 0

    def test_not_reached_milestone_has_positive_months(self):
        results = self._run(1000, 500, 2000, 0.12, [0.25])
        assert results[0]["reached"] is False
        assert results[0]["months_to_reach"] > 0

    def test_returns_one_result_per_milestone(self):
        results = self._run(5000, 500, 2000, 0.12, [0.25, 0.50, 1.0])
        assert len(results) == 3

    def test_required_capital_formula(self):
        """required_capital = (expenses * milestone * 12) / annual_return."""
        results = self._run(0, 0, 1000, 0.12, [0.25])
        # (1000 * 0.25 * 12) / 0.12 = 25000
        assert abs(results[0]["required_capital_usd"] - 25000) < 1

    def test_projected_date_is_in_future_for_unreached(self):
        from datetime import date
        results = self._run(1000, 500, 2000, 0.12, [1.0])
        if not results[0]["reached"]:
            projected = date.fromisoformat(results[0]["projected_date"])
            assert projected > date.today()

    def test_milestone_pct_in_result(self):
        results = self._run(5000, 500, 2000, 0.12, [0.50])
        assert results[0]["milestone_pct"] == 0.50


# ── Sanity: todos los tipos en sus buckets correctos ──────────────────────────

class TestBucketClassification:
    @pytest.mark.parametrize("asset_type", RENTA_ASSET_TYPES)
    def test_renta_types_go_to_renta(self, asset_type):
        b = split_portfolio_buckets([pos(asset_type, 1000, 0.50)])
        assert b["renta_total_usd"] > 0
        assert b["capital_total_usd"] == 0

    @pytest.mark.parametrize("asset_type", CAPITAL_ASSET_TYPES)
    def test_capital_types_go_to_capital(self, asset_type):
        b = split_portfolio_buckets([pos(asset_type, 1000, 0.10)])
        assert b["capital_total_usd"] > 0
        assert b["renta_total_usd"] == 0

    @pytest.mark.parametrize("asset_type", AMBOS_ASSET_TYPES)
    def test_ambos_types_split(self, asset_type):
        b = split_portfolio_buckets([pos(asset_type, 1000, 0.10)])
        assert b["renta_total_usd"] == Decimal("500")
        assert b["capital_total_usd"] == Decimal("500")
