"""
TDD tests para las funciones de LECAPs via ArgentinaDatos:
  - get_lecap_tna_by_ticker(ticker)
  - get_lecap_market_tna()

Benchmark confirmado 2026-04-10:
  S15Y6: vpv=105.178, vto=2026-05-15 (confirmado via spike real de BYMA alternativo)
  S31G6: precio técnico ~113.82
  Tasas de mercado LECAP argentinas en abril 2026: ~30-35% TNA
"""

import time
from unittest.mock import patch, MagicMock

import pytest

import app.services.fci_prices as fci_mod
from app.services.fci_prices import (
    get_lecap_tna_by_ticker,
    get_lecap_market_tna,
    _letras_cache,
    _fetch_letras,
)


@pytest.fixture(autouse=True)
def clear_cache():
    _letras_cache["data"] = {}
    _letras_cache["ts"] = 0.0
    yield
    _letras_cache["data"] = {}
    _letras_cache["ts"] = 0.0


# ── _fetch_letras ──────────────────────────────────────────────────────────────

def _mock_response(items: list[dict], status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.is_success = (status == 200)
    mock.json.return_value = items
    return mock


SAMPLE_LETRAS = [
    {"ticker": "S15Y6", "vpv": 97.5, "fechaVencimiento": "2026-05-15"},
    {"ticker": "S31G6", "vpv": 96.2, "fechaVencimiento": "2026-06-30"},
    {"ticker": "X29Y6", "vpv": 118.0, "fechaVencimiento": "2026-09-29"},  # CER, vpv > 100
    {"ticker": "T17O6", "vpv": 94.8, "fechaVencimiento": "2026-10-17"},
]


def test_fetch_letras_parses_correctly():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        data = _fetch_letras()
    assert "S15Y6" in data
    assert data["S15Y6"]["vpv"] == 97.5
    assert data["S15Y6"]["vencimiento"] == "2026-05-15"


def test_fetch_letras_http_error_returns_empty():
    with patch("httpx.get", return_value=_mock_response([], status=400)):
        data = _fetch_letras()
    assert data == {}


def test_fetch_letras_exception_returns_empty():
    with patch("httpx.get", side_effect=Exception("timeout")):
        data = _fetch_letras()
    assert data == {}


def test_fetch_letras_cache_hit():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)) as mock_get:
        _fetch_letras()
        _fetch_letras()
    assert mock_get.call_count == 1


def test_fetch_letras_cache_expired_refetches():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)) as mock_get:
        _fetch_letras()
        _letras_cache["ts"] = time.time() - 700  # expirar
        _fetch_letras()
    assert mock_get.call_count == 2


# ── get_lecap_tna_by_ticker ────────────────────────────────────────────────────

def test_get_lecap_tna_by_ticker_s15y6():
    """S15Y6 con vpv=97.5 y 35 días al vto debe dar TNA razonable ~30-36%."""
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        tna = get_lecap_tna_by_ticker("S15Y6")
    assert tna is not None
    # (100/97.5 - 1) * (365/35) * 100 ≈ 26.7% — varía según fecha de test
    # En abril 2026 con 35 días: ~26-40% es rango razonable
    assert 15.0 <= tna <= 50.0


def test_get_lecap_tna_by_ticker_not_found():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        result = get_lecap_tna_by_ticker("XXXXXXXXX")
    assert result is None


def test_get_lecap_tna_by_ticker_cer_vpv_over_par():
    """X29Y6 con vpv=118 (CER con valor nominal ajustado) → None porque vpv >= 100."""
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        result = get_lecap_tna_by_ticker("X29Y6")
    assert result is None


def test_get_lecap_tna_by_ticker_argdata_unavailable():
    with patch("httpx.get", side_effect=Exception("network error")):
        result = get_lecap_tna_by_ticker("S15Y6")
    assert result is None


def test_get_lecap_tna_by_ticker_case_insensitive():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        upper = get_lecap_tna_by_ticker("S15Y6")
        _letras_cache["data"] = {}
        _letras_cache["ts"] = 0.0
        with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
            lower = get_lecap_tna_by_ticker("s15y6")
    assert upper == lower


def test_get_lecap_tna_by_ticker_vpv_exact_100_returns_none():
    """vpv == 100 es el límite: la fórmula da TNA=0 exactamente, retornar None."""
    letras_at_par = [{"ticker": "S01Z6", "vpv": 100.0, "fechaVencimiento": "2026-12-01"}]
    with patch("httpx.get", return_value=_mock_response(letras_at_par)):
        result = get_lecap_tna_by_ticker("S01Z6")
    assert result is None


# ── get_lecap_market_tna ───────────────────────────────────────────────────────

def test_get_lecap_market_tna_returns_float():
    with patch("httpx.get", return_value=_mock_response(SAMPLE_LETRAS)):
        tna = get_lecap_market_tna()
    assert tna is not None
    assert isinstance(tna, float)
    # Solo S-prefix con vpv < 100: S15Y6=97.5, S31G6=96.2, T17O6 excluido (no S-prefix)
    assert 10.0 <= tna <= 60.0


def test_get_lecap_market_tna_excludes_cer():
    """X-prefix no debe entrar en el promedio de mercado nominal."""
    only_cer = [{"ticker": "X29Y6", "vpv": 118.0, "fechaVencimiento": "2026-09-29"}]
    with patch("httpx.get", return_value=_mock_response(only_cer)):
        result = get_lecap_market_tna()
    assert result is None


def test_get_lecap_market_tna_no_data():
    with patch("httpx.get", side_effect=Exception("down")):
        result = get_lecap_market_tna()
    assert result is None


# ── integración: byma_client fallback chain ────────────────────────────────────

def test_byma_get_lecap_tna_falls_back_to_argentinadatos_on_400():
    """Si BYMA retorna 400, get_lecap_tna() debe intentar ArgentinaDatos."""
    import app.services.byma_client as byma_mod
    byma_mod._lecap_cache["value"] = None
    byma_mod._lecap_cache["ts"] = 0.0

    byma_response = MagicMock()
    byma_response.status_code = 400

    with patch("httpx.get", return_value=byma_response):
        with patch(
            "app.services.fci_prices.get_lecap_market_tna",
            return_value=31.8,
        ):
            tna = byma_mod.get_lecap_tna()

    assert tna == 31.8


def test_byma_get_lecap_tna_hardcoded_fallback_when_both_fail():
    """Si BYMA y ArgentinaDatos fallan → LECAP_TNA_FALLBACK (32%)."""
    import app.services.byma_client as byma_mod
    byma_mod._lecap_cache["value"] = None
    byma_mod._lecap_cache["ts"] = 0.0

    byma_response = MagicMock()
    byma_response.status_code = 400

    with patch("httpx.get", return_value=byma_response):
        with patch(
            "app.services.fci_prices.get_lecap_market_tna",
            return_value=None,
        ):
            tna = byma_mod.get_lecap_tna()

    assert tna == byma_mod.LECAP_TNA_FALLBACK
