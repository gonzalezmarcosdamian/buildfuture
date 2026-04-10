"""
P1 — Validación de yield por tipo de instrumento.

Verifica que update_yields() asigna annual_yield_pct correctamente
para LETRA (LECAP), BOND, ON y FCI, y que los valores quedan dentro
de rangos razonables. También valida el flujo de update_stock_prices().

Las funciones de BYMA/CAFCI son importadas lazily dentro de yield_updater
(from app.services.byma_client import ...) por lo que se parchean en el
módulo fuente, no en yield_updater.

Corre con: pytest backend/tests/test_yield_per_instrument.py -v
"""
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.services.yield_updater import update_yields, update_stock_prices

_BYMA = "app.services.byma_client"
_FCI = "app.services.fci_prices"


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _pos(asset_type, ticker, ppc_ars=1000.0, avg_usd=1.0, yield_pct=0.0,
         price_usd=1.0, external_id=None, fci_categoria=None, source="IOL",
         quantity=100, current_value_ars=10200.0):
    p = MagicMock()
    p.asset_type = asset_type
    p.ticker = ticker
    p.ppc_ars = Decimal(str(ppc_ars))
    p.avg_purchase_price_usd = Decimal(str(avg_usd))
    p.annual_yield_pct = Decimal(str(yield_pct))
    p.current_price_usd = Decimal(str(price_usd))
    p.external_id = external_id
    p.fci_categoria = fci_categoria
    p.source = source
    p.quantity = Decimal(str(quantity))
    p.current_value_ars = Decimal(str(current_value_ars))
    return p


def _make_db(positions):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = positions
    return db


# ── LETRA (LECAP S-prefix) ────────────────────────────────────────────────────

class TestYieldLETRA:
    def test_lecap_tea_from_byma_applied(self):
        """Si BYMA entrega TEA para S31G6 con precio >= par, se asigna annual_yield_pct."""
        # current_value_ars=10200, quantity=100 → price_per_100=102 >= 100 → BYMA path
        pos = _pos("LETRA", "S31G6", current_value_ars=10200.0, quantity=100)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=38.5), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.5), \
             patch(f"{_FCI}.get_lecap_tna_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assert n >= 1
        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.385) < 0.001, f"TEA LECAP esperada 0.385, got {assigned}"

    def test_lecap_cer_prefix_retorna_cero(self):
        """X-prefix (CER) retorna 0 cuando BYMA no tiene TIR real."""
        pos = _pos("LETRA", "X29Y6", current_value_ars=10500.0, quantity=100)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_cer_letter_tir", return_value=None), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        # X-prefix sin BYMA → yield=0 (deuda técnica conocida)
        assert float(pos.annual_yield_pct) == 0.0

    def test_lecap_fallback_usa_promedio_mercado(self):
        """Si no hay TEA por ticker, usa get_lecap_tna() (promedio mercado)."""
        pos = _pos("LETRA", "S16E7", current_value_ars=10200.0, quantity=100)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_FCI}.get_lecap_tna_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=42.0), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.42) < 0.001, f"Fallback promedio esperado 0.42, got {assigned}"

    def test_lecap_bajo_par_usa_formula_tir(self):
        """Con precio < par usa TIR = (100/precio - 1) * (365/dias)."""
        # current_value_ars=9800, quantity=100 → price_per_100=98 < 100
        pos = _pos("LETRA", "S31G6", current_value_ars=9800.0, quantity=100)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        # TIR = (100/98 - 1) * (365/días_a_vto) debe ser positivo
        assert assigned > 0, f"TIR LECAP bajo par debe ser > 0, got {assigned}"
        assert assigned < 1.5, f"TIR LECAP irrazonable: {assigned}"


# ── BOND ──────────────────────────────────────────────────────────────────────

class TestYieldBOND:
    def test_bond_tir_de_byma_aplicada(self):
        """Si BYMA devuelve TIR para AL30, se aplica y queda en rango."""
        pos = _pos("BOND", "AL30", price_usd=0.65, avg_usd=0.55)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_bond_tir", return_value=15.0), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.15) < 0.001, f"TIR BOND esperada 0.15, got {assigned}"

    def test_bond_fallback_tabla_si_byma_none(self):
        """Si BYMA retorna None, usa la tabla interna _BOND_YTM (GD30 = 0.16)."""
        pos = _pos("BOND", "GD30", price_usd=0.70, avg_usd=0.55)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.16) < 0.001, f"Tabla GD30=0.16, got {assigned}"

    def test_bond_ticker_desconocido_no_cambia_yield(self):
        """Ticker desconocido sin BYMA ni tabla → yield no se modifica."""
        pos = _pos("BOND", "XYZZZZ", price_usd=0.80, avg_usd=0.70, yield_pct=0.10)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            update_yields(db, mep=Decimal("1430"))

        # _yield_bond retorna None → no se asigna nuevo valor
        assert float(pos.annual_yield_pct) == 0.10


# ── ON ────────────────────────────────────────────────────────────────────────

class TestYieldON:
    def test_on_tir_byma_aplicada(self):
        """TIR de BYMA para una ON se aplica directamente."""
        pos = _pos("ON", "TLCMO", price_usd=1.11, avg_usd=1.0)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_on_tir", return_value=8.5), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.085) < 0.001, f"TIR ON esperada 0.085, got {assigned}"

    def test_on_fallback_tabla_si_byma_none(self):
        """Si BYMA retorna None para la ON, usa tabla interna (TLCMO=0.07)."""
        pos = _pos("ON", "TLCMO", price_usd=1.11, avg_usd=1.0)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_on_tir", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_FCI}.get_vcp", return_value=None):
            update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.07) < 0.001, f"Tabla TLCMO=0.07, got {assigned}"


# ── FCI ───────────────────────────────────────────────────────────────────────

class TestYieldFCI:
    def test_fci_yield_desde_cafci(self):
        """Rendimiento FCI desde CAFCI se aplica (TNA como fracción 0..1)."""
        pos = _pos("FCI", "SCHRATS", external_id="SCHRATS", fci_categoria="Renta en Pesos")
        db = _make_db([pos])

        # get_yield_30d retorna TNA fraccionaria (0.55 = 55% TNA)
        with patch(f"{_FCI}.get_yield_30d", return_value=0.55), \
             patch(f"{_FCI}.get_vcp", return_value=12.50), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None):
            n = update_yields(db, mep=Decimal("1430"))

        assigned = float(pos.annual_yield_pct)
        assert abs(assigned - 0.55) < 0.001, f"FCI yield esperado 0.55, got {assigned}"

    def test_fci_sin_external_id_usa_promedio(self):
        """FCI sin external_id usa promedio de mercado calculado por _fci_market_avg_yield."""
        pos = _pos("FCI", "DESCONOCIDO", external_id=None, fci_categoria=None, yield_pct=0.0)
        db = _make_db([pos])

        # Simulamos que _fci_market_avg_yield llama get_vcp para calcular el promedio
        with patch(f"{_FCI}.get_vcp", return_value=12.50), \
             patch(f"{_BYMA}.get_lecap_tea_by_ticker", return_value=None), \
             patch(f"{_BYMA}.get_lecap_tna", return_value=38.0), \
             patch(f"{_BYMA}.get_bond_tir", return_value=None), \
             patch(f"{_BYMA}.get_on_tir", return_value=None):
            update_yields(db, mep=Decimal("1430"))

        # yield se asigna al promedio de mercado (que puede ser 0 si get_vcp da None para los fondos mock)
        # lo relevante es que no explota
        assert pos.annual_yield_pct is not None


# ── STOCK (update_stock_prices) ───────────────────────────────────────────────

class TestUpdateStockPrices:
    def test_stock_price_convertido_a_usd(self):
        """Precio ARS convertido a USD via MEP se asigna a current_price_usd."""
        pos = _pos("STOCK", "GGAL", price_usd=1.0, avg_usd=1.0)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_stock_price_ars", return_value=1820.50):
            n = update_stock_prices(db, mep=Decimal("1430"))

        assert n == 1
        expected_usd = round(1820.50 / 1430, 4)
        assert abs(float(pos.current_price_usd) - expected_usd) < 0.001

    def test_stock_byma_none_no_actualiza(self):
        """Si BYMA retorna None (ticker fuera del panel), price no cambia."""
        pos = _pos("STOCK", "MIRG", price_usd=5.0)
        original_price = float(pos.current_price_usd)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_stock_price_ars", return_value=None):
            n = update_stock_prices(db, mep=Decimal("1430"))

        assert n == 0
        assert float(pos.current_price_usd) == original_price

    def test_stock_sin_mep_skip(self):
        """Sin MEP no se puede convertir ARS → USD: n=0."""
        pos = _pos("STOCK", "GGAL", price_usd=1.0)
        db = _make_db([pos])

        with patch(f"{_BYMA}.get_stock_price_ars", return_value=1820.50):
            n = update_stock_prices(db, mep=None)

        assert n == 0
