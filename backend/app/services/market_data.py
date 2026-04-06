"""
Snapshot del mercado argentino para alimentar las recomendaciones.
Fuentes públicas — sin auth requerida.
"""

import logging
import httpx
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.byma_client import get_lecap_tna

logger = logging.getLogger("buildfuture.market")


@dataclass
class MarketSnapshot:
    mep_usd: float = 1431.0
    blue_usd: float = 1415.0
    mep_source: str = "fallback"
    lecap_tna_pct: float = 55.0  # TNA referencial LECAPs — se sobreescribe con BYMA
    cer_tna_pct: float = 48.0  # TNA bonos CER
    al30_price: float = 0.0  # Precio AL30 en USD (paridad)
    top_cedears: list[dict] = field(default_factory=list)
    inflation_monthly_pct: float = 2.5  # último dato INDEC


def fetch_market_snapshot() -> MarketSnapshot:
    snap = MarketSnapshot()

    # 1. Tipo de cambio MEP
    try:
        r = httpx.get("https://dolarapi.com/v1/dolares/bolsa", timeout=8)
        r.raise_for_status()
        d = r.json()
        snap.mep_usd = d.get("venta") or d.get("compra") or snap.mep_usd
        snap.mep_source = "dolarapi"
        logger.info("MEP: %s", snap.mep_usd)
    except Exception as e:
        logger.warning("dolarapi falló: %s", e)

    # 2. Dólar blue (proxy spread)
    try:
        r = httpx.get("https://api.bluelytics.com.ar/v2/latest", timeout=8)
        r.raise_for_status()
        snap.blue_usd = r.json().get("blue", {}).get("value_sell", snap.blue_usd)
    except Exception as e:
        logger.warning("bluelytics falló: %s", e)

    # 3. Top CEDEARs por volumen — Rava/IOL no tienen API pública fácil,
    #    usamos lista curada actualizada periódicamente
    snap.top_cedears = [
        {
            "ticker": "SPY",
            "name": "S&P 500 ETF",
            "sector": "mercado_usa",
            "ytd_pct": 8.5,
        },
        {
            "ticker": "QQQ",
            "name": "Nasdaq 100 ETF",
            "sector": "tech_usa",
            "ytd_pct": 6.2,
        },
        {
            "ticker": "XLE",
            "name": "Energy Sector ETF",
            "sector": "energia",
            "ytd_pct": 4.1,
        },
        {"ticker": "GGAL", "name": "Galicia", "sector": "bancos_ar", "ytd_pct": 22.0},
        {"ticker": "YPF", "name": "YPF", "sector": "energia_ar", "ytd_pct": 18.3},
    ]

    # 4. TNA LECAPs desde BYMA Open Data (fallback interno si falla)
    snap.lecap_tna_pct = get_lecap_tna()
    logger.info("lecap_tna: %.2f%%", snap.lecap_tna_pct)

    logger.info("Market snapshot OK: MEP=%s blue=%s lecap_tna=%.2f%%",
                snap.mep_usd, snap.blue_usd, snap.lecap_tna_pct)
    return snap
