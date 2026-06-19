"""
Tests para devaluation.get_expected_devaluation — jerarquía de fuentes, bounds y cache.

Corre con: pytest backend/tests/test_devaluation.py -v
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services import devaluation as dv
from app.services.devaluation import (
    get_expected_devaluation,
    invalidate_cache,
    DEVALUATION_FALLBACK,
    DEVALUATION_MIN,
    DEVALUATION_MAX,
)


@pytest.fixture(autouse=True)
def _clear_cache_and_mep():
    invalidate_cache()
    # get_mep() se llama para mep_spot — evitar network
    with patch("app.services.mep.get_mep", return_value=Decimal("1450")):
        yield
    invalidate_cache()


def _sources(rofex=None, parity=None, trend=None):
    return (
        patch("app.services.devaluation._from_rofex", return_value=rofex),
        patch("app.services.devaluation._from_lecap_on_parity", return_value=parity),
        patch("app.services.devaluation._from_mep_trend", return_value=trend),
    )


class TestGetExpectedDevaluation:
    def test_usa_rofex_si_disponible(self):
        r, p, t = _sources(rofex=0.27)
        with r, p, t:
            assert get_expected_devaluation() == Decimal("0.27")
        assert dv._cache["source"] == "rofex"

    def test_cae_a_paridad_si_rofex_none(self):
        r, p, t = _sources(rofex=None, parity=0.35)
        with r, p, t:
            assert get_expected_devaluation() == Decimal("0.35")
        assert dv._cache["source"] == "lecap_on_parity"

    def test_cae_a_mep_trend_si_los_demas_none(self):
        r, p, t = _sources(rofex=None, parity=None, trend=0.30)
        with r, p, t:
            assert get_expected_devaluation() == Decimal("0.30")

    def test_fallback_si_todas_none(self):
        r, p, t = _sources(rofex=None, parity=None, trend=None)
        with r, p, t:
            assert get_expected_devaluation() == DEVALUATION_FALLBACK

    def test_valor_sobre_el_techo_usa_fallback(self):
        r, p, t = _sources(rofex=1.5)  # 150% > MAX
        with r, p, t:
            assert get_expected_devaluation() == DEVALUATION_FALLBACK

    def test_valor_bajo_el_piso_usa_fallback(self):
        r, p, t = _sources(rofex=0.02)  # 2% < MIN
        with r, p, t:
            assert get_expected_devaluation() == DEVALUATION_FALLBACK

    def test_bordes_min_max_son_validos(self):
        r, p, t = _sources(rofex=DEVALUATION_MIN)
        with r, p, t:
            assert get_expected_devaluation() == Decimal(str(round(DEVALUATION_MIN, 4)))
        invalidate_cache()
        r, p, t = _sources(rofex=DEVALUATION_MAX)
        with r, p, t:
            assert get_expected_devaluation() == Decimal(str(round(DEVALUATION_MAX, 4)))

    def test_cache_evita_recomputar(self):
        r, p, t = _sources(rofex=0.27)
        with r, p, t:
            get_expected_devaluation()
        # segunda llamada: las fuentes ahora devolverían otra cosa, pero el cache manda
        r2, p2, t2 = _sources(rofex=0.50)
        with r2, p2, t2:
            assert get_expected_devaluation() == Decimal("0.27")
