"""
Motor de recomendaciones inteligente basado en scoring — sin API externa de IA.
Consulta datos de mercado en tiempo real y aplica reglas financieras argentinas.
"""

import logging
import time
import httpx
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("buildfuture.smart_recs")

_market_cache: dict = {}
MARKET_CACHE_TTL = 3600  # 1 hora


# ── Universo de instrumentos ─────────────────────────────────────────────────


@dataclass
class Instrument:
    ticker: str
    name: str
    asset_type: str  # CEDEAR | LETRA | BOND | ON | CRYPTO
    currency: str  # ARS | USD
    base_yield_pct: float
    risk_level: str  # bajo | medio | alto
    min_capital_ars: float
    # Factores de scoring (se multiplican por condiciones de mercado)
    score_fx_hedge: float  # sube si MEP spread es alto (dolarización urgente)
    score_yield_carry: float  # sube si tasa real ARS es positiva
    score_freedom_bar: float  # peso cuando freedom bar es bajo (necesita yield)
    score_diversify: float  # sube si el usuario no lo tiene
    tags: list[str] = field(default_factory=list)


UNIVERSE = [
    Instrument(
        ticker="S31O5",
        name="LECAP Oct-25 (corto plazo)",
        asset_type="LETRA",
        currency="ARS",
        base_yield_pct=0.68,
        risk_level="bajo",
        min_capital_ars=10000,
        score_fx_hedge=0.3,
        score_yield_carry=1.0,
        score_freedom_bar=0.8,
        score_diversify=0.7,
        tags=["capital_preservation", "carry_trade", "corto_plazo"],
    ),
    Instrument(
        ticker="S15G5",
        name="LECAP Jun-25 (muy corto)",
        asset_type="LETRA",
        currency="ARS",
        base_yield_pct=0.72,
        risk_level="bajo",
        min_capital_ars=5000,
        score_fx_hedge=0.2,
        score_yield_carry=1.0,
        score_freedom_bar=0.7,
        score_diversify=0.6,
        tags=["capital_preservation", "carry_trade", "liquidez"],
    ),
    Instrument(
        ticker="QQQ",
        name="CEDEAR QQQ — Nasdaq 100",
        asset_type="CEDEAR",
        currency="USD",
        base_yield_pct=0.15,
        risk_level="medio",
        min_capital_ars=20000,
        score_fx_hedge=1.0,
        score_yield_carry=0.3,
        score_freedom_bar=0.6,
        score_diversify=0.9,
        tags=["dolarizacion", "tech_usa", "largo_plazo"],
    ),
    Instrument(
        ticker="SPY",
        name="CEDEAR SPY — S&P 500",
        asset_type="CEDEAR",
        currency="USD",
        base_yield_pct=0.12,
        risk_level="medio",
        min_capital_ars=15000,
        score_fx_hedge=1.0,
        score_yield_carry=0.3,
        score_freedom_bar=0.5,
        score_diversify=0.9,
        tags=["dolarizacion", "mercado_usa", "largo_plazo"],
    ),
    Instrument(
        ticker="YCA6O",
        name="ON YPF USD (hard dollar)",
        asset_type="ON",
        currency="USD",
        base_yield_pct=0.09,
        risk_level="medio",
        min_capital_ars=50000,
        score_fx_hedge=0.9,
        score_yield_carry=0.5,
        score_freedom_bar=0.9,
        score_diversify=0.8,
        tags=["flujo_fijo", "hard_dollar", "cuasi_soberano"],
    ),
    Instrument(
        ticker="AL30",
        name="Bono Soberano AL30",
        asset_type="BOND",
        currency="USD",
        base_yield_pct=0.16,
        risk_level="alto",
        min_capital_ars=30000,
        score_fx_hedge=0.8,
        score_yield_carry=0.4,
        score_freedom_bar=1.0,
        score_diversify=0.7,
        tags=["high_yield", "soberano", "spread_compression"],
    ),
    Instrument(
        ticker="GD30",
        name="Bono Soberano GD30 (ley NY)",
        asset_type="BOND",
        currency="USD",
        base_yield_pct=0.14,
        risk_level="alto",
        min_capital_ars=30000,
        score_fx_hedge=0.8,
        score_yield_carry=0.4,
        score_freedom_bar=0.9,
        score_diversify=0.7,
        tags=["high_yield", "ley_ny", "soberano"],
    ),
    Instrument(
        ticker="GGAL",
        name="CEDEAR Galicia (banco AR)",
        asset_type="CEDEAR",
        currency="USD",
        base_yield_pct=0.20,
        risk_level="alto",
        min_capital_ars=10000,
        score_fx_hedge=0.7,
        score_yield_carry=0.2,
        score_freedom_bar=0.5,
        score_diversify=0.8,
        tags=["bancos_ar", "ciclo_credito", "beta_alto"],
    ),
    Instrument(
        ticker="XLE",
        name="CEDEAR XLE — Energy ETF",
        asset_type="CEDEAR",
        currency="USD",
        base_yield_pct=0.115,
        risk_level="medio",
        min_capital_ars=15000,
        score_fx_hedge=0.9,
        score_yield_carry=0.2,
        score_freedom_bar=0.4,
        score_diversify=0.8,
        tags=["energia", "vaca_muerta", "commodities"],
    ),
]


# ── Fetch de datos de mercado ─────────────────────────────────────────────────


def _fetch_market_data() -> dict:
    cache_key = "market"
    if cache_key in _market_cache:
        if time.time() - _market_cache[cache_key]["ts"] < MARKET_CACHE_TTL:
            return _market_cache[cache_key]["data"]

    data = {
        "mep": 1431.0,
        "blue": 1415.0,
        "oficial": 1354.0,
        "spread_pct": 1.1,
        "lecap_tna": 68.0,  # TNA referencial mercado secundario
        "inflation_monthly": 2.5,
        "tasa_real_mensual": 0.0,
        "merval_ytd": 45.0,
        "sources": [],
    }

    # 1. TC MEP y blue
    try:
        r = httpx.get("https://dolarapi.com/v1/dolares", timeout=8)
        r.raise_for_status()
        dolares = r.json()
        for d in dolares:
            casa = d.get("casa", "")
            if casa == "bolsa":
                data["mep"] = d.get("venta") or data["mep"]
            elif casa == "blue":
                data["blue"] = d.get("venta") or data["blue"]
            elif casa == "oficial":
                data["oficial"] = d.get("venta") or data["oficial"]
        data["spread_pct"] = round(
            (data["mep"] - data["oficial"]) / data["oficial"] * 100, 1
        )
        data["sources"].append("dolarapi")
        logger.info(
            "TC fetched: MEP=%s blue=%s spread=%s%%",
            data["mep"],
            data["blue"],
            data["spread_pct"],
        )
    except Exception as e:
        logger.warning("dolarapi falló: %s", e)

    # 2. Inflación y tasa real — BCRA API pública
    try:
        r = httpx.get(
            "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/inflacion",
            timeout=8,
            headers={"User-Agent": "BuildFuture/1.0"},
        )
        if r.status_code == 200:
            rows = r.json().get("results", [])
            if rows:
                data["inflation_monthly"] = float(rows[-1].get("valor", 2.5))
                data["sources"].append("bcra")
                logger.info("Inflación mensual BCRA: %s%%", data["inflation_monthly"])
    except Exception as e:
        logger.warning("BCRA inflación falló: %s", e)

    # 3. Tasa real = TNA mensualizada vs inflación
    tna_mensual = data["lecap_tna"] / 12
    data["tasa_real_mensual"] = round(tna_mensual - data["inflation_monthly"], 2)

    _market_cache[cache_key] = {"ts": time.time(), "data": data}
    return data


# ── Motor de scoring ──────────────────────────────────────────────────────────

RISK_PROFILES = {
    "conservador": {"bajo": 1.4, "medio": 0.6, "alto": 0.0},
    "moderado": {"bajo": 1.0, "medio": 1.0, "alto": 0.5},
    "agresivo": {"bajo": 0.7, "medio": 1.0, "alto": 1.3},
}


def score_instrument(
    inst: Instrument,
    market: dict,
    freedom_pct: float,
    current_tickers: list[str],
    capital_ars: float,
    risk_profile: str,
) -> float:
    score = 50.0  # base

    # 1. Capital mínimo
    if capital_ars < inst.min_capital_ars:
        return 0.0  # no alcanza el mínimo

    # 2. Perfil de riesgo
    risk_weights = RISK_PROFILES.get(risk_profile, RISK_PROFILES["moderado"])
    score *= risk_weights.get(inst.risk_level, 1.0)

    # 3. Spread MEP/oficial — si > 3% favorece dolarización
    spread = market["spread_pct"]
    if spread > 5:
        score += inst.score_fx_hedge * 25
    elif spread > 2:
        score += inst.score_fx_hedge * 12

    # 4. Tasa real positiva favorece carry en ARS
    if market["tasa_real_mensual"] > 0:
        score += inst.score_yield_carry * 20 * (market["tasa_real_mensual"] / 3)
    elif market["tasa_real_mensual"] < -1:
        score -= inst.score_yield_carry * 15  # carry negativo, penalizar ARS

    # 5. Freedom bar — si es bajo, priorizar yield
    freedom_gap = max(0, 1 - freedom_pct / 100)
    score += inst.score_freedom_bar * freedom_gap * 20

    # 6. Diversificación — premiar lo que no tiene
    if inst.ticker not in current_tickers:
        score += inst.score_diversify * 15
    else:
        score -= 10  # ya lo tiene

    # 7. Yield absoluto — más yield = más score (moderado)
    score += inst.base_yield_pct * 30

    return round(score, 2)


def _build_rationale(inst: Instrument, market: dict, rank: int) -> tuple[str, str]:
    """Genera rationale y why_now dinámicos según condiciones de mercado."""
    spread = market["spread_pct"]
    tasa_real = market["tasa_real_mensual"]
    inflation = market["inflation_monthly"]

    rationale_map = {
        "LETRA": (
            f"Tasa real {'positiva' if tasa_real > 0 else 'negativa'} en ARS "
            f"({inst.base_yield_pct*100:.0f}% TEA). Sin riesgo precio, capital garantizado.",
            f"TNA mensualizada supera inflación en {tasa_real:.1f}pp. "
            f"El carry trade en ARS {'sigue activo' if tasa_real > 0 else 'está comprimido'}.",
        ),
        "CEDEAR": (
            f"Exposición dolarizada al mercado {'tecnológico' if 'tech' in (inst.tags or []) else 'internacional'} "
            f"de EE.UU. vía CCL, sin necesidad de transferir divisas.",
            f"Spread MEP/oficial del {spread:.1f}% hace atractiva la dolarización vía CEDEARs "
            f"{'— urgente si spread sube más' if spread > 4 else '— cobertura preventiva'}.",
        ),
        "ON": (
            f"Flujo fijo en dólares reales (hard dollar) con {inst.base_yield_pct*100:.0f}% anual. "
            f"Emisor cuasi-soberano con respaldo de exportaciones.",
            f"Spread soberano en compresión post-acuerdo FMI. "
            f"Buen punto de entrada para asegurar yield en USD.",
        ),
        "BOND": (
            f"Alto rendimiento en USD ({inst.base_yield_pct*100:.0f}% anual) a precio de descuento. "
            f"Upside de capital si Argentina continúa comprimiendo spreads.",
            f"Con inflación mensual del {inflation:.1f}% y carry positivo, "
            f"los bonos soberanos ofrecen la mejor relación yield/riesgo del mercado local.",
        ),
    }

    return rationale_map.get(
        inst.asset_type,
        (
            f"{inst.name} — rendimiento estimado {inst.base_yield_pct*100:.0f}% anual en {inst.currency}.",
            "Instrumento recomendado según condiciones actuales del mercado.",
        ),
    )


def get_smart_recommendations(
    capital_ars: float,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    risk_profile: str = "moderado",
) -> dict:
    market = _fetch_market_data()
    fx_rate = market["mep"]

    # Score todos los instrumentos
    scored = []
    for inst in UNIVERSE:
        s = score_instrument(
            inst, market, freedom_pct, current_tickers, capital_ars, risk_profile
        )
        if s > 0:
            scored.append((s, inst))

    # Ordenar por score desc
    scored.sort(key=lambda x: x[0], reverse=True)
    top3 = scored[:3]

    # Distribuir capital proporcionalmente a los scores
    total_score = sum(s for s, _ in top3) or 1
    recommendations = []

    for rank, (score, inst) in enumerate(top3, 1):
        alloc_pct = score / total_score
        amount_ars = capital_ars * alloc_pct
        amount_usd = amount_ars / fx_rate
        monthly_return_usd = amount_usd * inst.base_yield_pct / 12
        rationale, why_now = _build_rationale(inst, market, rank)

        recommendations.append(
            {
                "rank": rank,
                "ticker": inst.ticker,
                "name": inst.name,
                "asset_type": inst.asset_type,
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
            }
        )

    # Context summary dinámico
    spread = market["spread_pct"]
    tasa_real = market["tasa_real_mensual"]
    if spread > 5 and tasa_real > 0:
        context = f"Spread MEP {spread:.1f}% y tasa real positiva ({tasa_real:+.1f}pp/mes): momento ideal para combinar carry ARS con cobertura cambiaria."
    elif spread > 5:
        context = f"Spread MEP elevado ({spread:.1f}%): prioridad en dolarización vía CEDEARs y hard dollar."
    elif tasa_real > 0:
        context = f"Tasa real positiva ({tasa_real:+.1f}pp/mes): el carry en pesos supera la inflación — momento para LECAPs mientras dure."
    else:
        context = f"Mercado en transición. Inflación {market['inflation_monthly']:.1f}%/mes. Diversificación entre ARS y USD es clave."

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "valid_until": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "context_summary": context,
        "market_data": {
            "mep": market["mep"],
            "blue": market["blue"],
            "spread_pct": market["spread_pct"],
            "inflation_monthly": market["inflation_monthly"],
            "tasa_real_mensual": market["tasa_real_mensual"],
            "sources": market["sources"],
        },
        "risk_profile": risk_profile,
        "recommendations": recommendations,
    }
