"""
Motor de recomendaciones IA — Claude Haiku 4.5.
Genera recomendaciones semanales basadas en portafolio + mercado + objetivo.
Cachea el resultado 7 días.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import anthropic

from app.services.market_data import MarketSnapshot

logger = logging.getLogger("buildfuture.ai_recs")

# Cache simple en memoria — persiste mientras el proceso viva
_cache: dict = {}
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 días


@dataclass
class AIRecommendation:
    rank: int
    ticker: str
    name: str
    asset_type: str
    rationale: str
    why_now: str
    annual_yield_pct: float
    risk_level: str  # bajo | medio | alto
    currency: str  # ARS | USD
    allocation_pct: float
    amount_ars: float
    amount_usd: float
    monthly_return_usd: float
    is_hero: bool = False


SYSTEM_PROMPT = """Sos un asesor financiero argentino experto en el mercado local.
Tu trabajo es generar recomendaciones de inversión personalizadas, accionables y honestas.
Siempre respondés en JSON válido con la estructura exacta que se te pide.
No agregás disclaimers ni texto fuera del JSON."""


def _build_prompt(
    capital_ars: float,
    fx_rate: float,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    market: MarketSnapshot,
) -> str:
    capital_usd = capital_ars / fx_rate
    spread_pct = ((market.mep_usd - market.blue_usd) / market.blue_usd) * 100

    return f"""
Contexto del usuario:
- Capital disponible para invertir: ARS {capital_ars:,.0f} (≈ USD {capital_usd:.0f})
- Tipo de cambio MEP actual: ARS {market.mep_usd}
- Freedom Bar actual: {freedom_pct:.1f}% (objetivo: 100%)
- Ahorro mensual: USD {monthly_savings_usd:.0f}/mes
- Portafolio actual (tickers): {current_tickers or ['ninguno — 100% líquido']}

Contexto del mercado argentino hoy:
- Dólar MEP: ARS {market.mep_usd} | Blue: ARS {market.blue_usd} | Spread: {spread_pct:.1f}%
- TNA LECAPs corto plazo: ~{market.lecap_tna_pct}%
- Inflación mensual última: ~{market.inflation_monthly_pct}%
- Top CEDEARs momentum: {[f"{c['ticker']} +{c['ytd_pct']}% YTD" for c in market.top_cedears[:3]]}

Instrucción:
Generá exactamente 3 recomendaciones de inversión rankeadas por prioridad para este usuario.
La #1 es la más importante ("hero card" — mejor match ahora).
Considerá: su Freedom Bar ({freedom_pct:.1f}%), gaps en su portafolio, condiciones de mercado.
Solo instrumentos disponibles en IOL (BCBA): CEDEARs, LECAPs, bonos soberanos (AL30/GD30), ONs.
Montos proporcionales al capital disponible.

Respondé SOLO con este JSON (sin texto adicional):
{{
  "generated_at": "{datetime.utcnow().isoformat()}",
  "valid_until": "{(datetime.utcnow() + timedelta(days=7)).isoformat()}",
  "context_summary": "Una frase explicando el estado actual y por qué estas recomendaciones",
  "recommendations": [
    {{
      "rank": 1,
      "ticker": "TICKER",
      "name": "Nombre completo",
      "asset_type": "CEDEAR|LETRA|BOND|ON",
      "rationale": "Por qué este instrumento para este usuario (2 oraciones)",
      "why_now": "Por qué ahora, dado el contexto de mercado actual (1 oración)",
      "annual_yield_pct": 0.00,
      "risk_level": "bajo|medio|alto",
      "currency": "ARS|USD",
      "allocation_pct": 0.00,
      "amount_ars": 0,
      "amount_usd": 0.0,
      "monthly_return_usd": 0.0
    }}
  ]
}}
"""


def get_ai_recommendations(
    capital_ars: float,
    fx_rate: float,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    market: MarketSnapshot,
    force_refresh: bool = False,
) -> dict:
    cache_key = f"recs_{int(capital_ars/50000)*50000}"  # agrupa por tramos de 50k

    if not force_refresh and cache_key in _cache:
        cached = _cache[cache_key]
        if time.time() - cached["ts"] < CACHE_TTL_SECONDS:
            logger.info(
                "Recomendaciones desde cache (age=%ds)", time.time() - cached["ts"]
            )
            return cached["data"]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY no configurada — usando fallback estático")
        return _fallback_recommendations(capital_ars, fx_rate)

    logger.info("Generando recomendaciones IA — capital=ARS %s", capital_ars)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(
        capital_ars, fx_rate, freedom_pct, monthly_savings_usd, current_tickers, market
    )

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Limpiar posible markdown
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        logger.info("Recomendaciones IA generadas OK")

        # Marcar hero
        if data.get("recommendations"):
            data["recommendations"][0]["is_hero"] = True
            for r in data["recommendations"][1:]:
                r["is_hero"] = False

        _cache[cache_key] = {"ts": time.time(), "data": data}
        return data

    except Exception as e:
        logger.error("Error generando recomendaciones IA: %s", e)
        return _fallback_recommendations(capital_ars, fx_rate)


def _fallback_recommendations(capital_ars: float, fx_rate: float) -> dict:
    """Recomendaciones estáticas cuando la IA no está disponible."""
    capital_usd = capital_ars / fx_rate
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "valid_until": (datetime.utcnow() + timedelta(days=7)).isoformat(),
        "context_summary": "Configurá tu ANTHROPIC_API_KEY para recomendaciones personalizadas con IA.",
        "recommendations": [
            {
                "rank": 1,
                "ticker": "S15G5",
                "name": "LECAP corto plazo",
                "asset_type": "LETRA",
                "rationale": "Tasa real positiva en ARS sin riesgo precio.",
                "why_now": "El carry trade en ARS sigue activo con tasas superiores a la inflación.",
                "annual_yield_pct": 0.70,
                "risk_level": "bajo",
                "currency": "ARS",
                "allocation_pct": 0.40,
                "amount_ars": capital_ars * 0.40,
                "amount_usd": capital_usd * 0.40,
                "monthly_return_usd": capital_usd * 0.40 * 0.70 / 12,
                "is_hero": True,
            },
            {
                "rank": 2,
                "ticker": "QQQ",
                "name": "CEDEAR QQQ — Nasdaq 100",
                "asset_type": "CEDEAR",
                "rationale": "Exposición dolarizada al tech de EE.UU. via CCL.",
                "why_now": "Cobertura cambiaria ante posible aceleración del crawling peg.",
                "annual_yield_pct": 0.15,
                "risk_level": "medio",
                "currency": "USD",
                "allocation_pct": 0.35,
                "amount_ars": capital_ars * 0.35,
                "amount_usd": capital_usd * 0.35,
                "monthly_return_usd": capital_usd * 0.35 * 0.15 / 12,
                "is_hero": False,
            },
            {
                "rank": 3,
                "ticker": "YCA6O",
                "name": "ON YPF USD",
                "asset_type": "ON",
                "rationale": "Flujo fijo en dólares reales con emisor cuasi-soberano.",
                "why_now": "Spread comprimiendo post-acuerdo FMI, buen entry point.",
                "annual_yield_pct": 0.09,
                "risk_level": "medio",
                "currency": "USD",
                "allocation_pct": 0.25,
                "amount_ars": capital_ars * 0.25,
                "amount_usd": capital_usd * 0.25,
                "monthly_return_usd": capital_usd * 0.25 * 0.09 / 12,
                "is_hero": False,
            },
        ],
    }
