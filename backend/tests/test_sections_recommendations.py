"""
Tests para get_sections_recommendations y las mejoras al UNIVERSE v2.

Corre con: pytest backend/tests/test_sections_recommendations.py -v
"""
from unittest.mock import patch

import pytest

from app.services.expert_committee import (
    UNIVERSE,
    get_sections_recommendations,
    _RECOMMENDED_FOR,
    AGENT_WEIGHTS,
    RISK_PROFILE_FILTERS,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

_MOCK_MARKET = {
    "mep": 1431.0, "blue": 1415.0, "oficial": 1354.0,
    "spread_pct": 5.7, "lecap_tna": 68.0,
    "inflation_monthly": 2.5, "tasa_real_mensual": 3.2,
    "riesgo_pais": 700, "merval_trend": 0.0,
    "sources": ["mock"],
}


def _sections(capital=500_000, freedom_pct=30, tickers=None):
    with patch("app.services.expert_committee._fetch_market", return_value=_MOCK_MARKET):
        return get_sections_recommendations(
            capital_ars=capital,
            freedom_pct=freedom_pct,
            monthly_savings_usd=1000,
            current_tickers=tickers or [],
        )


# ── UNIVERSE v2 ────────────────────────────────────────────────────────────────

class TestUniverseV2:
    def test_universe_tiene_18_o_mas_instrumentos(self):
        assert len(UNIVERSE) >= 18

    def test_todos_tienen_liquidity_score(self):
        for inst in UNIVERSE:
            assert 0 < inst.liquidity_score <= 1.0, f"{inst.ticker} liquidity_score inválido"

    def test_todos_tienen_logo_url(self):
        for inst in UNIVERSE:
            assert inst.logo_url, f"{inst.ticker} sin logo_url"

    def test_meli_es_el_cedear_mas_liquido(self):
        cedears = [i for i in UNIVERSE if i.asset_type == "CEDEAR"]
        meli = next((i for i in cedears if i.ticker == "MELI"), None)
        assert meli is not None, "MELI no está en UNIVERSE"
        max_liq = max(i.liquidity_score for i in cedears)
        assert meli.liquidity_score == max_liq, "MELI debe ser el CEDEAR más líquido"

    def test_al30_es_el_bond_mas_liquido(self):
        bonds = [i for i in UNIVERSE if i.asset_type == "BOND"]
        al30 = next((i for i in bonds if i.ticker == "AL30"), None)
        assert al30 is not None
        max_liq = max(i.liquidity_score for i in bonds)
        assert al30.liquidity_score == max_liq

    def test_yca6o_es_bajo_riesgo(self):
        yca = next(i for i in UNIVERSE if i.ticker == "YCA6O")
        assert yca.risk_level == "bajo"

    def test_nuevos_instrumentos_presentes(self):
        tickers = {i.ticker for i in UNIVERSE}
        nuevos = ["MELI", "YPFD", "GLOB", "GD35", "YMCJO", "TLCMO", "S29J6"]
        for t in nuevos:
            assert t in tickers, f"{t} no está en UNIVERSE"

    def test_jobs_validos(self):
        for inst in UNIVERSE:
            assert inst.job in ("renta", "capital", "ambos"), f"{inst.ticker} job inválido: {inst.job}"


# ── get_sections_recommendations ──────────────────────────────────────────────

class TestSectionsStructure:
    def test_retorna_renta_y_capital(self):
        result = _sections()
        assert "renta" in result
        assert "capital" in result
        assert "context_summary" in result
        assert "generated_at" in result

    def test_6_instrumentos_por_seccion(self):
        result = _sections()
        assert len(result["renta"]) == 6, f"Esperaba 6 renta, got {len(result['renta'])}"
        assert len(result["capital"]) == 6, f"Esperaba 6 capital, got {len(result['capital'])}"

    def test_campos_obligatorios_en_cada_rec(self):
        result = _sections()
        campos = {"ticker", "name", "asset_type", "job", "recommended_for",
                  "logo_url", "annual_yield_pct", "risk_level", "currency",
                  "amount_ars", "amount_usd", "monthly_return_usd", "score"}
        for sec in ("renta", "capital"):
            for rec in result[sec]:
                for campo in campos:
                    assert campo in rec, f"{rec['ticker']} falta campo '{campo}'"

    def test_recommended_for_es_lista_no_vacia(self):
        result = _sections()
        for sec in ("renta", "capital"):
            for rec in result[sec]:
                assert isinstance(rec["recommended_for"], list), f"{rec['ticker']} recommended_for no es lista"
                assert len(rec["recommended_for"]) > 0, f"{rec['ticker']} recommended_for vacío"
                for p in rec["recommended_for"]:
                    assert p in ("conservador", "moderado", "agresivo"), f"{rec['ticker']} perfil inválido: {p}"

    def test_logo_url_en_cada_rec(self):
        result = _sections()
        for sec in ("renta", "capital"):
            for rec in result[sec]:
                assert isinstance(rec["logo_url"], str), f"{rec['ticker']} logo_url no es str"

    def test_renta_section_solo_tiene_job_renta_o_ambos(self):
        result = _sections()
        for rec in result["renta"]:
            assert rec["job"] in ("renta", "ambos"), f"{rec['ticker']} job={rec['job']} en sección renta"

    def test_capital_section_solo_tiene_job_capital_o_ambos(self):
        result = _sections()
        for rec in result["capital"]:
            assert rec["job"] in ("capital", "ambos"), f"{rec['ticker']} job={rec['job']} en sección capital"

    def test_no_duplicados_dentro_de_seccion(self):
        result = _sections()
        for sec in ("renta", "capital"):
            tickers = [r["ticker"] for r in result[sec]]
            assert len(tickers) == len(set(tickers)), f"Duplicados en sección {sec}: {tickers}"

    def test_ordenados_por_score_descendente(self):
        result = _sections()
        for sec in ("renta", "capital"):
            scores = [r["score"] for r in result[sec]]
            assert scores == sorted(scores, reverse=True), f"Sección {sec} no está ordenada por score"

    def test_scores_positivos(self):
        result = _sections()
        for sec in ("renta", "capital"):
            for rec in result[sec]:
                assert rec["score"] > 0, f"{rec['ticker']} score <= 0"


# ── Comportamiento del scoring ────────────────────────────────────────────────

class TestSectionsScoring:
    def test_lecaps_aparecen_en_renta(self):
        result = _sections()
        renta_tickers = {r["ticker"] for r in result["renta"]}
        letras = {i.ticker for i in UNIVERSE if i.asset_type == "LETRA"}
        assert renta_tickers & letras, "Ninguna LECAP en sección renta"

    def test_cedears_aparecen_en_capital(self):
        result = _sections()
        capital_tickers = {r["ticker"] for r in result["capital"]}
        cedears = {i.ticker for i in UNIVERSE if i.asset_type == "CEDEAR"}
        assert capital_tickers & cedears, "Ningún CEDEAR en sección capital"

    def test_capital_insuficiente_penaliza(self):
        # Con $5k ARS, los instrumentos de $50k min deben tener menor presencia
        result_low  = _sections(capital=5_000)
        result_high = _sections(capital=500_000)
        # Los scores no deben ser idénticos (capital bajo cambia el scoring)
        scores_low  = {r["ticker"]: r["score"] for r in result_low["renta"] + result_low["capital"]}
        scores_high = {r["ticker"]: r["score"] for r in result_high["renta"] + result_high["capital"]}
        # Al menos algún instrumento tiene score diferente
        shared = set(scores_low) & set(scores_high)
        diffs = [abs(scores_low[t] - scores_high[t]) for t in shared]
        assert any(d > 0 for d in diffs), "Capital no afecta el scoring"

    def test_ycao6_apto_conservador_y_moderado(self):
        result = _sections()
        for sec in ("renta", "capital"):
            for rec in result[sec]:
                if rec["ticker"] == "YCA6O":
                    assert "conservador" in rec["recommended_for"], "YCA6O debe ser apto para conservador"
                    assert "moderado" in rec["recommended_for"], "YCA6O debe ser apto para moderado"
                    assert "agresivo" not in rec["recommended_for"], "YCA6O no debe ser agresivo"

    def test_context_summary_no_vacio(self):
        result = _sections()
        assert result["context_summary"], "context_summary vacío"

    def test_market_snapshot_incluido(self):
        result = _sections()
        assert "market_snapshot" in result
        snap = result["market_snapshot"]
        assert "mep" in snap
        assert "riesgo_pais" in snap
        assert "sources" in snap


# ── AGENT_WEIGHTS y RISK_PROFILE_FILTERS ─────────────────────────────────────

class TestModuleConstants:
    def test_agent_weights_para_3_perfiles(self):
        for profile in ("conservador", "moderado", "agresivo"):
            assert profile in AGENT_WEIGHTS
            weights = AGENT_WEIGHTS[profile]
            assert abs(sum(weights.values()) - 1.0) < 0.01, f"{profile} weights no suman 1"

    def test_risk_profile_filters_completos(self):
        for profile in ("conservador", "moderado", "agresivo"):
            assert profile in RISK_PROFILE_FILTERS
            f = RISK_PROFILE_FILTERS[profile]
            assert "bajo" in f and "medio" in f and "alto" in f

    def test_conservador_filtra_alto(self):
        assert RISK_PROFILE_FILTERS["conservador"]["alto"] == 0.0

    def test_agresivo_boost_alto(self):
        assert RISK_PROFILE_FILTERS["agresivo"]["alto"] > 1.0

    def test_recommended_for_map(self):
        assert _RECOMMENDED_FOR["bajo"] == ["conservador", "moderado"]
        assert _RECOMMENDED_FOR["medio"] == ["moderado", "agresivo"]
        assert _RECOMMENDED_FOR["alto"] == ["agresivo"]
