"""
Comité de expertos en inversiones argentinas.

Arquitectura multi-agente: cada experto analiza el contexto desde su especialidad
y vota con convicción. El orquestador agrega los votos y genera recomendaciones
con rationale compuesto por las voces de los agentes que acordaron.

Agentes:
  AgenteCarryARS      — especialista en tasa/LECAPs/carry en pesos
  AgenteDolarizacion  — especialista en cobertura cambiaria (CEDEARs, bonos USD)
  AgenteRentaFija     — especialista en bonos soberanos y ONs
  AgenteDiversificacion — analiza concentración del portafolio actual
  AgenteMacro         — contexto macro transversal, ajusta todos los scores
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger("buildfuture.experts")

_market_cache: dict = {}
MARKET_CACHE_TTL = 3600


# ── Instrumento con datos enriquecidos ────────────────────────────────────────

@dataclass
class Instrument:
    ticker: str
    name: str
    asset_type: str        # LETRA | CEDEAR | BOND | ON | FCI
    currency: str          # ARS | USD
    base_yield_pct: float
    risk_level: str        # bajo | medio | alto
    min_capital_ars: float
    mercado: str = "bCBA"
    # Factores de afinidad por agente (0-1)
    affinity_carry: float = 0.5
    affinity_dolar: float = 0.5
    affinity_renta_fija: float = 0.5
    tags: list[str] = field(default_factory=list)
    # Propósito: renta (flujo periódico) | capital (apreciación) | ambos
    job: str = "renta"
    # Liquidez relativa en BYMA (0-1). Se actualiza con volumen live cuando disponible.
    liquidity_score: float = 1.0
    # URL del logo para el frontend — Clearbit para subyacentes US, flagcdn para soberanos
    logo_url: str = ""


# ── Logo map — resuelto por ticker ────────────────────────────────────────────

_LOGO_MAP: dict[str, str] = {
    # CEDEARs — subyacente US/latam
    "MELI":   "https://logo.clearbit.com/mercadolibre.com",
    "SPY":    "https://logo.clearbit.com/ssga.com",
    "QQQ":    "https://logo.clearbit.com/invesco.com",
    "XLE":    "https://logo.clearbit.com/ssga.com",
    "GGAL":   "https://logo.clearbit.com/grupogalicia.com.ar",
    "YPFD":   "https://logo.clearbit.com/ypf.com",
    "VIST":   "https://logo.clearbit.com/vistaenergy.com",
    "GLOB":   "https://logo.clearbit.com/globant.com",
    # ONs — empresa emisora
    "YCA6O":  "https://logo.clearbit.com/ypf.com",
    "YMCJO":  "https://logo.clearbit.com/ypf.com",
    "TLCMO":  "https://logo.clearbit.com/telecom.com.ar",
    # Soberanos
    "AL30":   "https://flagcdn.com/w40/ar.png",
    "GD30":   "https://flagcdn.com/w40/ar.png",
    "GD35":   "https://flagcdn.com/w40/ar.png",
    # LECAPs — BCRA
    "S15Y6":  "https://logo.clearbit.com/bcra.gob.ar",
    "S29J6":  "https://logo.clearbit.com/bcra.gob.ar",
    "S31G6":  "https://logo.clearbit.com/bcra.gob.ar",
    # FCI
    "IOLCAMA": "https://logo.clearbit.com/invertironline.com",
}


# ── Universo elegible — pool amplio, el algoritmo decide cuáles recomendar ───
#
# Criterios de inclusión:
#   1. Liquidez real en BYMA (liquidity_score >= 0.4)
#   2. Accesible para retail argentino (min_capital_ars razonable)
#   3. Representatividad de categoría: cubre un "slot" conceptual diferente
#   4. Yield/retorno ajustado al riesgo documentable
#
# Nunca definido por lo que tiene un usuario puntual.
# Actualizable sin cambiar la lógica del comité.

UNIVERSE: list[Instrument] = [

    # ── FCI Money Market ─────────────────────────────────────────────────────
    Instrument(
        ticker="IOLCAMA", name="Fondo Común Money Market ARS",
        asset_type="FCI", currency="ARS",
        base_yield_pct=0.64, risk_level="bajo", min_capital_ars=1_000,
        affinity_carry=0.9, affinity_dolar=0.05, affinity_renta_fija=0.2,
        tags=["money_market", "liquidez_diaria", "capital_garantizado", "fci"],
        job="renta", liquidity_score=1.0,
        logo_url=_LOGO_MAP["IOLCAMA"],
    ),

    # ── LECAPs (Letras de Capitalización del Tesoro) ─────────────────────────
    # Más operadas en BYMA por volumen — duration corto→largo
    Instrument(
        ticker="S15Y6", name="LECAP May-26",
        asset_type="LETRA", currency="ARS",
        base_yield_pct=0.68, risk_level="bajo", min_capital_ars=10_000,
        affinity_carry=1.0, affinity_dolar=0.1, affinity_renta_fija=0.4,
        tags=["carry", "capital_garantizado", "corto_plazo"],
        job="renta", liquidity_score=0.95,
        logo_url=_LOGO_MAP["S15Y6"],
    ),
    Instrument(
        ticker="S29J6", name="LECAP Jun-26",
        asset_type="LETRA", currency="ARS",
        base_yield_pct=0.67, risk_level="bajo", min_capital_ars=10_000,
        affinity_carry=0.95, affinity_dolar=0.1, affinity_renta_fija=0.4,
        tags=["carry", "capital_garantizado", "corto_plazo"],
        job="renta", liquidity_score=0.88,
        logo_url=_LOGO_MAP["S29J6"],
    ),
    Instrument(
        ticker="S31G6", name="LECAP Ago-26",
        asset_type="LETRA", currency="ARS",
        base_yield_pct=0.66, risk_level="bajo", min_capital_ars=10_000,
        affinity_carry=0.9, affinity_dolar=0.1, affinity_renta_fija=0.4,
        tags=["carry", "capital_garantizado", "mediano_plazo"],
        job="renta", liquidity_score=0.90,
        logo_url=_LOGO_MAP["S31G6"],
    ),

    # ── ONs corporativas hard dollar ──────────────────────────────────────────
    # Renta fija privada: menor riesgo que soberano, flujo en USD real
    Instrument(
        ticker="YCA6O", name="YPF ON USD 2026",
        asset_type="ON", currency="USD",
        base_yield_pct=0.085, risk_level="bajo", min_capital_ars=50_000,
        affinity_carry=0.1, affinity_dolar=0.6, affinity_renta_fija=0.95,
        tags=["on", "hard_dollar", "ypf", "vaca_muerta", "flujo_fijo"],
        job="renta", liquidity_score=0.92,
        logo_url=_LOGO_MAP["YCA6O"],
    ),
    Instrument(
        ticker="TLCMO", name="Telecom ON USD 2026",
        asset_type="ON", currency="USD",
        base_yield_pct=0.07, risk_level="bajo", min_capital_ars=50_000,
        affinity_carry=0.1, affinity_dolar=0.55, affinity_renta_fija=0.90,
        tags=["on", "hard_dollar", "telecom", "flujo_fijo"],
        job="renta", liquidity_score=0.80,
        logo_url=_LOGO_MAP["TLCMO"],
    ),
    Instrument(
        ticker="YMCJO", name="YPF ON USD 2029",
        asset_type="ON", currency="USD",
        base_yield_pct=0.09, risk_level="medio", min_capital_ars=50_000,
        affinity_carry=0.1, affinity_dolar=0.6, affinity_renta_fija=0.88,
        tags=["on", "hard_dollar", "ypf", "duration_media"],
        job="renta", liquidity_score=0.75,
        logo_url=_LOGO_MAP["YMCJO"],
    ),

    # ── Bonos soberanos (renta + upside capital) ──────────────────────────────
    Instrument(
        ticker="AL30", name="Bono Soberano AL30",
        asset_type="BOND", currency="USD",
        base_yield_pct=0.16, risk_level="alto", min_capital_ars=30_000,
        affinity_carry=0.2, affinity_dolar=0.8, affinity_renta_fija=0.9,
        tags=["high_yield", "soberano", "spread_compression", "ley_ar"],
        job="ambos", liquidity_score=0.98,
        logo_url=_LOGO_MAP["AL30"],
    ),
    Instrument(
        ticker="GD30", name="Bono Soberano GD30 (ley NY)",
        asset_type="BOND", currency="USD",
        base_yield_pct=0.14, risk_level="alto", min_capital_ars=30_000,
        affinity_carry=0.2, affinity_dolar=0.8, affinity_renta_fija=0.9,
        tags=["high_yield", "ley_ny", "soberano", "institucional"],
        job="ambos", liquidity_score=0.92,
        logo_url=_LOGO_MAP["GD30"],
    ),
    Instrument(
        ticker="GD35", name="Bono Soberano GD35 (ley NY)",
        asset_type="BOND", currency="USD",
        base_yield_pct=0.18, risk_level="alto", min_capital_ars=30_000,
        affinity_carry=0.15, affinity_dolar=0.8, affinity_renta_fija=0.85,
        tags=["high_yield", "ley_ny", "soberano", "largo_plazo"],
        job="ambos", liquidity_score=0.82,
        logo_url=_LOGO_MAP["GD35"],
    ),

    # ── CEDEARs — dolarización via mercado de capitales ───────────────────────

    # MercadoLibre: el más operado de Argentina por volumen nominal
    Instrument(
        ticker="MELI", name="CEDEAR MercadoLibre",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.22, risk_level="medio", min_capital_ars=10_000,
        affinity_carry=0.05, affinity_dolar=0.95, affinity_renta_fija=0.0,
        tags=["dolarizacion", "tech_latam", "lider_regional", "largo_plazo"],
        job="capital", liquidity_score=1.0,
        logo_url=_LOGO_MAP["MELI"],
    ),
    # S&P 500: broad market defensivo, bajo tracking error
    Instrument(
        ticker="SPY", name="CEDEAR S&P 500",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.12, risk_level="medio", min_capital_ars=15_000,
        affinity_carry=0.1, affinity_dolar=0.9, affinity_renta_fija=0.0,
        tags=["dolarizacion", "mercado_usa", "largo_plazo", "defensivo"],
        job="capital", liquidity_score=0.95,
        logo_url=_LOGO_MAP["SPY"],
    ),
    # Nasdaq 100: concentrado en tech megacap
    Instrument(
        ticker="QQQ", name="CEDEAR Nasdaq 100",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.15, risk_level="medio", min_capital_ars=20_000,
        affinity_carry=0.1, affinity_dolar=1.0, affinity_renta_fija=0.0,
        tags=["dolarizacion", "tech_usa", "largo_plazo"],
        job="capital", liquidity_score=0.92,
        logo_url=_LOGO_MAP["QQQ"],
    ),
    # Galicia: proxy ciclo crediticio AR, alta beta al proceso de normalización
    Instrument(
        ticker="GGAL", name="CEDEAR Galicia",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.25, risk_level="alto", min_capital_ars=10_000,
        affinity_carry=0.1, affinity_dolar=0.75, affinity_renta_fija=0.0,
        tags=["bancos_ar", "beta_alto", "ciclo_credito", "normalizacion"],
        job="capital", liquidity_score=0.93,
        logo_url=_LOGO_MAP["GGAL"],
    ),
    # YPF equity: proxy directo Vaca Muerta, más líquido que VIST
    Instrument(
        ticker="YPFD", name="CEDEAR YPF",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.20, risk_level="alto", min_capital_ars=10_000,
        affinity_carry=0.05, affinity_dolar=0.8, affinity_renta_fija=0.0,
        tags=["energia", "vaca_muerta", "hidrocarburos", "exportaciones"],
        job="capital", liquidity_score=0.88,
        logo_url=_LOGO_MAP["YPFD"],
    ),
    # XLE: energía global diversificada, menos volátil que VIST/YPFD
    Instrument(
        ticker="XLE", name="CEDEAR XLE Energy ETF",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.115, risk_level="medio", min_capital_ars=15_000,
        affinity_carry=0.1, affinity_dolar=0.8, affinity_renta_fija=0.0,
        tags=["energia", "commodities", "global", "defensivo"],
        job="capital", liquidity_score=0.78,
        logo_url=_LOGO_MAP["XLE"],
    ),
    # Vista Energy: puro Vaca Muerta, mayor beta que YPFD
    Instrument(
        ticker="VIST", name="CEDEAR Vista Energy",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.28, risk_level="alto", min_capital_ars=10_000,
        affinity_carry=0.05, affinity_dolar=0.7, affinity_renta_fija=0.0,
        tags=["energia", "vaca_muerta", "beta_alto", "crecimiento"],
        job="capital", liquidity_score=0.72,
        logo_url=_LOGO_MAP["VIST"],
    ),
    # Globant: tech latam, lider en servicios digitales
    Instrument(
        ticker="GLOB", name="CEDEAR Globant",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.18, risk_level="medio", min_capital_ars=15_000,
        affinity_carry=0.05, affinity_dolar=0.85, affinity_renta_fija=0.0,
        tags=["tech_latam", "servicios_digitales", "exportaciones", "largo_plazo"],
        job="capital", liquidity_score=0.70,
        logo_url=_LOGO_MAP.get("GLOB", ""),
    ),
]


# ── Resultado de un agente ────────────────────────────────────────────────────

@dataclass
class AgentVote:
    agent: str
    scores: dict[str, float]   # ticker → score
    rationale: str
    conviction: float           # 0-1
    key_signal: str


# ── Pesos de agentes por perfil — nivel módulo para compartir entre funciones ─

AGENT_WEIGHTS: dict[str, dict[str, float]] = {
    "conservador": {
        "Carry ARS": 0.35, "Dolarizacion": 0.20,
        "Renta Fija": 0.20, "Diversificacion": 0.10, "Macro": 0.15,
    },
    "moderado": {
        "Carry ARS": 0.25, "Dolarizacion": 0.25,
        "Renta Fija": 0.25, "Diversificacion": 0.10, "Macro": 0.15,
    },
    "agresivo": {
        "Carry ARS": 0.10, "Dolarizacion": 0.35,
        "Renta Fija": 0.30, "Diversificacion": 0.10, "Macro": 0.15,
    },
}

RISK_PROFILE_FILTERS: dict[str, dict[str, float]] = {
    "conservador": {"bajo": 1.5, "medio": 0.4, "alto": 0.0},
    "moderado":    {"bajo": 1.0, "medio": 1.1, "alto": 0.7},
    "agresivo":    {"bajo": 0.3, "medio": 0.9, "alto": 1.6},
}


# ── Fetch de datos de mercado ─────────────────────────────────────────────────

def _fetch_market() -> dict:
    cache_key = "market"
    if cache_key in _market_cache:
        if time.time() - _market_cache[cache_key]["ts"] < MARKET_CACHE_TTL:
            return _market_cache[cache_key]["data"]

    data = {
        "mep": 1431.0, "blue": 1415.0, "oficial": 1354.0,
        "spread_pct": 5.7,
        "lecap_tna": 68.0,
        "inflation_monthly": 2.5,
        "tasa_real_mensual": 3.2,
        "riesgo_pais": 700,
        "merval_trend": 0.0,   # % variación últimos 5 días (positivo = suba)
        "sources": [],
    }

    # TC MEP, blue, oficial — dolarapi.com
    try:
        r = httpx.get("https://dolarapi.com/v1/dolares", timeout=8)
        r.raise_for_status()
        for d in r.json():
            casa = d.get("casa", "")
            if casa == "bolsa":
                data["mep"] = d.get("venta") or data["mep"]
            elif casa == "blue":
                data["blue"] = d.get("venta") or data["blue"]
            elif casa == "oficial":
                data["oficial"] = d.get("venta") or data["oficial"]
        data["spread_pct"] = round((data["mep"] - data["oficial"]) / data["oficial"] * 100, 1)
        data["sources"].append("dolarapi")
        logger.info("MEP=%.0f Blue=%.0f spread=%.1f%%", data["mep"], data["blue"], data["spread_pct"])
    except Exception as e:
        logger.warning("dolarapi fallo: %s", e)

    # Inflación mensual — BCRA
    try:
        r = httpx.get(
            "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/inflacion",
            timeout=8, headers={"User-Agent": "BuildFuture/1.0"}
        )
        if r.status_code == 200:
            rows = r.json().get("results", [])
            if rows:
                data["inflation_monthly"] = float(rows[-1].get("valor", 2.5))
                data["sources"].append("bcra_inflacion")
    except Exception as e:
        logger.warning("BCRA inflacion fallo: %s", e)

    # Riesgo país (EMBI Argentina) — Ámbito
    try:
        r = httpx.get("https://mercados.ambito.com/riesgopais/variacion", timeout=6)
        if r.status_code == 200:
            payload = r.json()
            # {"fecha":"01/04/2025","valor":"701","variacion":"-1.97%"}
            val = payload.get("valor") or payload.get("value")
            if val:
                data["riesgo_pais"] = int(str(val).replace(",", "").split(".")[0])
                data["sources"].append("ambito_rp")
                logger.info("Riesgo pais: %d", data["riesgo_pais"])
    except Exception as e:
        logger.warning("Ambito riesgo pais fallo: %s", e)

    # Recalcular tasa real
    tna_mensual = data["lecap_tna"] / 12
    data["tasa_real_mensual"] = round(tna_mensual - data["inflation_monthly"], 2)

    _market_cache[cache_key] = {"ts": time.time(), "data": data}
    return data


# ── Agentes expertos ──────────────────────────────────────────────────────────

class AgenteCarryARS:
    """Especialista en carry trade en pesos. Vota por LECAPs/FCI cuando tasa real > 0."""
    name = "Carry ARS"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        tasa_real = market["tasa_real_mensual"]
        inflation = market["inflation_monthly"]
        spread = market["spread_pct"]

        scores: dict[str, float] = {}
        for inst in UNIVERSE:
            s = inst.affinity_carry * 100

            if tasa_real > 2:
                s += 40 if inst.asset_type == "LETRA" else (15 if inst.asset_type == "FCI" else 0)
            elif tasa_real > 0:
                s += 20 if inst.asset_type == "LETRA" else (8 if inst.asset_type == "FCI" else 0)
            elif tasa_real < -1:
                s -= 30 if inst.currency == "ARS" else 0

            # Spread alto → carry ARS pierde atractivo relativo
            if spread > 8:
                s -= 20 if inst.currency == "ARS" else 0

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        conviction = min(max(tasa_real / 5, 0), 1) if tasa_real > 0 else 0.1
        if spread > 8:
            conviction *= 0.5

        if tasa_real > 2:
            key = f"Tasa real positiva: +{tasa_real:.1f}pp/mes ({market['lecap_tna']:.0f}% TNA vs {inflation:.1f}% inflacion)"
        elif tasa_real > 0:
            key = f"Carry levemente positivo: +{tasa_real:.1f}pp — ventana estrecha"
        else:
            key = f"Carry negativo ({tasa_real:.1f}pp) — ARS pierde contra inflacion"

        rationale = (
            f"Con TNA {market['lecap_tna']:.0f}% e inflacion {inflation:.1f}%/mes, "
            f"la tasa real {'es positiva (+' + str(tasa_real) + 'pp)' if tasa_real > 0 else 'es negativa (' + str(tasa_real) + 'pp)'}. "
            f"{'Las LECAPs son la opcion de menor riesgo con rendimiento real garantizado.' if tasa_real > 1 else 'Carry en ARS pierde atractivo — evaluar cobertura.'}"
        )

        return AgentVote(agent=self.name, scores=scores, rationale=rationale,
                         conviction=round(conviction, 2), key_signal=key)


class AgenteDolarizacion:
    """Cobertura cambiaria. Cuando spread MEP/oficial alto, prioriza CEDEARs y bonos USD."""
    name = "Dolarizacion"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        spread = market["spread_pct"]
        mep = market["mep"]
        oficial = market["oficial"]

        scores: dict[str, float] = {}
        for inst in UNIVERSE:
            s = inst.affinity_dolar * 100

            if spread > 8:
                s += 35 if inst.currency == "USD" else -15
            elif spread > 5:
                s += 20 if inst.currency == "USD" else -5
            elif spread > 2:
                s += 8 if inst.currency == "USD" else 0

            # Liquidez alta → prima adicional en contexto de dolarización urgente
            if inst.currency == "USD" and spread > 5:
                s += inst.liquidity_score * 10

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        conviction = min(spread / 10, 1.0)

        if spread > 8:
            key = f"Brecha MEP/oficial {spread:.1f}% — dolarizacion urgente (MEP ${mep:.0f} vs oficial ${oficial:.0f})"
        elif spread > 5:
            key = f"Brecha {spread:.1f}% — cobertura cambiaria recomendada"
        else:
            key = f"Brecha {spread:.1f}% — riesgo cambiario moderado"

        rationale = (
            f"La brecha MEP/oficial del {spread:.1f}% "
            f"{'indica presion cambiaria — los pesos tienen riesgo de depreciacion' if spread > 6 else 'sugiere mantener cobertura en USD'}. "
            f"CEDEARs ajustan automaticamente al CCL."
        )

        return AgentVote(agent=self.name, scores=scores, rationale=rationale,
                         conviction=round(conviction, 2), key_signal=key)


class AgenteRentaFija:
    """Bonos soberanos y ONs. Usa riesgo país real para calibrar upside de BONDs."""
    name = "Renta Fija"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        riesgo_pais = market.get("riesgo_pais", 700)

        scores: dict[str, float] = {}
        for inst in UNIVERSE:
            s = inst.affinity_renta_fija * 100

            if inst.asset_type == "BOND":
                if riesgo_pais < 500:
                    s += 40   # compresión fuerte de spread → máximo upside capital
                elif riesgo_pais < 700:
                    s += 25
                elif riesgo_pais < 900:
                    s += 10
                else:
                    s -= 20   # riesgo soberano alto, reducir exposición
                # Liquidez: preferir AL30 sobre GD35 en contexto incierto
                s += inst.liquidity_score * 8

            if inst.asset_type == "ON":
                # ONs corporativas: siempre atractivas como renta fija privada
                # Premio extra si riesgo país es alto (son menos correlacionadas al soberano)
                bonus = 25 if riesgo_pais > 800 else 20
                s += bonus
                s += inst.liquidity_score * 5

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        if riesgo_pais < 600:
            conviction = 0.85
            key = f"Riesgo pais {riesgo_pais}pb — compresion de spreads favorece bonos soberanos"
        elif riesgo_pais < 900:
            conviction = 0.60
            key = f"Riesgo pais {riesgo_pais}pb — ONs preferibles a soberanos por menor volatilidad"
        else:
            conviction = 0.30
            key = f"Riesgo pais {riesgo_pais}pb — alta incertidumbre, priorizar ONs con colateral real"

        rationale = (
            f"ONs corporativas en USD con menor riesgo soberano. "
            f"Con riesgo pais en {riesgo_pais}pb, "
            f"{'los bonos AL30/GD30 tienen upside significativo si continua compresion de spreads' if riesgo_pais < 700 else 'las ONs aseguran rendimiento con menor volatilidad que soberanos'}."
        )

        return AgentVote(agent=self.name, scores=scores, rationale=rationale,
                         conviction=round(conviction, 2), key_signal=key)


class AgenteDiversificacion:
    """Penaliza concentración. Premio si el usuario no tiene ese tipo de activo."""
    name = "Diversificacion"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        scores: dict[str, float] = {}
        portfolio_set = set(t.upper() for t in portfolio_tickers)

        for inst in UNIVERSE:
            s = 50.0

            if inst.ticker.upper() not in portfolio_set:
                s += 25
            else:
                s -= 20  # ya lo tiene, no concentrar más

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        has_ars    = bool(portfolio_set & _LECAP_TICKERS)
        has_usd    = bool(portfolio_set & _USD_TICKERS)
        has_cedear = bool(portfolio_set & _CEDEAR_TICKERS)

        missing = []
        if not has_ars:
            missing.append("renta ARS (LECAPs)")
        if not has_usd:
            missing.append("activos USD")
        if not has_cedear:
            missing.append("CEDEARs")

        conviction = 0.6 if missing else 0.3
        key = (f"Portfolio actual: {len(portfolio_set)} posiciones — "
               f"{'faltan: ' + ', '.join(missing) if missing else 'bien diversificado'}")
        rationale = (
            f"Un portafolio equilibrado necesita ARS (carry), USD (cobertura) y renta fija. "
            f"{'Te falta: ' + ', '.join(missing) + '.' if missing else 'Tu portafolio esta distribuido.'}"
        )

        return AgentVote(agent=self.name, scores=scores, rationale=rationale,
                         conviction=round(conviction, 2), key_signal=key)


class AgenteMacro:
    """Contexto macro transversal. Ajusta todos los scores según el régimen macro del día."""
    name = "Macro"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        spread = market["spread_pct"]
        inflation = market["inflation_monthly"]
        riesgo_pais = market.get("riesgo_pais", 700)
        tasa_real = market["tasa_real_mensual"]

        # Régimen normalización: riesgo país < 800 y brecha < 10%
        normalizando = riesgo_pais < 800 and spread < 10

        scores: dict[str, float] = {}
        for inst in UNIVERSE:
            s = 50.0

            if normalizando:
                if inst.asset_type in ("BOND", "ON"):
                    s += 25
                if inst.asset_type == "CEDEAR":
                    s += 12
            else:
                # Estrés macro: liquidez y dolarización urgente
                if inst.asset_type == "FCI":
                    s += 30
                if inst.currency == "USD":
                    s += 20

            # Desinflación + carry positivo → LECAPs y FCI atractivos
            if inflation < 3 and tasa_real > 2:
                if inst.asset_type in ("LETRA", "FCI"):
                    s += 20

            # Inflación alta → penalizar ARS largo plazo
            if inflation > 4:
                if inst.currency == "ARS" and "largo_plazo" in inst.tags:
                    s -= 20
                if inst.currency == "USD":
                    s += 10

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        conviction = 0.7 if normalizando else 0.5

        if normalizando:
            key = f"Normalizacion macro: riesgo pais {riesgo_pais}pb, brecha {spread:.1f}% — bonos y renta fija con upside"
        else:
            key = f"Estres macro activo: riesgo pais {riesgo_pais}pb — priorizar liquidez y USD"

        rationale = (
            f"{'Normalizacion macro favorece compresion de spreads y revalorizacion de bonos.' if normalizando else 'Entorno de estres: preservar capital en USD y mantener liquidez.'} "
            f"Inflacion {inflation:.1f}%/mes, tasa real {'+' if tasa_real >= 0 else ''}{tasa_real:.1f}pp."
        )

        return AgentVote(agent=self.name, scores=scores, rationale=rationale,
                         conviction=round(conviction, 2), key_signal=key)


# ── Sets derivados del UNIVERSE ───────────────────────────────────────────────

_LECAP_TICKERS  = frozenset(i.ticker for i in UNIVERSE if i.asset_type == "LETRA")
_USD_TICKERS    = frozenset(i.ticker for i in UNIVERSE if i.currency == "USD")
_CEDEAR_TICKERS = frozenset(i.ticker for i in UNIVERSE if i.asset_type == "CEDEAR")


# ── Scoring interno compartido ────────────────────────────────────────────────

def _compute_scores(
    universe: list[Instrument],
    votes: list[AgentVote],
    weights: dict[str, float],
    risk_filter: dict[str, float],
    capital_ars: float,
    freedom_pct: float,
) -> dict[str, float]:
    """
    Calcula el score final por instrumento para un perfil dado.
    Incluye: agent weighted sum × conviction × risk_filter × liquidity_score.
    """
    final: dict[str, float] = {}
    for inst in universe:
        score = 0.0
        for vote in votes:
            w = weights.get(vote.agent, 0.25)
            agent_score = vote.scores.get(inst.ticker, 0)
            score += w * agent_score * (0.5 + vote.conviction * 0.5)

        score *= risk_filter.get(inst.risk_level, 1.0)
        score *= inst.liquidity_score  # instrumentos más operados ganan naturalmente

        if capital_ars < inst.min_capital_ars:
            score *= 0.25

        freedom_gap = max(0, 1 - freedom_pct / 100)
        score += inst.base_yield_pct * freedom_gap * 20

        final[inst.ticker] = round(score, 2)

    return final


# ── Slot system ───────────────────────────────────────────────────────────────

def _pick_by_slots(ranked: list, profile: str, target: int = 5) -> list:
    """
    Selecciona instrumentos usando slots para garantizar variedad por perfil.
    ranked: [(score, Instrument), ...] ordenado descendente.
    """
    selected: list = []
    used: set = set()

    def best(condition=None):
        for score, inst in ranked:
            if inst.ticker not in used and (condition is None or condition(inst)):
                return (score, inst)
        return None

    def pick(condition=None):
        result = best(condition)
        if result:
            selected.append(result)
            used.add(result[1].ticker)
        return result

    if profile == "conservador":
        pick(lambda i: i.asset_type == "FCI") or pick(lambda i: i.asset_type == "LETRA")
        pick(lambda i: i.asset_type == "LETRA")
        pick(lambda i: i.asset_type == "LETRA") or pick(lambda i: i.asset_type in ("ON", "FCI"))
        pick(lambda i: i.asset_type == "ON" and i.risk_level == "bajo")
        pick(lambda i: i.risk_level != "alto")

    elif profile == "agresivo":
        pick(lambda i: i.risk_level == "alto")
        used_types = {inst.asset_type for _, inst in selected}
        pick(lambda i: i.risk_level == "alto" and i.asset_type not in used_types) or pick(lambda i: i.risk_level == "alto")
        pick(lambda i: i.asset_type == "CEDEAR")
        pick(lambda i: i.risk_level in ("medio", "alto") and i.asset_type != "ON")
        pick()

    else:  # moderado
        pick()
        pick(lambda i: i.currency == "USD")
        used_types = {inst.asset_type for _, inst in selected}
        pick(lambda i: i.asset_type not in used_types)
        used_types = {inst.asset_type for _, inst in selected}
        pick(lambda i: i.asset_type not in used_types) or pick(lambda i: i.currency not in {inst.currency for _, inst in selected}) or pick()
        pick()

    while len(selected) < target:
        result = best()
        if not result:
            break
        selected.append(result)
        used.add(result[1].ticker)

    return selected


# ── Rationale builder ─────────────────────────────────────────────────────────

def _build_rationale(inst: Instrument, winning_agents: list[AgentVote], market: dict) -> tuple[str, str]:
    agents_for = [a for a in winning_agents if a.scores.get(inst.ticker, 0) > 50]

    if inst.asset_type == "FCI":
        rationale = (
            f"Fondo de mercado monetario en ARS con liquidez diaria. "
            f"TNA {inst.base_yield_pct * 100:.0f}% sin riesgo de tasa ni plazo minimo."
        )
        why_now = (
            f"Capital disponible en 24hs con rendimiento similar a LECAP. "
            f"Con inflacion {market['inflation_monthly']:.1f}%/mes genera tasa real positiva sin atar el capital."
        )
    elif inst.asset_type == "LETRA":
        rationale = (
            f"TNA {inst.base_yield_pct * 100:.0f}% con capital garantizado al vencimiento. "
            f"Tasa real positiva de +{market['tasa_real_mensual']:.1f}pp/mes sobre inflacion."
        )
        why_now = (
            f"Con TNA {market['lecap_tna']:.0f}% e inflacion {market['inflation_monthly']:.1f}%/mes, "
            f"cada mes sin invertir en LECAPs es rendimiento real perdido."
        )
    elif inst.asset_type == "CEDEAR":
        style = "tecnologico" if any(t in inst.tags for t in ["tech_usa", "tech_latam"]) else (
            "energetico" if "energia" in inst.tags else "internacional"
        )
        rationale = (
            f"Exposicion en USD al mercado {style} via CCL. "
            f"Ajusta automaticamente al tipo de cambio."
        )
        why_now = (
            f"Brecha MEP/oficial del {market['spread_pct']:.1f}% — "
            f"cada peso sin cobertura pierde terreno frente al dolar."
        )
    elif inst.asset_type == "ON":
        rationale = (
            f"Flujo fijo en dolares reales al {inst.base_yield_pct * 100:.0f}% anual. "
            f"Emisor privado con respaldo en exportaciones — menor riesgo que soberano."
        )
        why_now = (
            "Las ONs son el 'plazo fijo en dolares' del mercado de capitales argentino. "
            "Cupones regulares en USD con menor volatilidad que bonos soberanos."
        )
    elif inst.asset_type == "BOND":
        rationale = (
            f"Bono soberano con {inst.base_yield_pct * 100:.0f}% TIR en USD. "
            f"Upside de capital si Argentina continua comprimiendo spreads."
        )
        why_now = (
            f"Riesgo pais en {market.get('riesgo_pais', 700)}pb — "
            f"cada baja de 100pb implica apreciacion de capital en los bonos."
        )
    else:
        rationale = f"{inst.name} — {inst.base_yield_pct * 100:.0f}% anual en {inst.currency}."
        why_now = "Instrumento recomendado segun condiciones actuales."

    if agents_for:
        rationale += f" | Acuerdan: {', '.join(a.agent for a in agents_for[:2])}."

    return rationale, why_now


# ── Mapa perfil suitability desde risk_level ─────────────────────────────────

_RECOMMENDED_FOR: dict[str, list[str]] = {
    "bajo":  ["conservador", "moderado"],
    "medio": ["moderado", "agresivo"],
    "alto":  ["agresivo"],
}


# ── get_committee_recommendations — endpoint clásico por perfil ───────────────

def get_committee_recommendations(
    capital_ars: float,
    risk_profile: str,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    live_yields: Optional[dict] = None,
) -> dict:
    """Recomendaciones para un perfil específico. Mantiene compatibilidad con el endpoint existente."""
    market = _fetch_market()
    fx_rate = market["mep"]

    universe = UNIVERSE.copy()
    if live_yields:
        for inst in universe:
            if inst.ticker in live_yields:
                inst.base_yield_pct = live_yields[inst.ticker]

    agents = [AgenteCarryARS(), AgenteDolarizacion(), AgenteRentaFija(),
              AgenteDiversificacion(), AgenteMacro()]
    votes = [a.vote(market, current_tickers, capital_ars) for a in agents]

    weights = AGENT_WEIGHTS.get(risk_profile, AGENT_WEIGHTS["moderado"])
    risk_filter = RISK_PROFILE_FILTERS.get(risk_profile, RISK_PROFILE_FILTERS["moderado"])

    final_scores = _compute_scores(universe, votes, weights, risk_filter, capital_ars, freedom_pct)

    ticker_map = {inst.ticker: inst for inst in universe}
    ranked_all = sorted(
        [(s, ticker_map[t]) for t, s in final_scores.items() if s > 0],
        key=lambda x: x[0], reverse=True,
    )

    if not ranked_all:
        ranked_all = [(50.0, universe[0])]

    ranked = _pick_by_slots(ranked_all, risk_profile, target=5)
    if not ranked:
        ranked = ranked_all[:5]

    total_score = sum(s for s, _ in ranked) or 1
    recommendations = []

    for rank, (score, inst) in enumerate(ranked, 1):
        alloc_pct = score / total_score
        amount_ars = capital_ars * alloc_pct
        amount_usd = amount_ars / fx_rate
        monthly_return_usd = amount_usd * inst.base_yield_pct / 12
        rationale, why_now = _build_rationale(inst, votes, market)

        recommendations.append({
            "rank": rank,
            "ticker": inst.ticker,
            "name": inst.name,
            "asset_type": inst.asset_type,
            "job": inst.job,
            "recommended_for": _RECOMMENDED_FOR.get(inst.risk_level, ["moderado"]),
            "logo_url": inst.logo_url,
            "rationale": rationale,
            "why_now": why_now,
            "annual_yield_pct": inst.base_yield_pct,
            "risk_level": inst.risk_level,
            "currency": inst.currency,
            "allocation_pct": round(alloc_pct, 2),
            "amount_ars": round(amount_ars),
            "amount_usd": round(amount_usd, 2),
            "monthly_return_usd": round(monthly_return_usd, 2),
            "score": score,
            "is_hero": rank == 1,
            "agents_agreed": [
                {"agent": v.agent, "conviction": v.conviction, "signal": v.key_signal}
                for v in votes if v.scores.get(inst.ticker, 0) > 50
            ],
        })

    spread = market["spread_pct"]
    tasa_real = market["tasa_real_mensual"]
    if tasa_real > 2 and spread < 6:
        context = f"Momento de carry: tasa real +{tasa_real:.1f}pp/mes con brecha controlada. Las LECAPs son la apuesta dominante."
    elif spread > 8:
        context = f"Brecha {spread:.1f}% — el comite prioriza dolarizacion. Cada peso sin cobertura pierde terreno."
    elif tasa_real > 0 and spread > 5:
        context = f"Contexto mixto: carry positivo (+{tasa_real:.1f}pp) pero brecha {spread:.1f}% elevada. ARS para el corto, USD para el largo."
    else:
        context = "Mercado en transicion. El comite recomienda diversificacion entre ARS y USD."

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "valid_until": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "context_summary": context,
        "committee_signals": [
            {"agent": v.agent, "key_signal": v.key_signal, "conviction": v.conviction, "rationale": v.rationale}
            for v in votes
        ],
        "recommendations": recommendations,
        "market_snapshot": {
            "mep": market["mep"], "spread_pct": market["spread_pct"],
            "lecap_tna": market["lecap_tna"], "inflation_monthly": market["inflation_monthly"],
            "tasa_real_mensual": market["tasa_real_mensual"],
            "riesgo_pais": market.get("riesgo_pais", 700),
            "sources": market["sources"],
        },
    }


# ── get_sections_recommendations — nuevo endpoint sin selector de perfil ──────

def get_sections_recommendations(
    capital_ars: float,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    live_yields: Optional[dict] = None,
) -> dict:
    """
    Corre el scoring para los 3 perfiles en una sola pasada y devuelve
    instrumentos separados por job (renta / capital), cada uno con
    recommended_for indicando para qué perfiles es apto.

    6 por sección, ordenados por score máximo cross-perfiles × liquidez.
    """
    market = _fetch_market()
    fx_rate = market["mep"]

    universe = UNIVERSE.copy()
    if live_yields:
        for inst in universe:
            if inst.ticker in live_yields:
                inst.base_yield_pct = live_yields[inst.ticker]

    # Agentes votan una sola vez (son independientes del perfil)
    agents = [AgenteCarryARS(), AgenteDolarizacion(), AgenteRentaFija(),
              AgenteDiversificacion(), AgenteMacro()]
    votes = [a.vote(market, current_tickers, capital_ars) for a in agents]

    # Scores por perfil para cada instrumento
    profile_scores: dict[str, dict[str, float]] = {}
    for profile in ("conservador", "moderado", "agresivo"):
        profile_scores[profile] = _compute_scores(
            universe, votes,
            AGENT_WEIGHTS[profile],
            RISK_PROFILE_FILTERS[profile],
            capital_ars, freedom_pct,
        )

    # Construir entrada por instrumento
    recs_renta: list[dict] = []
    recs_capital: list[dict] = []

    for inst in universe:
        scores_by_profile = {p: profile_scores[p][inst.ticker] for p in ("conservador", "moderado", "agresivo")}
        max_score = max(scores_by_profile.values())
        avg_score = sum(scores_by_profile.values()) / 3

        if max_score <= 0:
            continue

        # Perfil suitability: incluir perfiles donde el score es significativo (> 30% del max)
        threshold = max_score * 0.3
        active_profiles = [
            p for p in ("conservador", "moderado", "agresivo")
            if scores_by_profile[p] >= threshold
        ]
        # Fallback: usar el mapa estático de risk_level
        recommended_for = active_profiles if active_profiles else _RECOMMENDED_FOR.get(inst.risk_level, ["moderado"])

        # Allocation informativa: porción fija por sección (el usuario ve montos orientativos)
        alloc_ars = capital_ars * 0.17  # ~1/6 del capital por instrumento en sección
        alloc_usd = alloc_ars / fx_rate
        monthly_return_usd = alloc_usd * inst.base_yield_pct / 12

        rationale, why_now = _build_rationale(inst, votes, market)

        rec = {
            "ticker": inst.ticker,
            "name": inst.name,
            "asset_type": inst.asset_type,
            "job": inst.job,
            "recommended_for": recommended_for,
            "logo_url": inst.logo_url,
            "rationale": rationale,
            "why_now": why_now,
            "annual_yield_pct": inst.base_yield_pct,
            "risk_level": inst.risk_level,
            "currency": inst.currency,
            "amount_ars": round(alloc_ars),
            "amount_usd": round(alloc_usd, 2),
            "monthly_return_usd": round(monthly_return_usd, 2),
            "score": round(max_score, 2),
            "avg_score": round(avg_score, 2),
            "agents_agreed": [
                {"agent": v.agent, "conviction": v.conviction, "signal": v.key_signal}
                for v in votes if v.scores.get(inst.ticker, 0) > 50
            ],
        }

        if inst.job in ("renta", "ambos"):
            recs_renta.append(rec)
        if inst.job in ("capital", "ambos"):
            recs_capital.append(rec)

    # Ordenar por score y limitar a 6
    recs_renta.sort(key=lambda x: x["score"], reverse=True)
    recs_capital.sort(key=lambda x: x["score"], reverse=True)

    # Context summary
    spread = market["spread_pct"]
    tasa_real = market["tasa_real_mensual"]
    riesgo_pais = market.get("riesgo_pais", 700)

    if tasa_real > 2 and spread < 6:
        context = f"Momento de carry: tasa real +{tasa_real:.1f}pp/mes. LECAPs dominan la renta en ARS."
    elif spread > 8:
        context = f"Brecha {spread:.1f}% — dolarizacion prioritaria. Capital en USD defensivo."
    elif riesgo_pais < 600:
        context = f"Riesgo pais {riesgo_pais}pb — compresion de spreads da upside a bonos soberanos."
    elif tasa_real > 0 and spread > 5:
        context = f"Contexto mixto: carry positivo (+{tasa_real:.1f}pp) con brecha {spread:.1f}%. ARS corto plazo, USD largo plazo."
    else:
        context = "Diversificacion equilibrada entre renta ARS y capital USD."

    return {
        "renta": recs_renta[:6],
        "capital": recs_capital[:6],
        "context_summary": context,
        "generated_at": datetime.utcnow().isoformat(),
        "market_snapshot": {
            "mep": market["mep"],
            "spread_pct": market["spread_pct"],
            "lecap_tna": market["lecap_tna"],
            "inflation_monthly": market["inflation_monthly"],
            "tasa_real_mensual": market["tasa_real_mensual"],
            "riesgo_pais": riesgo_pais,
            "sources": market["sources"],
        },
    }
