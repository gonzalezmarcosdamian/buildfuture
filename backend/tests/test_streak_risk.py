"""
Tests para compute_streak_risk — alerta de racha mensual en riesgo.

Corre con: pytest backend/tests/test_streak_risk.py -v
"""

from datetime import date

from app.routers.portfolio import compute_streak_risk, STREAK_RISK_DAYS


def _calendar(invested_flags: list[bool]) -> list[dict]:
    """Construye un calendario de 12 meses; el último elemento es el mes actual."""
    return [
        {"month": f"2026-{i + 1:02d}-01", "invested": flag}
        for i, flag in enumerate(invested_flags)
    ]


# 12 meses: los primeros 11 con inversión, el último (mes actual) sin invertir.
_PREV_STREAK_11 = _calendar([True] * 11 + [False])
_ALL_INVESTED = _calendar([True] * 12)
_NO_STREAK = _calendar([False] * 12)


class TestComputeStreakRisk:
    def test_at_risk_when_late_in_month_and_streak_alive(self):
        # Día 28 de un mes de 31 → quedan 3 días (<= umbral) y hay racha previa.
        result = compute_streak_risk(
            _PREV_STREAK_11, current_month_invested=False, today=date(2026, 1, 28)
        )
        assert result["at_risk"] is True
        assert result["days_left"] == 3
        assert result["streak_to_keep"] == 11

    def test_not_at_risk_early_in_month(self):
        # Día 5 → quedan 26 días, todavía hay tiempo de sobra.
        result = compute_streak_risk(
            _PREV_STREAK_11, current_month_invested=False, today=date(2026, 1, 5)
        )
        assert result["at_risk"] is False
        assert result["streak_to_keep"] == 11

    def test_not_at_risk_when_already_invested_this_month(self):
        result = compute_streak_risk(
            _ALL_INVESTED, current_month_invested=True, today=date(2026, 1, 30)
        )
        assert result["at_risk"] is False

    def test_not_at_risk_without_previous_streak(self):
        # Nunca invirtió → no hay racha que perder, no tiene sentido alarmar.
        result = compute_streak_risk(
            _NO_STREAK, current_month_invested=False, today=date(2026, 1, 30)
        )
        assert result["at_risk"] is False
        assert result["streak_to_keep"] == 0

    def test_streak_to_keep_breaks_on_gap(self):
        # Patrón: ...True, True, False(mes pasado), False(actual). La racha previa se cortó.
        cal = _calendar([True] * 9 + [False, True, False])
        result = compute_streak_risk(
            cal, current_month_invested=False, today=date(2026, 1, 30)
        )
        assert result["streak_to_keep"] == 1  # solo el mes pasado

    def test_days_left_uses_real_month_length(self):
        # Febrero 2026 tiene 28 días.
        result = compute_streak_risk(
            _PREV_STREAK_11, current_month_invested=False, today=date(2026, 2, 25)
        )
        assert result["days_left"] == 3

    def test_boundary_exactly_at_threshold(self):
        # days_left == STREAK_RISK_DAYS debe alarmar (umbral inclusivo).
        day = 31 - STREAK_RISK_DAYS
        result = compute_streak_risk(
            _PREV_STREAK_11, current_month_invested=False, today=date(2026, 1, day)
        )
        assert result["days_left"] == STREAK_RISK_DAYS
        assert result["at_risk"] is True
