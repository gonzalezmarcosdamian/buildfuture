"""
Tests para recommendation_engine.py — filtrado por perfil, cálculos, ordenamiento.

Corre con: pytest backend/tests/test_recommendation_engine.py -v
"""
import pytest

from app.services.recommendation_engine import (
    get_recommendations,
    INSTRUMENT_UNIVERSE,
    InstrumentRecommendation,
)


class TestGetRecommendations:
    def test_returns_list(self):
        result = get_recommendations(capital_ars=500_000, fx_rate=1430, current_tickers=[])
        assert isinstance(result, list)

    def test_conservador_no_incluye_alto_riesgo(self):
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=[], risk_profile="conservador"
        )
        for rec in result:
            assert rec["risk_level"] != "alto", f"{rec['ticker']} es alto riesgo pero se incluyó para conservador"

    def test_moderado_no_incluye_alto_riesgo(self):
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=[], risk_profile="moderado"
        )
        for rec in result:
            assert rec["risk_level"] != "alto"

    def test_agresivo_puede_incluir_alto_riesgo(self):
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=[], risk_profile="agresivo"
        )
        high_risk = [r for r in result if r["risk_level"] == "alto"]
        assert len(high_risk) > 0, "El perfil agresivo debería incluir al menos un instrumento de alto riesgo"

    def test_perfil_invalido_no_lanza_excepcion(self):
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=[], risk_profile="unknown"
        )
        assert isinstance(result, list)

    def test_amount_ars_es_capital_por_allocation_pct(self):
        capital = 1_000_000
        result = get_recommendations(capital_ars=capital, fx_rate=1430, current_tickers=[])
        for rec in result:
            expected = round(capital * rec["allocation_pct"])
            assert rec["amount_ars"] == expected, f"{rec['ticker']} amount_ars incorrecto"

    def test_amount_usd_es_ars_sobre_fx(self):
        fx = 1430
        result = get_recommendations(capital_ars=500_000, fx_rate=fx, current_tickers=[])
        for rec in result:
            expected_usd = round(rec["amount_ars"] / fx, 2)
            assert abs(rec["amount_usd"] - expected_usd) < 0.01, f"{rec['ticker']} amount_usd incorrecto"

    def test_monthly_return_calculado_correctamente(self):
        result = get_recommendations(capital_ars=500_000, fx_rate=1430, current_tickers=[])
        for rec in result:
            expected = round((rec["amount_usd"] * rec["annual_yield_pct"]) / 12, 2)
            assert abs(rec["monthly_return_usd"] - expected) < 0.01

    def test_ya_en_portafolio_marcado(self):
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=["QQQ", "AL30"]
        )
        for rec in result:
            if rec["ticker"] in ("QQQ", "AL30"):
                assert rec["already_in_portfolio"] is True
            else:
                assert rec["already_in_portfolio"] is False

    def test_instrumentos_sin_tener_antes_que_los_que_ya_tiene(self):
        """Los instrumentos que el usuario NO tiene deben aparecer antes en la lista."""
        result = get_recommendations(
            capital_ars=500_000, fx_rate=1430, current_tickers=["S15G5"]
        )
        positions = [r["already_in_portfolio"] for r in result]
        # Una vez que aparece True, no debería haber False después
        seen_true = False
        for p in positions:
            if p:
                seen_true = True
            if seen_true and not p:
                pytest.fail("Un instrumento sin tener aparece después de uno que ya se tiene")

    def test_campos_obligatorios_presentes(self):
        result = get_recommendations(capital_ars=500_000, fx_rate=1430, current_tickers=[])
        campos = {
            "ticker", "name", "asset_type", "market", "allocation_pct",
            "amount_ars", "amount_usd", "annual_yield_pct", "monthly_return_usd",
            "rationale", "risk_level", "currency", "already_in_portfolio"
        }
        for rec in result:
            for campo in campos:
                assert campo in rec, f"Campo '{campo}' faltante en recomendación de {rec.get('ticker')}"


class TestInstrumentUniverse:
    def test_universe_no_vacio(self):
        assert len(INSTRUMENT_UNIVERSE) > 0

    def test_todos_tienen_ticker(self):
        for inst in INSTRUMENT_UNIVERSE:
            assert inst.ticker, "Instrumento sin ticker"

    def test_allocation_pcts_positivos(self):
        for inst in INSTRUMENT_UNIVERSE:
            assert inst.allocation_pct > 0, f"{inst.ticker} allocation_pct <= 0"

    def test_annual_yield_pcts_positivos(self):
        for inst in INSTRUMENT_UNIVERSE:
            assert inst.annual_yield_pct > 0, f"{inst.ticker} annual_yield_pct <= 0"

    def test_risk_levels_validos(self):
        for inst in INSTRUMENT_UNIVERSE:
            assert inst.risk_level in ("bajo", "medio", "alto"), f"{inst.ticker} risk_level inválido"
