"""
Tests para las funciones puras de historical_reconstructor.py — la reconstrucción
del historial de tenencia desde operaciones IOL (la lógica más sensible del gráfico).

Corre con: pytest backend/tests/test_historical_reconstructor.py -v
"""

from datetime import date

from app.services.historical_reconstructor import (
    _parse_operations_v2,
    _qty_at,
    _build_reliable_timeline,
    _yahoo_ticker_for,
)


class TestParseOperationsV2:
    def test_skips_non_terminada(self):
        ops = [{"estado": "pendiente", "fechaOrden": "2026-01-10", "simbolo": "AL30",
                "cantidadOperada": 100, "tipo": "compra"}]
        assert _parse_operations_v2(ops) == []

    def test_skips_zero_or_missing_qty(self):
        ops = [
            {"estado": "terminada", "fechaOrden": "2026-01-10", "simbolo": "AL30", "cantidadOperada": 0, "tipo": "compra"},
            {"estado": "terminada", "fechaOrden": "2026-01-10", "simbolo": "AL30", "cantidadOperada": None, "tipo": "compra"},
        ]
        assert _parse_operations_v2(ops) == []

    def test_skips_invalid_date_and_empty_ticker(self):
        ops = [
            {"estado": "terminada", "fechaOrden": "no-date", "simbolo": "AL30", "cantidadOperada": 5, "tipo": "compra"},
            {"estado": "terminada", "fechaOrden": "2026-01-10", "simbolo": "", "cantidadOperada": 5, "tipo": "compra"},
        ]
        assert _parse_operations_v2(ops) == []

    def test_parses_uppercases_and_sorts_by_date(self):
        ops = [
            {"estado": "Terminada", "fechaOrden": "2026-03-01", "simbolo": "ggal", "cantidadOperada": 10, "tipo": "compra", "precioOperado": 50, "montoOperado": 500},
            {"estado": "terminada", "fechaOrden": "2026-01-15", "simbolo": "al30", "cantidadOperada": 100, "tipo": "venta"},
        ]
        parsed = _parse_operations_v2(ops)
        assert [p["ticker"] for p in parsed] == ["AL30", "GGAL"]  # ordenado por fecha
        assert parsed[0]["date"] == date(2026, 1, 15)
        assert parsed[1]["ticker"] == "GGAL"
        assert parsed[1]["qty"] == 10.0
        assert parsed[1]["precio_op"] == 50.0


class TestQtyAt:
    TL = [(date(2026, 1, 10), 50.0), (date(2026, 2, 10), 120.0), (date(2026, 3, 10), 80.0)]

    def test_before_first_event_is_zero(self):
        assert _qty_at(self.TL, date(2026, 1, 1)) == 0.0

    def test_exactly_at_event(self):
        assert _qty_at(self.TL, date(2026, 1, 10)) == 50.0

    def test_between_events_holds_last(self):
        assert _qty_at(self.TL, date(2026, 2, 20)) == 120.0

    def test_after_last_event(self):
        assert _qty_at(self.TL, date(2026, 6, 1)) == 80.0


class TestBuildReliableTimeline:
    def test_buy_unwinds_backward_and_appends_today(self):
        parsed = [{"date": date(2026, 1, 10), "ticker": "AAPL", "qty": 40.0, "tipo": "compra"}]
        result = _build_reliable_timeline(parsed, {"AAPL": 100.0})
        assert "AAPL" in result
        tl = result["AAPL"]
        # evento POST-compra = 100 en la fecha de la op + append de hoy con qty actual
        assert tl[0] == (date(2026, 1, 10), 100.0)
        assert tl[-1][0] == date.today()
        assert tl[-1][1] == 100.0

    def test_ignores_tickers_not_in_current_positions(self):
        parsed = [{"date": date(2026, 1, 10), "ticker": "VENDIDO", "qty": 10.0, "tipo": "compra"}]
        result = _build_reliable_timeline(parsed, {"AAPL": 100.0})
        assert "VENDIDO" not in result

    def test_invisible_sales_stop_older_history(self):
        # Dos compras que sumarían más de lo que se tiene hoy → hubo ventas fuera de ventana
        parsed = [
            {"date": date(2026, 1, 1), "ticker": "X", "qty": 200.0, "tipo": "compra"},
            {"date": date(2026, 2, 1), "ticker": "X", "qty": 30.0, "tipo": "compra"},
        ]
        result = _build_reliable_timeline(parsed, {"X": 50.0})
        # no debe explotar; conserva la historia reciente verificable y termina hoy
        assert result["X"][-1][0] == date.today()


class TestYahooTickerFor:
    def test_cedear_and_etf_passthrough(self):
        assert _yahoo_ticker_for("AAPL", "CEDEAR") == "AAPL"
        assert _yahoo_ticker_for("SPY", "ETF") == "SPY"

    def test_bond_letra_return_none(self):
        assert _yahoo_ticker_for("AL30", "BOND") is None
        assert _yahoo_ticker_for("S31G6", "LETRA") is None
