"""
Tests para byma_client.py — POST /get-market-data (nuevo contrato 2026-04-10).

Contrato real descubierto via reverse-engineering del JS de Open BYMA Data:
  - Todos los endpoints de mercado son POST /get-market-data con body JSON con panel key
  - Respuesta: {"data": [...], "content": {...}}
  - impliedYield viene null → bonds/ONs siempre retornan None hasta que BYMA lo exponga
  - Fichatecnica: POST /bnown/fichatecnica/especies/general → TEM contractual

Corre con: pytest backend/tests/test_byma_client.py -v
"""

from datetime import date
from unittest.mock import patch, MagicMock, call
import pytest

from app.services.byma_client import (
    get_lecap_tna, LECAP_TNA_FALLBACK,
    get_lecap_tea_by_ticker,
    get_cedear_price_ars,
    get_bond_tir, get_on_tir,
    get_cer_letter_tir, CER_TIR_MIN, CER_TIR_MAX,
)
import app.services.byma_client as bc


# ── Fixture: limpiar todos los caches antes/después de cada test ──────────────

@pytest.fixture(autouse=True)
def clear_cache():
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0
    bc._letras_market_cache["data"] = {}
    bc._letras_market_cache["ts"] = 0.0
    bc._cedear_cache["data"] = {}
    bc._cedear_cache["ts"] = 0.0
    bc._stock_cache["data"] = {}
    bc._stock_cache["ts"] = 0.0
    bc._sovereign_cache["data"] = {}
    bc._sovereign_cache["ts"] = 0.0
    bc._on_cache["data"] = {}
    bc._on_cache["ts"] = 0.0
    bc._cer_cache["data"] = {}
    bc._cer_cache["ts"] = 0.0
    bc._ficha_cache["data"] = {}
    bc._cedear_full_cache["data"] = {}
    bc._cedear_full_cache["ts"] = 0.0
    yield
    bc._lecap_cache["value"] = None
    bc._lecap_cache["ts"] = 0.0
    bc._letras_market_cache["data"] = {}
    bc._letras_market_cache["ts"] = 0.0
    bc._cedear_cache["data"] = {}
    bc._cedear_cache["ts"] = 0.0
    bc._stock_cache["data"] = {}
    bc._stock_cache["ts"] = 0.0
    bc._sovereign_cache["data"] = {}
    bc._sovereign_cache["ts"] = 0.0
    bc._on_cache["data"] = {}
    bc._on_cache["ts"] = 0.0
    bc._cer_cache["data"] = {}
    bc._cer_cache["ts"] = 0.0
    bc._ficha_cache["data"] = {}
    bc._cedear_full_cache["data"] = {}
    bc._cedear_full_cache["ts"] = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _market_response(items: list[dict], status: int = 200):
    """Simula respuesta JSON de POST /get-market-data."""
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = {"data": items, "content": {"page_number": 1}}
    return mock


def _ficha_response(ticker: str, emision: str, vto: str, interes: str, status: int = 200):
    """Simula respuesta JSON de POST /bnown/fichatecnica/especies/general."""
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = {
        "data": [{
            "symbol": ticker,
            "fechaEmision": f"{emision} 00:00:00.0",
            "fechaVencimiento": f"{vto} 00:00:00.0",
            "interes": interes,
        }]
    }
    return mock


def _make_post_side_effect(letras_items=None, ficha_items=None, letras_status=200):
    """
    side_effect para httpx.post que distingue /get-market-data de /fichatecnica.
    ficha_items: dict {ticker_upper: (emision, vto, interes)} o None para 404.
    """
    def side_effect(url, json=None, **kwargs):
        if "fichatecnica" in url:
            sym = (json or {}).get("symbol", "UNKNOWN").upper()
            if ficha_items and sym in ficha_items:
                em, vto, interes = ficha_items[sym]
                return _ficha_response(sym, em, vto, interes)
            mock = MagicMock()
            mock.status_code = 404
            mock.json.return_value = {"data": []}
            return mock
        else:
            # /get-market-data
            return _market_response(letras_items or [], letras_status)
    return side_effect


# ═══════════════════════════════════════════════════════════════════════════════
# LECAP — get_lecap_tna
# ═══════════════════════════════════════════════════════════════════════════════

# S31G6: emision 2025-12-31, vto 2026-06-30 → 181 días total, TEM 2.60%
# VNV = 100 * 1.026^(181/30.4375) ≈ 100 * 1.026^5.95 ≈ 116.5
# Con vwap=96.2 y ~81 días restantes (al 2026-04-10): TEA ≈ 27%
# Precios realistas para 2026-04-10: letras cercanas al VNV
SAMPLE_LETRAS_ITEMS = [
    {"symbol": "S31G6", "vwap": 112.0, "tradeVolume": 1_000_000},  # VNV≈116.5 → TEA razonable
    {"symbol": "S15Y6", "vwap": 105.2, "tradeVolume": 500_000},    # cerca del par
    {"symbol": "X29Y6", "vwap": 114.3, "tradeVolume": 200_000},    # CER — ignorado en LECAP
]
SAMPLE_FICHA = {
    "S31G6": ("2025-12-31", "2026-06-30", "Tasa efectiva mensual: 2,60 %"),
    "S15Y6": ("2026-03-16", "2026-05-15", "Tasa efectiva mensual: 2,60 %"),
}


def test_lecap_tna_calcula_tea_desde_byma():
    """Con LECAPs vigentes devuelve TEA calculada desde precio + TEM contractual."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect(SAMPLE_LETRAS_ITEMS, SAMPLE_FICHA)):
        tna = get_lecap_tna()

    # TEA debe ser un float positivo y razonable para el mercado argentino actual
    assert isinstance(tna, float)
    assert 5.0 <= tna <= 100.0


def test_lecap_tna_excluye_cer():
    """Tickers X-prefix (CER) no se incluyen en el promedio de TEA nominal."""
    # Solo hay CER, sin S-prefix → fallback ArgentinaDatos
    cer_only = [{"symbol": "X29Y6", "vwap": 114.3, "tradeVolume": 500_000}]
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect(cer_only, {})):
        with patch("app.services.byma_client._lecap_tna_argentinadatos_fallback",
                   return_value=31.5) as mock_fb:
            tna = get_lecap_tna()

    mock_fb.assert_called_once()
    assert tna == 31.5


def test_lecap_tna_fallback_si_byma_falla():
    """Si BYMA devuelve error → llama a ArgentinaDatos fallback."""
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        with patch("app.services.byma_client._lecap_tna_argentinadatos_fallback",
                   return_value=LECAP_TNA_FALLBACK) as mock_fb:
            tna = get_lecap_tna()

    mock_fb.assert_called_once()
    assert tna == LECAP_TNA_FALLBACK


def test_lecap_tna_fallback_si_respuesta_vacia():
    """Si BYMA devuelve lista vacía → fallback."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect([], {})):
        with patch("app.services.byma_client._lecap_tna_argentinadatos_fallback",
                   return_value=LECAP_TNA_FALLBACK) as mock_fb:
            tna = get_lecap_tna()

    mock_fb.assert_called_once()
    assert tna == LECAP_TNA_FALLBACK


def test_lecap_tna_fallback_si_status_no_200():
    """HTTP 400 → fallback."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect([], letras_status=400)):
        with patch("app.services.byma_client._lecap_tna_argentinadatos_fallback",
                   return_value=32.0) as mock_fb:
            tna = get_lecap_tna()

    mock_fb.assert_called_once()
    assert tna == 32.0


def test_lecap_tna_cache_evita_segundo_http_call():
    """Llamar dos veces seguidas con cache válido solo hace un HTTP call."""
    mock_post = MagicMock(
        side_effect=_make_post_side_effect(SAMPLE_LETRAS_ITEMS, SAMPLE_FICHA)
    )
    with patch("app.services.byma_client.httpx.post", mock_post):
        result1 = get_lecap_tna()
        calls_after_first = mock_post.call_count
        result2 = get_lecap_tna()

    # Segundo call debe devolver el mismo valor sin calls adicionales
    assert result1 == result2
    assert mock_post.call_count == calls_after_first


# ═══════════════════════════════════════════════════════════════════════════════
# get_lecap_tea_by_ticker
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_lecap_tea_by_ticker_retorna_tea():
    """get_lecap_tea_by_ticker devuelve TEA calculada para un ticker válido."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect(SAMPLE_LETRAS_ITEMS, SAMPLE_FICHA)):
        tea = get_lecap_tea_by_ticker("S31G6")

    assert tea is not None
    assert isinstance(tea, float)
    assert 5.0 <= tea <= 100.0


def test_get_lecap_tea_by_ticker_no_encontrado_retorna_none():
    """Ticker no en BYMA → None."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect(SAMPLE_LETRAS_ITEMS, SAMPLE_FICHA)):
        tea = get_lecap_tea_by_ticker("SXXXXXX")

    assert tea is None


def test_get_lecap_tea_by_ticker_sin_ficha_retorna_none():
    """Si fichatecnica falla para el ticker → None."""
    with patch("app.services.byma_client.httpx.post",
               side_effect=_make_post_side_effect(SAMPLE_LETRAS_ITEMS, {})):
        tea = get_lecap_tea_by_ticker("S31G6")

    assert tea is None


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 2 — get_cedear_price_ars
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_CEDEARS = [
    {"symbol": "AAPL", "vwap": 14500.0, "tradeVolume": 200_000},
    {"symbol": "MSFT", "vwap": 12300.0, "tradeVolume": 150_000},
]


def test_cedear_price_ars_retorna_precio():
    """Devuelve vwap del CEDEAR cuando el ticker está en la respuesta."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_CEDEARS)):
        price = get_cedear_price_ars("AAPL")

    assert price == 14500.0


def test_cedear_price_ars_ticker_inexistente_retorna_none():
    """Si el ticker no está en la respuesta retorna None."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_CEDEARS)):
        price = get_cedear_price_ars("NVDA")

    assert price is None


def test_cedear_price_ars_fallback_si_byma_falla():
    """Si BYMA falla (exception) retorna None."""
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_fallback_si_status_no_200():
    """HTTP 500 → retorna None."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response([], status=500)):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_ignora_precio_cero():
    """vwap=0 no es un dato válido, retorna None para ese ticker."""
    items = [{"symbol": "AAPL", "vwap": 0.0, "tradeVolume": 0}]
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(items)):
        price = get_cedear_price_ars("AAPL")

    assert price is None


def test_cedear_price_ars_cache_evita_segundo_http_call():
    """Dos llamadas distintas al mismo ticker usan cache (una sola request)."""
    mock_post = MagicMock(return_value=_market_response(SAMPLE_CEDEARS))
    with patch("app.services.byma_client.httpx.post", mock_post):
        get_cedear_price_ars("AAPL")
        get_cedear_price_ars("MSFT")

    assert mock_post.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 3 — get_bond_tir (bonos soberanos)
#
# Nota: impliedYield viene null en el nuevo endpoint POST /get-market-data.
# get_bond_tir siempre retorna None hasta que BYMA exponga el campo.
# El caller (yield_updater) usa la tabla _BOND_YTM como fallback.
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_BONDS = [
    {"symbol": "AL30", "vwap": 55.0, "impliedYield": None, "tradeVolume": 5_000_000},
    {"symbol": "GD30", "vwap": 52.0, "impliedYield": None, "tradeVolume": 3_000_000},
]


def test_bond_tir_retorna_none_porque_implied_yield_null():
    """
    BYMA btnTitPublicos devuelve impliedYield=null → get_bond_tir retorna None.
    El caller usa _BOND_YTM como fallback.
    """
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_BONDS)):
        tir = get_bond_tir("AL30")

    assert tir is None


def test_bond_tir_ticker_inexistente_retorna_none():
    """Bono no encontrado → None."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_BONDS)):
        tir = get_bond_tir("BONOD")

    assert tir is None


def test_bond_tir_fallback_si_byma_falla():
    """Error de red → None."""
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        tir = get_bond_tir("AL30")

    assert tir is None


def test_bond_tir_cache_evita_segundo_http_call():
    """Dos tickers del mismo panel comparten cache (una sola request HTTP)."""
    mock_post = MagicMock(return_value=_market_response(SAMPLE_BONDS))
    with patch("app.services.byma_client.httpx.post", mock_post):
        get_bond_tir("AL30")
        get_bond_tir("GD30")

    assert mock_post.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 4 — get_on_tir (obligaciones negociables)
#
# Nota: igual que bonos — impliedYield null → siempre None.
# ═══════════════════════════════════════════════════════════════════════════════

SAMPLE_ONS = [
    {"symbol": "YCA6O", "vwap": 97.5, "impliedYield": None, "tradeVolume": 1_000_000},
    {"symbol": "IRCFO", "vwap": 98.0, "impliedYield": None, "tradeVolume": 500_000},
]


def test_on_tir_retorna_none_porque_implied_yield_null():
    """BYMA btnObligNegociables: impliedYield=null → None."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_ONS)):
        tir = get_on_tir("YCA6O")

    assert tir is None


def test_on_tir_ticker_inexistente_retorna_none():
    """ON no encontrada → None."""
    with patch("app.services.byma_client.httpx.post",
               return_value=_market_response(SAMPLE_ONS)):
        tir = get_on_tir("OXERTO")

    assert tir is None


def test_on_tir_fallback_si_byma_falla():
    """Error de red → None."""
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        tir = get_on_tir("YCA6O")

    assert tir is None


def test_on_tir_cache_independiente_de_bonds():
    """
    ON y bonos soberanos usan paneles distintos.
    Cada uno hace su propio POST (caches independientes).
    """
    call_count = {"n": 0}

    def side_effect(url, json=None, **kwargs):
        call_count["n"] += 1
        panel_body = json or {}
        if panel_body.get("btnObligNegociables"):
            return _market_response(SAMPLE_ONS)
        elif panel_body.get("btnTitPublicos"):
            return _market_response(SAMPLE_BONDS)
        return _market_response([])

    with patch("app.services.byma_client.httpx.post", side_effect=side_effect):
        get_bond_tir("AL30")
        get_on_tir("YCA6O")

    # Un call por cada panel distinto (caches separados)
    assert call_count["n"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# BYMA 5 — get_cer_letter_tir (letras ajustadas por CER, prefijo X)
#
# Contexto: la TIR real de las letras CER es el rendimiento anual POR ENCIMA
# del índice CER (inflación BCRA). Un valor NEGATIVO es normal y esperado:
#   X29Y6 ≈ -12%  (Rava, Cocos, IOL lo confirman — el usuario lo detectó en prod)
#
# Cálculo: precio BYMA + UVA (ArgentinaDatos) como proxy del CER.
# get_cer_letter_tir delega en _calc_cer_tir_for_all() — para los tests
# mockeamos esa función interna para aislar el comportamiento del caller.
# ═══════════════════════════════════════════════════════════════════════════════

def test_cer_letter_tir_retorna_tir_negativa():
    """
    X29Y6 debe retornar TIR real negativa (típicamente ≈ -12%).
    Referencia de mercado (abril 2026): Rava, Cocos e IOL muestran TIR ≈ -12%.
    """
    with patch("app.services.byma_client._calc_cer_tir_for_all",
               return_value={"X29Y6": -11.59, "X18E7": -9.1}):
        tir = get_cer_letter_tir("X29Y6")

    assert tir == -11.59


def test_cer_letter_tir_no_confunde_con_lecap():
    """
    S-prefix (LECAP pura) NO debe aparecer en el resultado de CER.
    _calc_cer_tir_for_all solo incluye X-prefix.
    """
    # _calc_cer_tir_for_all ya filtra por X-prefix internamente
    with patch("app.services.byma_client._calc_cer_tir_for_all",
               return_value={"X29Y6": -11.59}):
        tir_s = get_cer_letter_tir("S30J6")
        tir_x = get_cer_letter_tir("X29Y6")

    assert tir_s is None, "S30J6 es LECAP pura, no debe aparecer como CER"
    assert tir_x == -11.59


def test_cer_letter_tir_ticker_inexistente_retorna_none():
    """Ticker CER no encontrado → None."""
    with patch("app.services.byma_client._calc_cer_tir_for_all",
               return_value={"X29Y6": -11.59}):
        tir = get_cer_letter_tir("X99Z9")

    assert tir is None


def test_cer_letter_tir_fallback_si_byma_falla():
    """Error en _calc_cer_tir_for_all → None."""
    with patch("app.services.byma_client._calc_cer_tir_for_all",
               side_effect=Exception("timeout")):
        tir = get_cer_letter_tir("X29Y6")

    assert tir is None


def test_cer_letter_tir_cache_evita_segundo_http_call():
    """Dos consultas distintas usan el mismo cache poblado en el primer call."""
    mock_calc = MagicMock(return_value={"X29Y6": -11.59, "X18E7": -9.1})
    with patch("app.services.byma_client._calc_cer_tir_for_all", mock_calc):
        get_cer_letter_tir("X29Y6")
        get_cer_letter_tir("X18E7")

    assert mock_calc.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests para helpers internos
# ═══════════════════════════════════════════════════════════════════════════════

def test_parse_tem_from_interes_coma_decimal():
    """'Tasa efectiva mensual: 2,60 %' → 0.026"""
    from app.services.byma_client import _parse_tem_from_interes
    tem = _parse_tem_from_interes("Tasa efectiva mensual: 2,60 %")
    assert tem is not None
    assert abs(tem - 0.026) < 0.0001


def test_parse_tem_from_interes_punto_decimal():
    """'tasa efectiva mensual del 2.5%' → 0.025"""
    from app.services.byma_client import _parse_tem_from_interes
    tem = _parse_tem_from_interes("tasa efectiva mensual del 2.5%")
    assert tem is not None
    assert abs(tem - 0.025) < 0.0001


def test_parse_tem_from_interes_sin_patron_retorna_none():
    """Cadena sin porcentaje → None."""
    from app.services.byma_client import _parse_tem_from_interes
    assert _parse_tem_from_interes("") is None
    assert _parse_tem_from_interes("Sin tasa") is None


def test_parse_date_formato_byma():
    """'2026-05-15 00:00:00.0' → date(2026, 5, 15)"""
    from app.services.byma_client import _parse_date
    d = _parse_date("2026-05-15 00:00:00.0")
    assert d == date(2026, 5, 15)


def test_parse_date_formato_iso():
    """'2026-03-16' → date(2026, 3, 16)"""
    from app.services.byma_client import _parse_date
    d = _parse_date("2026-03-16")
    assert d == date(2026, 3, 16)


def test_parse_date_invalido_retorna_none():
    """Cadena inválida → None."""
    from app.services.byma_client import _parse_date
    assert _parse_date("") is None
    assert _parse_date(None) is None


def test_calc_lecap_tea_sanity():
    """
    S31G6: emision=2025-12-31, vto=2026-06-30, TEM=2.6%, vwap=110.0
    VNV = 100 * 1.026^(181/30.4) ≈ 116.5
    Con vwap=110 y 81 días restantes TEA ≈ 30-35%.
    """
    from app.services.byma_client import _calc_lecap_tea_from_price
    emision = date(2025, 12, 31)
    vto = date(2026, 6, 30)
    today = date(2026, 4, 10)
    tea = _calc_lecap_tea_from_price(110.0, 0.026, emision, vto, today)
    assert tea is not None
    assert 15.0 <= tea <= 80.0  # rango razonable mercado argentino


def test_calc_lecap_tea_vwap_cero_retorna_none():
    """vwap=0 → None."""
    from app.services.byma_client import _calc_lecap_tea_from_price
    result = _calc_lecap_tea_from_price(0.0, 0.026, date(2025, 12, 31), date(2026, 6, 30), date(2026, 4, 10))
    assert result is None


def test_calc_lecap_tea_vencida_retorna_none():
    """dias_restantes <= 0 → None."""
    from app.services.byma_client import _calc_lecap_tea_from_price
    result = _calc_lecap_tea_from_price(98.0, 0.026, date(2025, 1, 1), date(2026, 1, 1), date(2026, 4, 10))
    assert result is None


# ── get_stock_price_ars (BYMA leading-equity) ─────────────────────────────────

SAMPLE_LIDERES_ITEMS = [
    {"symbol": "GGAL", "vwap": 1820.50, "previousSettlementPrice": 1800.0},
    {"symbol": "YPF",  "vwap": 2340.00, "previousSettlementPrice": 2300.0},
    {"symbol": "PAMP", "vwap": 3150.75, "previousSettlementPrice": 3100.0},
]


def test_stock_precio_blue_chip_correcto():
    """GGAL en panel lideres → retorna vwap correcto."""
    from app.services.byma_client import get_stock_price_ars
    resp = _market_response(SAMPLE_LIDERES_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        price = get_stock_price_ars("GGAL")
    assert price == pytest.approx(1820.50, abs=0.01)


def test_stock_ticker_no_blue_chip_retorna_none():
    """MIRG no está en panel lideres → None."""
    from app.services.byma_client import get_stock_price_ars
    resp = _market_response(SAMPLE_LIDERES_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        price = get_stock_price_ars("MIRG")
    assert price is None


def test_stock_cache_evita_segundo_call():
    """Segunda llamada al mismo ticker usa cache — solo 1 HTTP call."""
    from app.services.byma_client import get_stock_price_ars
    resp = _market_response(SAMPLE_LIDERES_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp) as mock_post:
        get_stock_price_ars("GGAL")
        get_stock_price_ars("YPF")
        assert mock_post.call_count == 1


def test_stock_byma_falla_retorna_none():
    """BYMA lanza excepción → None."""
    from app.services.byma_client import get_stock_price_ars
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        price = get_stock_price_ars("GGAL")
    assert price is None


def test_stock_precio_cero_retorna_none():
    """Item con vwap=0 y previousSettlementPrice=0 → no se cachea, retorna None."""
    from app.services.byma_client import get_stock_price_ars
    items = [{"symbol": "GGAL", "vwap": 0, "previousSettlementPrice": 0}]
    resp = _market_response(items)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        price = get_stock_price_ars("GGAL")
    assert price is None


# ── get_cedear_market_data ─────────────────────────────────────────────────────

SAMPLE_CEDEAR_FULL_ITEMS = [
    {
        "symbol": "AAPL",
        "vwap": 15250.0,
        "previousSettlementPrice": 0,
        "previousClosingPrice": 14800.0,
        "tradingHighPrice": 15500.0,
        "tradingLowPrice": 15100.0,
    },
    {
        "symbol": "QQQ",
        "vwap": 0,
        "previousSettlementPrice": 42000.0,
        "previousClosingPrice": 41500.0,
        "tradingHighPrice": 42500.0,
        "tradingLowPrice": 41000.0,
    },
    {
        "symbol": "MSFT",
        "vwap": 18000.0,
        "previousSettlementPrice": 0,
        "previousClosingPrice": 0,  # sin prev_close
        "tradingHighPrice": 18500.0,
        "tradingLowPrice": 17800.0,
    },
]


def test_cedear_market_data_retorna_dict_completo():
    """AAPL con todos los campos → dict con price, prev_close, high, low, variation."""
    from app.services.byma_client import get_cedear_market_data
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        data = get_cedear_market_data("AAPL")
    assert data is not None
    assert data["price_ars"] == 15250.0
    assert data["prev_close_ars"] == 14800.0
    assert data["high_ars"] == 15500.0
    assert data["low_ars"] == 15100.0
    # variation_pct = (15250 - 14800) / 14800 * 100 ≈ 3.04%
    assert data["variation_pct"] is not None
    assert abs(data["variation_pct"] - 3.04) < 0.1


def test_cedear_market_data_usa_settlement_si_vwap_cero():
    """QQQ con vwap=0 → usa previousSettlementPrice como price_ars."""
    from app.services.byma_client import get_cedear_market_data
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        data = get_cedear_market_data("QQQ")
    assert data is not None
    assert data["price_ars"] == 42000.0


def test_cedear_market_data_prev_close_none_si_cero():
    """MSFT con previousClosingPrice=0 → prev_close_ars=None, variation_pct=None."""
    from app.services.byma_client import get_cedear_market_data
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        data = get_cedear_market_data("MSFT")
    assert data is not None
    assert data["prev_close_ars"] is None
    assert data["variation_pct"] is None


def test_cedear_market_data_ticker_inexistente_retorna_none():
    """Ticker que no está en la respuesta → None."""
    from app.services.byma_client import get_cedear_market_data
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp):
        data = get_cedear_market_data("TSLA")
    assert data is None


def test_cedear_market_data_cache_evita_segundo_call():
    """Dos calls con distintos tickers → 1 solo HTTP call (cache compartido)."""
    from app.services.byma_client import get_cedear_market_data
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp) as mock_post:
        get_cedear_market_data("AAPL")
        get_cedear_market_data("QQQ")
    assert mock_post.call_count == 1


def test_cedear_market_data_byma_falla_retorna_none():
    """BYMA lanza excepción → None."""
    from app.services.byma_client import get_cedear_market_data
    with patch("app.services.byma_client.httpx.post", side_effect=Exception("timeout")):
        data = get_cedear_market_data("AAPL")
    assert data is None


def test_cedear_market_data_sincroniza_cedear_cache():
    """Después de get_cedear_market_data, get_cedear_price_ars usa cache sin HTTP."""
    from app.services.byma_client import get_cedear_market_data, get_cedear_price_ars
    resp = _market_response(SAMPLE_CEDEAR_FULL_ITEMS)
    with patch("app.services.byma_client.httpx.post", return_value=resp) as mock_post:
        get_cedear_market_data("AAPL")   # carga full cache y price cache
        price = get_cedear_price_ars("AAPL")  # debe usar cache
    assert mock_post.call_count == 1
    assert price == 15250.0
