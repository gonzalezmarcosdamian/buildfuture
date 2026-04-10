"""
Tests de yield_updater.py
Corre con: pytest backend/tests/test_yield_updater.py -v
"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.yield_updater import (
    _parse_lecap_maturity,
    _lecap_tir,
    _yield_lecap,
    _yield_bond,
    _yield_fci,
    update_yields,
)


# ── _parse_lecap_maturity ──────────────────────────────────────────────────────

class TestParseLecapMaturity:
    def test_agosto_2026(self):
        assert _parse_lecap_maturity("S31G6") == date(2026, 8, 31)

    def test_febrero_2026(self):
        assert _parse_lecap_maturity("S28F6") == date(2026, 2, 28)

    def test_junio_2026(self):
        assert _parse_lecap_maturity("S30J6") == date(2026, 6, 30)

    def test_enero_2027(self):
        assert _parse_lecap_maturity("S16E7") == date(2027, 1, 16)

    def test_diciembre_2025(self):
        assert _parse_lecap_maturity("S12D5") == date(2025, 12, 12)

    def test_mayo_lowercase(self):
        # Y = mayo, case insensitive
        assert _parse_lecap_maturity("s30y6") == date(2026, 5, 30)

    def test_dia_invalido_ajustado(self):
        # S31F6 → feb no tiene 31 → ajusta a 28
        result = _parse_lecap_maturity("S31F6")
        assert result == date(2026, 2, 28)

    def test_ticker_invalido(self):
        assert _parse_lecap_maturity("AL30") is None
        assert _parse_lecap_maturity("GD30") is None
        assert _parse_lecap_maturity("GGAL") is None
        assert _parse_lecap_maturity("") is None

    def test_ticker_sin_letra_de_mes(self):
        # Si la letra no está en el mapa
        assert _parse_lecap_maturity("S31X6") is None


# ── _lecap_tir ────────────────────────────────────────────────────────────────

class TestLecapTir:
    def test_tir_basica(self):
        # precio 96.5, 180 días → (100/96.5 - 1) × (365/180) ≈ 0.0735
        price = Decimal("96.5")
        days = 180
        tir = _lecap_tir(price, days)
        expected = (Decimal("100") / Decimal("96.5") - Decimal("1")) * (Decimal("365") / Decimal("180"))
        assert abs(tir - expected) < Decimal("0.0001")

    def test_precio_100_tir_cero(self):
        # precio exactamente 100 → sin ganancia → TIR 0
        assert _lecap_tir(Decimal("100"), 180) == Decimal("0")

    def test_precio_negativo_fallback(self):
        assert _lecap_tir(Decimal("-1"), 180) == Decimal("0.40")

    def test_dias_cero_fallback(self):
        assert _lecap_tir(Decimal("96"), 0) == Decimal("0.40")

    def test_precio_mayor_100_tir_negativa_clampada(self):
        # precio > 100 → TIR negativa → clampada a 0
        assert _lecap_tir(Decimal("101"), 180) == Decimal("0")

    def test_rango_realista(self):
        # precio 95% de par, 90 días → TIR ≈ 0.21 TNA
        tir = _lecap_tir(Decimal("95"), 90)
        assert Decimal("0.10") < tir < Decimal("0.50")

    def test_rango_alta_tna(self):
        # precio 95% de par, 30 días → TIR ≈ 0.64 TNA (alta por plazo corto)
        tir = _lecap_tir(Decimal("95"), 30)
        assert Decimal("0.40") < tir < Decimal("1.00")


# ── _yield_lecap (integración con pos mock) ───────────────────────────────────

class TestYieldLecap:
    def _make_pos(self, ticker, quantity, value_ars):
        pos = MagicMock()
        pos.ticker = ticker
        pos.quantity = Decimal(str(quantity))
        pos.current_value_ars = Decimal(str(value_ars))
        pos.asset_type = "LETRA"
        return pos

    def test_lecap_activa(self):
        # S31G6 vence 2026-08-31; hoy simulado 2026-04-01 → ~152 días
        # Para ~68% TNA a 152 días: precio ≈ 100/(1+0.68*152/365) ≈ 78
        # quantity=10_000 nominales, value_ars=7_800 → price_per_100=78
        # TIR esperada ≈ (100/78-1)*(365/152) ≈ 67.7% TNA
        today = date(2026, 4, 1)
        pos = self._make_pos("S31G6", 10_000, 7_800)
        result = _yield_lecap(pos, today)
        assert result is not None
        assert Decimal("0.50") < result < Decimal("0.90")

    def test_lecap_vencida(self):
        today = date(2027, 1, 1)  # S31G6 vence 2026-08-31, ya venció
        pos = self._make_pos("S31G6", 10_000, 975_000)
        result = _yield_lecap(pos, today)
        assert result == Decimal("0")

    def test_ticker_invalido(self):
        pos = self._make_pos("AL30", 100, 50_000)
        result = _yield_lecap(pos, date(2026, 4, 1))
        assert result is None

    def test_sin_cantidad(self):
        pos = self._make_pos("S31G6", 0, 975_000)
        result = _yield_lecap(pos, date(2026, 4, 1))
        assert result is None

    def test_precio_tecnico_acumulado_usa_tna_mercado(self):
        # IOL muestra "precio técnico" acumulado > 100 para LECAPs en cartera.
        # Cuando precio >= 100, _yield_lecap usa get_lecap_tna() (promedio de mercado BYMA).
        pos = self._make_pos("S31G6", 349_344, 400_348)
        with patch("app.services.byma_client.get_lecap_tea_by_ticker", return_value=None), \
             patch("app.services.fci_prices.get_lecap_tna_by_ticker", return_value=None), \
             patch("app.services.byma_client.get_lecap_tna", return_value=32.0):
            result = _yield_lecap(pos, date(2026, 4, 2))
        # 32.0% → Decimal("0.32")
        assert result == Decimal("0.32")

    def test_precio_tecnico_acumulado_usa_tea_byma_si_disponible(self):
        # Si BYMA provee TEA exacta para el ticker, la usa (más precisa que el promedio).
        pos = self._make_pos("S31G6", 349_344, 400_348)
        with patch("app.services.byma_client.get_lecap_tea_by_ticker", return_value=27.5):
            result = _yield_lecap(pos, date(2026, 4, 2))
        # 27.5% → Decimal("0.275")
        assert result == Decimal("0.275")

    def test_precio_exactamente_100_usa_tna_mercado(self):
        # precio = 100 exacto → interpretamos como acumulado → usa TNA de mercado
        pos = self._make_pos("S31G6", 10_000, 10_000)
        with patch("app.services.byma_client.get_lecap_tea_by_ticker", return_value=None), \
             patch("app.services.fci_prices.get_lecap_tna_by_ticker", return_value=None), \
             patch("app.services.byma_client.get_lecap_tna", return_value=32.0):
            result = _yield_lecap(pos, date(2026, 4, 2))
        assert result == Decimal("0.32")


# ── _yield_bond ───────────────────────────────────────────────────────────────

class TestYieldBond:
    def _make_pos(self, ticker):
        pos = MagicMock()
        pos.ticker = ticker
        return pos

    def test_al30_conocido(self):
        assert _yield_bond(self._make_pos("AL30")) == Decimal("0.17")

    def test_gd30_conocido(self):
        assert _yield_bond(self._make_pos("GD30")) == Decimal("0.16")

    def test_ticker_lowercase(self):
        assert _yield_bond(self._make_pos("al30")) == Decimal("0.17")

    def test_ticker_desconocido(self):
        assert _yield_bond(self._make_pos("XYZW")) is None


# ── update_yields (integración con DB mock) ────────────────────────────────────

class TestUpdateYields:
    def _make_pos(self, asset_type, ticker, annual_yield_pct, quantity=10_000, value_ars=975_000):
        pos = MagicMock()
        pos.asset_type = asset_type
        pos.ticker = ticker
        pos.annual_yield_pct = Decimal(str(annual_yield_pct))
        pos.quantity = Decimal(str(quantity))
        pos.current_value_ars = Decimal(str(value_ars))
        return pos

    def _make_db(self, positions):
        db = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.all.return_value = positions
        query_mock.filter.return_value = filter_mock
        db.query.return_value = query_mock
        return db

    def test_actualiza_lecap(self):
        # quantity=10_000 nominales a 97.5% par → value_ars=9_750
        pos = self._make_pos("LETRA", "S31G6", "0.40", quantity=10_000, value_ars=9_750)
        db = self._make_db([pos])
        today = date(2026, 4, 1)
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = today
            # date(y, m, d) must still construct real dates for _parse_lecap_maturity
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = update_yields(db)
        assert n == 1
        db.commit.assert_called_once()

    def test_no_actualiza_si_sin_cambio(self):
        pos = self._make_pos("LETRA", "S31G6", "0.40", quantity=10_000, value_ars=9_750)
        today = date(2026, 4, 1)
        # Pre-compute real yield to set it as current value (no change scenario)
        expected = _yield_lecap(pos, today)
        pos.annual_yield_pct = expected
        db = self._make_db([pos])
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = update_yields(db)
        assert n == 0

    def test_actualiza_bond(self):
        pos = self._make_pos("BOND", "AL30", "0.09")  # viejo valor hardcodeado
        db = self._make_db([pos])
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            n = update_yields(db)
        assert n == 1
        assert pos.annual_yield_pct == Decimal("0.17")

    def test_sin_posiciones(self):
        db = self._make_db([])
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            n = update_yields(db)
        assert n == 0
        db.commit.assert_not_called()

    def test_error_en_posicion_no_rompe_el_loop(self):
        pos_ok = self._make_pos("BOND", "GD30", "0.09")
        pos_bad = MagicMock()
        pos_bad.asset_type = "LETRA"
        pos_bad.ticker = "S31G6"
        pos_bad.quantity = Decimal("1")
        pos_bad.current_value_ars = Decimal("100")
        # Forzar error al asignar
        type(pos_bad).annual_yield_pct = property(
            lambda self: Decimal("0.40"),
            MagicMock(side_effect=RuntimeError("db error")),
        )
        db = self._make_db([pos_ok, pos_bad])
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            n = update_yields(db)
        # Al menos pos_ok fue actualizada
        assert n >= 1

    def test_actualiza_fci_con_promedio_mercado(self):
        """FCI sin external_id usa el promedio de mercado."""
        pos = self._make_pos("FCI", "IOLMMA", "0.08")
        pos.external_id = None
        pos.fci_categoria = None
        db = self._make_db([pos])
        market_yield = Decimal("0.42")
        with patch("app.services.yield_updater._fci_market_avg_yield", return_value=market_yield), \
             patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = update_yields(db)
        assert n == 1
        assert pos.annual_yield_pct == market_yield

    def test_actualiza_fci_con_external_id(self):
        """FCI con external_id usa ArgentinaDatos exacto."""
        pos = self._make_pos("FCI", "IOLMMA", "0.08")
        pos.external_id = "Balanz Capital Money Market - Clase A"
        pos.fci_categoria = "mercadoDinero"
        db = self._make_db([pos])
        with patch("app.services.fci_prices.get_yield_30d", return_value=0.415), \
             patch("app.services.yield_updater._fci_market_avg_yield", return_value=Decimal("0.38")), \
             patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = update_yields(db)
        assert n == 1
        assert abs(float(pos.annual_yield_pct) - 0.415) < 0.001

    def test_mep_actualiza_current_price_usd_letra(self):
        """Con MEP provisto, recalcula current_price_usd para LETRA."""
        pos = self._make_pos("LETRA", "S31G6", "0.40", quantity=10_000, value_ars=7_800)
        pos.current_price_usd = Decimal("0.005")  # precio viejo/congelado
        pos.external_id = None
        pos.fci_categoria = None
        db = self._make_db([pos])
        mep = Decimal("1400")
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            n = update_yields(db, mep=mep)
        # new_price = 7800 / (10000 * 1400) = 0.000557...
        expected_price = Decimal("7800") / (Decimal("10000") * mep)
        assert abs(pos.current_price_usd - expected_price) < Decimal("0.000001")
        assert n >= 1  # fue marcado como changed

    def test_mep_none_no_toca_current_price_usd(self):
        """Sin MEP, current_price_usd no se modifica."""
        pos = self._make_pos("LETRA", "S31G6", "0.40", quantity=10_000, value_ars=7_800)
        original_price = Decimal("0.005")
        pos.current_price_usd = original_price
        pos.external_id = None
        pos.fci_categoria = None
        db = self._make_db([pos])
        with patch("app.services.yield_updater.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            update_yields(db, mep=None)
        assert pos.current_price_usd == original_price


# ── _yield_fci ────────────────────────────────────────────────────────────────

class TestYieldFci:
    def _make_pos(self, ticker, external_id=None, fci_categoria=None):
        pos = MagicMock()
        pos.ticker = ticker
        pos.asset_type = "FCI"
        pos.external_id = external_id
        pos.fci_categoria = fci_categoria
        return pos

    def test_sin_external_id_usa_promedio(self):
        pos = self._make_pos("IOLMMA")
        market_avg = Decimal("0.42")
        result = _yield_fci(pos, market_avg)
        assert result == market_avg

    def test_con_external_id_usa_argentinadatos(self):
        pos = self._make_pos("IOLMMA", "Balanz Capital Money Market - Clase A", "mercadoDinero")
        market_avg = Decimal("0.38")
        with patch("app.services.fci_prices.get_yield_30d", return_value=0.415):
            result = _yield_fci(pos, market_avg)
        assert abs(float(result) - 0.415) < 0.001

    def test_external_id_falla_cae_a_promedio(self):
        pos = self._make_pos("IOLMMA", "Fondo Inexistente", "mercadoDinero")
        market_avg = Decimal("0.38")
        with patch("app.services.fci_prices.get_yield_30d", return_value=0.0):
            result = _yield_fci(pos, market_avg)
        assert result == market_avg

    def test_external_id_yield_outlier_cae_a_promedio(self):
        # Si ArgentinaDatos devuelve TNA > 200% (match incorrecto), cae a promedio.
        pos = self._make_pos("IOLCAMA", "Fondo Erróneo", "mercadoDinero")
        market_avg = Decimal("0.38")
        with patch("app.services.fci_prices.get_yield_30d", return_value=1.988):  # 198.8% TNA
            result = _yield_fci(pos, market_avg)
        assert result == market_avg
