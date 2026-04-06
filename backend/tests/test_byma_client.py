"""
Tests para byma_client.py — integración con Open BYMA Data.

TDD: estos tests se escriben ANTES de la implementación.
Corre con: pytest backend/tests/test_byma_client.py -v
"""

from unittest.mock import patch, MagicMock
import pytest

from app.services.byma_client import get_lecap_tna, LECAP_TNA_FALLBACK
import app.services.byma_client as bc


# ── Fixture: limpiar cache antes de cada test ─────────────────────────────────

@pytest.fixture(autouse=True)
def clear_cache():
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0
    yield
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _byma_response(items: list[dict]):
    """Simula respuesta JSON de BYMA short-term-government-bonds."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    return mock


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_lecap_tna_calcula_promedio_ponderado():
    """Con dos LECAPs vigentes devuelve promedio ponderado por volumen."""
    items = [
        {"symbol": "S30J6", "last": 98.5, "maturity": "2026-06-30",
         "impliedYield": 52.0, "volume": 1_000_000, "securityType": "LETRA"},
        {"symbol": "S28F7", "last": 97.0, "maturity": "2027-02-28",
         "impliedYield": 48.0, "volume": 500_000, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response(items)):
        tna = get_lecap_tna()

    # promedio ponderado: (52*1M + 48*500K) / 1.5M = 50.67
    assert abs(tna - 50.67) < 0.1


def test_lecap_tna_filtra_vencidas(monkeypatch):
    """LECAPs con maturity en el pasado se ignoran."""
    items = [
        {"symbol": "S01E5", "last": 99.0, "maturity": "2020-01-01",
         "impliedYield": 30.0, "volume": 1_000_000, "securityType": "LETRA"},
        {"symbol": "S30J5", "last": 98.5, "maturity": "2099-06-30",
         "impliedYield": 52.0, "volume": 800_000, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response(items)):
        tna = get_lecap_tna()

    assert abs(tna - 52.0) < 0.1


def test_lecap_tna_ignora_no_letras():
    """Instrumentos que no son LETRA se ignoran aunque estén en la respuesta."""
    items = [
        {"symbol": "AL30", "last": 55.0, "maturity": "2099-07-09",
         "impliedYield": 10.0, "volume": 2_000_000, "securityType": "BONO"},
        {"symbol": "S30J5", "last": 98.5, "maturity": "2099-06-30",
         "impliedYield": 54.0, "volume": 900_000, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response(items)):
        tna = get_lecap_tna()

    assert abs(tna - 54.0) < 0.1


# ── Sad path ──────────────────────────────────────────────────────────────────

def test_lecap_tna_fallback_si_byma_falla():
    """Si BYMA devuelve error HTTP → retorna fallback hardcodeado."""
    with patch("app.services.byma_client.httpx.get", side_effect=Exception("timeout")):
        tna = get_lecap_tna()

    assert tna == LECAP_TNA_FALLBACK


def test_lecap_tna_fallback_si_respuesta_vacia():
    """Si BYMA no devuelve LECAPs (lista vacía) → retorna fallback."""
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response([])):
        tna = get_lecap_tna()

    assert tna == LECAP_TNA_FALLBACK


def test_lecap_tna_fallback_si_todas_vencidas():
    """Si todas las LECAPs están vencidas → retorna fallback."""
    items = [
        {"symbol": "S01E4", "last": 99.0, "maturity": "2020-01-01",
         "impliedYield": 40.0, "volume": 1_000_000, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response(items)):
        tna = get_lecap_tna()

    assert tna == LECAP_TNA_FALLBACK


def test_lecap_tna_fallback_si_implied_yield_cero():
    """LECAP con impliedYield=0 no se incluye en el promedio."""
    items = [
        {"symbol": "S30J5", "last": 100.0, "maturity": "2099-06-30",
         "impliedYield": 0.0, "volume": 1_000_000, "securityType": "LETRA"},
        {"symbol": "S28F5", "last": 98.5, "maturity": "2099-02-28",
         "impliedYield": 51.0, "volume": 600_000, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_byma_response(items)):
        tna = get_lecap_tna()

    assert abs(tna - 51.0) < 0.1


def test_lecap_tna_fallback_si_status_no_200():
    """HTTP 500 de BYMA → retorna fallback."""
    mock = MagicMock()
    mock.status_code = 500
    with patch("app.services.byma_client.httpx.get", return_value=mock):
        tna = get_lecap_tna()

    assert tna == LECAP_TNA_FALLBACK


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_lecap_tna_cache_evita_segundo_http_call():
    """Llamar dos veces seguidas solo hace un HTTP call (cache TTL 5 min)."""
    from app.services import byma_client as bc
    # limpiar cache antes del test
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0

    items = [
        {"symbol": "S30J5", "last": 98.5, "maturity": "2099-06-30",
         "impliedYield": 52.0, "volume": 1_000_000, "securityType": "LETRA"},
    ]
    mock_get = MagicMock(return_value=_byma_response(items))
    with patch("app.services.byma_client.httpx.get", mock_get):
        get_lecap_tna()
        get_lecap_tna()

    assert mock_get.call_count == 1
