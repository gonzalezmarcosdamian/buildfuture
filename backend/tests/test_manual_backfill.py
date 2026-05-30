"""
Tests para manual_backfill — retropolado de historial de posiciones manuales.

Corre con: pytest backend/tests/test_manual_backfill.py -v
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.manual_backfill import build_manual_value_series


def _pos(
    asset_type="CASH", quantity="1000", current_value_usd="1000", current_price_usd="1"
):
    return SimpleNamespace(
        asset_type=asset_type,
        quantity=Decimal(quantity),
        current_value_usd=Decimal(current_value_usd),
        current_price_usd=Decimal(current_price_usd),
        external_id=None,
    )


class TestBuildManualValueSeries:
    def test_flat_value_for_cash(self):
        pos = _pos(asset_type="CASH", quantity="500", current_value_usd="500")
        series = build_manual_value_series(pos, date(2026, 1, 1), date(2026, 1, 5))
        # Días 1..4 (ayer = 4, hoy = 5 excluido).
        assert len(series) == 4
        assert all(v == Decimal("500") for v in series.values())
        assert date(2026, 1, 5) not in series  # hoy lo cubre el flujo normal

    def test_excludes_today(self):
        pos = _pos()
        series = build_manual_value_series(pos, date(2026, 1, 1), date(2026, 1, 10))
        assert date(2026, 1, 10) not in series
        assert max(series) == date(2026, 1, 9)

    def test_empty_when_purchase_date_is_today_or_future(self):
        pos = _pos()
        assert (
            build_manual_value_series(pos, date(2026, 1, 10), date(2026, 1, 10)) == {}
        )
        assert (
            build_manual_value_series(pos, date(2026, 1, 15), date(2026, 1, 10)) == {}
        )

    def test_real_estate_flat(self):
        pos = _pos(asset_type="REAL_ESTATE", quantity="1", current_value_usd="120000")
        series = build_manual_value_series(pos, date(2026, 1, 1), date(2026, 1, 4))
        assert len(series) == 3
        assert all(v == Decimal("120000") for v in series.values())

    def test_crypto_uses_historical_prices(self):
        pos = _pos(
            asset_type="CRYPTO",
            quantity="2",
            current_value_usd="200",
            current_price_usd="100",
        )
        history = {
            date(2026, 1, 1): 40.0,
            date(2026, 1, 2): 50.0,
            date(2026, 1, 3): 60.0,
        }
        series = build_manual_value_series(
            pos, date(2026, 1, 1), date(2026, 1, 4), history
        )
        assert series[date(2026, 1, 1)] == Decimal("2") * Decimal("40.0")
        assert series[date(2026, 1, 2)] == Decimal("2") * Decimal("50.0")
        assert series[date(2026, 1, 3)] == Decimal("2") * Decimal("60.0")

    def test_crypto_fills_gaps_with_nearest_prior(self):
        # Falta el día 3 → lookup_price usa el precio del día 2 (más cercano hacia atrás).
        pos = _pos(asset_type="CRYPTO", quantity="1")
        history = {date(2026, 1, 2): 50.0}
        series = build_manual_value_series(
            pos, date(2026, 1, 2), date(2026, 1, 5), history
        )
        assert series[date(2026, 1, 2)] == Decimal("50.0")
        assert series[date(2026, 1, 3)] == Decimal("50.0")
        assert series[date(2026, 1, 4)] == Decimal("50.0")

    def test_crypto_without_history_falls_back_to_flat(self):
        pos = _pos(asset_type="CRYPTO", quantity="2", current_value_usd="200")
        series = build_manual_value_series(pos, date(2026, 1, 1), date(2026, 1, 4), {})
        assert all(v == Decimal("200") for v in series.values())
