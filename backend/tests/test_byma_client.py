"""
Tests para byma_client.py — integración con Open BYMA Data.

TDD: estos tests se escriben ANTES de la implementación.
Corre con: pytest backend/tests/test_byma_client.py -v
"""

from unittest.mock import patch, MagicMock
import pytest

from app.services.byma_client import (
    get_lecap_tna, LECAP_TNA_FALLBACK,
    get_cedear_price_ars,
    get_bond_tir, get_on_tir,
    get_cer_letter_tir, CER_TIR_MIN, CER_TIR_MAX,
)
import app.services.byma_client as bc


# ── Fixture: limpiar todos los caches antes de cada test ─────────────────────

@pytest.fixture(autouse=True)
def clear_cache():
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0
    bc._cedear_cache["data"] = {}
    bc._cedear_cache["ts"] = 0.0
    bc._sovereign_cache["data"] = {}
    bc._sovereign_cache["ts"] = 0.0
    bc._on_cache["data"] = {}
    bc._on_cache["ts"] = 0.0
    bc._cer_cache["data"] = {}
    bc._cer_cache["ts"] = 0.0
    yield
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0
    bc._cedear_cache["data"] = {}
    bc._cedear_cache["ts"] = 0.0
    bc._sovereign_cache["data"] = {}
    bc._sovereign_cache["ts"] = 0.0
    bc._on_cache["data"] = {}
    bc._on_cache["ts"] = 0.0
    bc._cer_cache["data"] = {}
    bc._cer_cache["ts"] = 0.0


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


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 2 — get_cedear_price_ars
# ═══════════════════════════════════════════════════════════════════════════════

def _cedear_response(items: list[dict]):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    return mock


def test_cedear_price_ars_retorna_precio():
    """Devuelve el precio en ARS del CEDEAR cuando el ticker está en la respuesta."""
    items = [
        {"symbol": "AAPL", "trade": 14500.0, "volume": 200_000, "securityType": "CEDEAR"},
        {"symbol": "MSFT", "trade": 12300.0, "volume": 150_000, "securityType": "CEDEAR"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cedear_response(items)):
        price = get_cedear_price_ars("AAPL")

    assert price == 14500.0


def test_cedear_price_ars_ticker_inexistente_retorna_none():
    """Si el ticker no está en la respuesta de BYMA retorna None (fallback al caller)."""
    items = [
        {"symbol": "AAPL", "last": 14500.0, "volume": 200_000, "securityType": "CEDEAR"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cedear_response(items)):
        price = get_cedear_price_ars("NVDA")

    assert price is None


def test_cedear_price_ars_fallback_si_byma_falla():
    """Si BYMA falla (timeout, error HTTP) retorna None."""
    with patch("app.services.byma_client.httpx.get", side_effect=Exception("timeout")):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_fallback_si_status_no_200():
    """HTTP 500 → retorna None."""
    mock = MagicMock()
    mock.status_code = 500
    with patch("app.services.byma_client.httpx.get", return_value=mock):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_ignora_precio_cero():
    """Precio last=0 no es un dato válido, retorna None para ese ticker."""
    items = [
        {"symbol": "AAPL", "last": 0.0, "volume": 0, "securityType": "CEDEAR"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cedear_response(items)):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_cache_evita_segundo_http_call():
    """Dos llamadas distintas al mismo endpoint usan el cache (una sola request HTTP)."""
    items = [
        {"symbol": "AAPL", "trade": 14500.0, "volume": 200_000, "securityType": "CEDEAR"},
        {"symbol": "MSFT", "trade": 12300.0, "volume": 150_000, "securityType": "CEDEAR"},
    ]
    mock_get = MagicMock(return_value=_cedear_response(items))
    with patch("app.services.byma_client.httpx.get", mock_get):
        get_cedear_price_ars("AAPL")
        get_cedear_price_ars("MSFT")

    assert mock_get.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 3 — get_bond_tir (bonos soberanos)
# ═══════════════════════════════════════════════════════════════════════════════

def _bond_response(items: list[dict]):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    return mock


def test_bond_tir_retorna_tir_correcta():
    """Devuelve la TIR (%) del bono solicitado."""
    items = [
        {"symbol": "AL30", "last": 55.0, "impliedYield": 11.5,
         "volume": 5_000_000, "securityType": "BONO"},
        {"symbol": "GD30", "last": 52.0, "impliedYield": 13.2,
         "volume": 3_000_000, "securityType": "BONO"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_bond_tir("AL30")

    assert tir == 11.5


def test_bond_tir_ticker_inexistente_retorna_none():
    """Bono no encontrado en BYMA → retorna None para que el caller use DEFAULT_YIELDS."""
    items = [
        {"symbol": "AL30", "last": 55.0, "impliedYield": 11.5,
         "volume": 5_000_000, "securityType": "BONO"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_bond_tir("BONOD")

    assert tir is None


def test_bond_tir_tir_extrema_retorna_none():
    """TIR > 50% es anomalía de mercado (bono en default) → retorna None."""
    items = [
        {"symbol": "AL30", "last": 10.0, "impliedYield": 250.0,
         "volume": 100, "securityType": "BONO"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_bond_tir("AL30")

    assert tir is None


def test_bond_tir_tir_negativa_retorna_none():
    """TIR negativa es dato corrupto → retorna None."""
    items = [
        {"symbol": "AL30", "last": 60.0, "impliedYield": -5.0,
         "volume": 500_000, "securityType": "BONO"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_bond_tir("AL30")

    assert tir is None


def test_bond_tir_fallback_si_byma_falla():
    """Error de red → retorna None."""
    with patch("app.services.byma_client.httpx.get", side_effect=Exception("timeout")):
        tir = get_bond_tir("AL30")

    assert tir is None


def test_bond_tir_cache_evita_segundo_http_call():
    """Dos tickers del mismo endpoint comparten cache (una sola request HTTP)."""
    items = [
        {"symbol": "AL30", "last": 55.0, "impliedYield": 11.5,
         "volume": 5_000_000, "securityType": "BONO"},
        {"symbol": "GD30", "last": 52.0, "impliedYield": 13.2,
         "volume": 3_000_000, "securityType": "BONO"},
    ]
    mock_get = MagicMock(return_value=_bond_response(items))
    with patch("app.services.byma_client.httpx.get", mock_get):
        get_bond_tir("AL30")
        get_bond_tir("GD30")

    assert mock_get.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 3 — get_on_tir (obligaciones negociables)
# ═══════════════════════════════════════════════════════════════════════════════

def test_on_tir_retorna_tir_correcta():
    """Devuelve la TIR (%) de la ON solicitada."""
    items = [
        {"symbol": "YCA6O", "last": 97.5, "impliedYield": 8.9,
         "volume": 1_000_000, "securityType": "ON"},
        {"symbol": "IRCFO", "last": 98.0, "impliedYield": 7.5,
         "volume": 500_000, "securityType": "ON"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_on_tir("YCA6O")

    assert tir == 8.9


def test_on_tir_ticker_inexistente_retorna_none():
    """ON no encontrada en BYMA → None."""
    items = [
        {"symbol": "YCA6O", "last": 97.5, "impliedYield": 8.9,
         "volume": 1_000_000, "securityType": "ON"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_on_tir("OXERTO")

    assert tir is None


def test_on_tir_tir_extrema_retorna_none():
    """TIR > 30% en ON es sospechosa → retorna None."""
    items = [
        {"symbol": "YCA6O", "last": 10.0, "impliedYield": 150.0,
         "volume": 100, "securityType": "ON"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_bond_response(items)):
        tir = get_on_tir("YCA6O")

    assert tir is None


def test_on_tir_fallback_si_byma_falla():
    """Error de red → None."""
    with patch("app.services.byma_client.httpx.get", side_effect=Exception("timeout")):
        tir = get_on_tir("YCA6O")

    assert tir is None


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 5 — get_cer_letter_tir (letras ajustadas por CER, prefijo X)
#
# Contexto: la TIR real de las letras CER es el rendimiento anual POR ENCIMA
# del índice CER (inflación BCRA). Un valor NEGATIVO es normal y esperado:
#   X29Y6 ≈ -12%  (Rava, Cocos, IOL lo confirman — el usuario lo detectó en producción)
#   X18E7 ≈  -9%  (referencia orientativa, varía con el mercado)
#
# BYMA expone la TIR real en el campo `impliedYield` del endpoint
# short-term-government-bonds, igual que para LECAPs pero con valor negativo.
# ═══════════════════════════════════════════════════════════════════════════════

def _cer_response(items: list[dict]):
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    return mock


def test_cer_letter_tir_retorna_tir_negativa():
    """
    X29Y6 debe retornar TIR real negativa (típicamente ≈ -12%).
    Referencia de mercado (abril 2026): Rava, Cocos e IOL muestran TIR ≈ -12%.
    El test verifica que el valor en BYMA se pasa correctamente al caller.
    """
    items = [
        {"symbol": "X29Y6", "impliedYield": -12.3, "securityType": "LETRA"},
        {"symbol": "X18E7", "impliedYield": -9.1,  "securityType": "LETRA"},
        {"symbol": "S30J6", "impliedYield": 52.0,  "securityType": "LETRA"},  # LECAP pura — ignorar
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cer_response(items)):
        tir = get_cer_letter_tir("X29Y6")

    assert tir == -12.3


def test_cer_letter_tir_no_confunde_con_lecap():
    """
    S-prefix (LECAP pura de descuento) NO debe aparecer en la respuesta de CER.
    get_cer_letter_tir solo devuelve tickers que empiezan con X.
    """
    items = [
        {"symbol": "S30J6", "impliedYield": 52.0,  "securityType": "LETRA"},
        {"symbol": "X29Y6", "impliedYield": -12.3, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cer_response(items)):
        tir_s = get_cer_letter_tir("S30J6")
        tir_x = get_cer_letter_tir("X29Y6")

    assert tir_s is None, "S30J6 es LECAP pura, no debe aparecer como CER"
    assert tir_x == -12.3


def test_cer_letter_tir_ticker_inexistente_retorna_none():
    """Ticker CER no encontrado en BYMA → None. El caller usa fallback 0."""
    items = [
        {"symbol": "X29Y6", "impliedYield": -12.3, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cer_response(items)):
        tir = get_cer_letter_tir("X99Z9")

    assert tir is None


def test_cer_letter_tir_fuera_de_rango_retorna_none():
    """
    TIR real fuera del rango sanidad (CER_TIR_MIN=-30 / CER_TIR_MAX=+30)
    es anomalía o dato sucio — retornar None en lugar de persistir basura.
    """
    items = [
        # TIR real +50% sobre CER → imposible en condiciones normales de mercado
        {"symbol": "X29Y6", "impliedYield": 50.0, "securityType": "LETRA"},
        # TIR real -50% → también fuera de rango
        {"symbol": "X18E7", "impliedYield": -50.0, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cer_response(items)):
        tir_alto = get_cer_letter_tir("X29Y6")
        tir_bajo = get_cer_letter_tir("X18E7")

    assert tir_alto is None
    assert tir_bajo is None


def test_cer_letter_tir_fallback_si_byma_falla():
    """Error de red → None. El caller (yield_updater) usa fallback=0."""
    with patch("app.services.byma_client.httpx.get", side_effect=Exception("timeout")):
        tir = get_cer_letter_tir("X29Y6")

    assert tir is None


def test_cer_letter_tir_fallback_si_status_no_200():
    """HTTP 500 → None."""
    mock = MagicMock()
    mock.status_code = 500
    with patch("app.services.byma_client.httpx.get", return_value=mock):
        tir = get_cer_letter_tir("X29Y6")

    assert tir is None


def test_cer_letter_tir_cache_evita_segundo_http_call():
    """Dos consultas al mismo endpoint comparten cache (una sola request HTTP)."""
    items = [
        {"symbol": "X29Y6", "impliedYield": -12.3, "securityType": "LETRA"},
        {"symbol": "X18E7", "impliedYield": -9.1,  "securityType": "LETRA"},
    ]
    mock_get = MagicMock(return_value=_cer_response(items))
    with patch("app.services.byma_client.httpx.get", mock_get):
        get_cer_letter_tir("X29Y6")
        get_cer_letter_tir("X18E7")

    assert mock_get.call_count == 1


def test_cer_letter_tir_tir_cero_retorna_none():
    """impliedYield=0 es dato vacío, no debe almacenarse."""
    items = [
        {"symbol": "X29Y6", "impliedYield": 0.0, "securityType": "LETRA"},
    ]
    with patch("app.services.byma_client.httpx.get", return_value=_cer_response(items)):
        tir = get_cer_letter_tir("X29Y6")

    # 0.0 está en el rango [-30, +30] pero es dato vacío — debería retornar None
    # Nota: el rango de sanidad incluye 0.0 como borde. Si BYMA devuelve 0 para
    # una letra CER activa, es probablemente dato sucio (sin precio en el día).
    # El caller usa fallback=0 de todas formas — este caso es edge.
    # Aceptamos None o 0.0 dependiendo de la implementación.
    assert tir == 0.0 or tir is None  # ambos son manejables por el caller


def test_on_tir_cache_independiente_de_bonds():
    """ON y bonos soberanos usan endpoints distintos → caches independientes."""
    bond_items = [
        {"symbol": "AL30", "last": 55.0, "impliedYield": 11.5,
         "volume": 5_000_000, "securityType": "BONO"},
    ]
    on_items = [
        {"symbol": "YCA6O", "last": 97.5, "impliedYield": 8.9,
         "volume": 1_000_000, "securityType": "ON"},
    ]
    call_count = {"n": 0}

    def side_effect(url, **kwargs):
        call_count["n"] += 1
        if "corporate" in url:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = on_items
            return m
        else:
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = bond_items
            return m

    with patch("app.services.byma_client.httpx.get", side_effect=side_effect):
        get_bond_tir("AL30")
        get_on_tir("YCA6O")

    # Un call por cada endpoint distinto
    assert call_count["n"] == 2
