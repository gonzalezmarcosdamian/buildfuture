"""
Motor de recomendaciones de inversión.
Genera un carrusel de instrumentos según perfil, portafolio actual y capital disponible.
"""

from decimal import Decimal
from dataclasses import dataclass


@dataclass
class InstrumentRecommendation:
    ticker: str
    name: str
    asset_type: str  # CEDEAR | BOND | LETRA | ON | CRYPTO
    market: str  # BCBA | CRYPTO
    allocation_pct: float  # % del capital sugerido
    annual_yield_pct: float
    rationale: str
    risk_level: str  # bajo | medio | alto
    currency: str  # ARS | USD


# Universo de instrumentos recomendables — actualizar periódicamente
INSTRUMENT_UNIVERSE = [
    InstrumentRecommendation(
        ticker="S15G5",
        name="LECAP Jun-25",
        asset_type="LETRA",
        market="BCBA",
        allocation_pct=0.40,
        annual_yield_pct=0.70,
        rationale="Tasa real positiva en ARS, corto plazo, sin riesgo precio. Ideal para capital que necesitás líquido pronto.",
        risk_level="bajo",
        currency="ARS",
    ),
    InstrumentRecommendation(
        ticker="QQQ",
        name="CEDEAR QQQ — Nasdaq 100",
        asset_type="CEDEAR",
        market="BCBA",
        allocation_pct=0.25,
        annual_yield_pct=0.15,
        rationale="Exposición dolarizada al tech de EE.UU. vía CCL. Doble cobertura: tipo de cambio + crecimiento Nasdaq.",
        risk_level="medio",
        currency="USD",
    ),
    InstrumentRecommendation(
        ticker="YCA6O",
        name="ON YPF USD",
        asset_type="ON",
        market="BCBA",
        allocation_pct=0.20,
        annual_yield_pct=0.09,
        rationale="Flujo fijo en dólares reales (hard dollar). Emisor cuasi-soberano con respaldo de exportaciones.",
        risk_level="medio",
        currency="USD",
    ),
    InstrumentRecommendation(
        ticker="AL30",
        name="Bono Soberano AL30",
        asset_type="BOND",
        market="BCBA",
        allocation_pct=0.10,
        annual_yield_pct=0.16,
        rationale="Alto rendimiento en USD a precio de descuento. Upside si Argentina sigue comprimiendo spreads.",
        risk_level="alto",
        currency="USD",
    ),
    InstrumentRecommendation(
        ticker="XLE",
        name="CEDEAR XLE — Energy ETF",
        asset_type="CEDEAR",
        market="BCBA",
        allocation_pct=0.05,
        annual_yield_pct=0.115,
        rationale="Diversificación sectorial al petróleo. Correlaciona con Vaca Muerta y precio Brent.",
        risk_level="medio",
        currency="USD",
    ),
    InstrumentRecommendation(
        ticker="SPY",
        name="CEDEAR SPY — S&P 500",
        asset_type="CEDEAR",
        market="BCBA",
        allocation_pct=0.20,
        annual_yield_pct=0.12,
        rationale="El índice más diversificado de EE.UU. Base sólida dolarizada para cualquier portafolio.",
        risk_level="medio",
        currency="USD",
    ),
    InstrumentRecommendation(
        ticker="GGAL",
        name="CEDEAR GGAL — Galicia",
        asset_type="CEDEAR",
        market="BCBA",
        allocation_pct=0.10,
        annual_yield_pct=0.18,
        rationale="Banco líder argentino con alta exposición al ciclo de crédito local. Beta alto al mercado AR.",
        risk_level="alto",
        currency="USD",
    ),
]


def get_recommendations(
    capital_ars: float,
    fx_rate: float,
    current_tickers: list[str],
    risk_profile: str = "moderado",
) -> list[dict]:
    """
    Retorna recomendaciones ordenadas por prioridad.
    Excluye instrumentos que el usuario ya tiene en cantidad significativa.
    """
    capital_usd = capital_ars / fx_rate

    # Filtrar según perfil de riesgo
    risk_map = {
        "conservador": ["bajo"],
        "moderado": ["bajo", "medio"],
        "agresivo": ["bajo", "medio", "alto"],
    }
    allowed_risks = risk_map.get(risk_profile, ["bajo", "medio"])

    results = []
    for inst in INSTRUMENT_UNIVERSE:
        if inst.risk_level not in allowed_risks:
            continue

        amount_ars = capital_ars * inst.allocation_pct
        amount_usd = amount_ars / fx_rate
        monthly_return_usd = (amount_usd * inst.annual_yield_pct) / 12

        already_have = inst.ticker in current_tickers

        results.append(
            {
                "ticker": inst.ticker,
                "name": inst.name,
                "asset_type": inst.asset_type,
                "market": inst.market,
                "allocation_pct": inst.allocation_pct,
                "amount_ars": round(amount_ars),
                "amount_usd": round(amount_usd, 2),
                "annual_yield_pct": inst.annual_yield_pct,
                "monthly_return_usd": round(monthly_return_usd, 2),
                "rationale": inst.rationale,
                "risk_level": inst.risk_level,
                "currency": inst.currency,
                "already_in_portfolio": already_have,
            }
        )

    # Priorizar los que no tiene
    results.sort(key=lambda x: x["already_in_portfolio"])
    return results
