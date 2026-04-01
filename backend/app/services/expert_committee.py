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


# ── Instrumento con datos enriquecidos ─────────────────────────────────────

@dataclass
class Instrument:
    ticker: str
    name: str
    asset_type: str       # LETRA | CEDEAR | BOND | ON
    currency: str         # ARS | USD
    base_yield_pct: float
    risk_level: str       # bajo | medio | alto
    min_capital_ars: float
    mercado: str = "bCBA"
    # Factores de afinidad por agente (0-1)
    affinity_carry: float = 0.5
    affinity_dolar: float = 0.5
    affinity_renta_fija: float = 0.5
    tags: list[str] = field(default_factory=list)


# Universo base — yields se actualizan con datos reales de IOL cuando disponible
UNIVERSE: list[Instrument] = [
    # Money market FCI — liquidez diaria, capital garantizado, sin riesgo tasa
    Instrument(
        ticker="IOLCAMA", name="IOL Conservador Money Market",
        asset_type="FCI", currency="ARS",
        base_yield_pct=0.64, risk_level="bajo", min_capital_ars=1_000,
        affinity_carry=0.9, affinity_dolar=0.05, affinity_renta_fija=0.2,
        tags=["money_market", "liquidez_diaria", "capital_garantizado", "fci"],
    ),
    # LECAPs vigentes al Q1-2026 — tickers confirmados en IOL
    Instrument(
        ticker="S15Y6", name="LECAP May-26",
        asset_type="LETRA", currency="ARS",
        base_yield_pct=0.68, risk_level="bajo", min_capital_ars=10_000,
        affinity_carry=1.0, affinity_dolar=0.1, affinity_renta_fija=0.4,
        tags=["carry", "capital_garantizado", "corto_plazo"],
    ),
    Instrument(
        ticker="S31G6", name="LECAP Ago-26",
        asset_type="LETRA", currency="ARS",
        base_yield_pct=0.66, risk_level="bajo", min_capital_ars=10_000,
        affinity_carry=0.9, affinity_dolar=0.1, affinity_renta_fija=0.4,
        tags=["carry", "capital_garantizado", "mediano_plazo"],
    ),
    Instrument(
        ticker="QQQ", name="CEDEAR Nasdaq 100",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.15, risk_level="medio", min_capital_ars=20_000,
        affinity_carry=0.1, affinity_dolar=1.0, affinity_renta_fija=0.0,
        tags=["dolarizacion", "tech_usa", "largo_plazo"],
    ),
    Instrument(
        ticker="SPY", name="CEDEAR S&P 500",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.12, risk_level="medio", min_capital_ars=15_000,
        affinity_carry=0.1, affinity_dolar=0.9, affinity_renta_fija=0.0,
        tags=["dolarizacion", "mercado_usa", "largo_plazo"],
    ),
    Instrument(
        ticker="AL30", name="Bono Soberano AL30",
        asset_type="BOND", currency="USD",
        base_yield_pct=0.16, risk_level="alto", min_capital_ars=30_000,
        affinity_carry=0.2, affinity_dolar=0.8, affinity_renta_fija=0.9,
        tags=["high_yield", "soberano", "spread_compression"],
    ),
    Instrument(
        ticker="GD30", name="Bono Soberano GD30 (ley NY)",
        asset_type="BOND", currency="USD",
        base_yield_pct=0.14, risk_level="alto", min_capital_ars=30_000,
        affinity_carry=0.2, affinity_dolar=0.8, affinity_renta_fija=0.9,
        tags=["high_yield", "ley_ny", "soberano"],
    ),
    Instrument(
        ticker="GGAL", name="CEDEAR Galicia",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.20, risk_level="alto", min_capital_ars=10_000,
        affinity_carry=0.1, affinity_dolar=0.7, affinity_renta_fija=0.0,
        tags=["bancos_ar", "beta_alto", "ciclo_credito"],
    ),
    Instrument(
        ticker="XLE", name="CEDEAR XLE Energy ETF",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.115, risk_level="medio", min_capital_ars=15_000,
        affinity_carry=0.1, affinity_dolar=0.8, affinity_renta_fija=0.0,
        tags=["energia", "vaca_muerta", "commodities"],
    ),
    # YPF ON hard dollar — renta fija privada con respaldo en exportaciones
    Instrument(
        ticker="YCA6O", name="YPF ON USD 2026",
        asset_type="ON", currency="USD",
        base_yield_pct=0.085, risk_level="medio", min_capital_ars=50_000,
        affinity_carry=0.1, affinity_dolar=0.6, affinity_renta_fija=0.95,
        tags=["on", "hard_dollar", "ypf", "vaca_muerta", "flujo_fijo"],
    ),
    # VIST — CEDEAR Vista Energy, beta alto a Vaca Muerta
    Instrument(
        ticker="VIST", name="CEDEAR Vista Energy",
        asset_type="CEDEAR", currency="USD",
        base_yield_pct=0.22, risk_level="alto", min_capital_ars=10_000,
        affinity_carry=0.05, affinity_dolar=0.7, affinity_renta_fija=0.0,
        tags=["energia", "vaca_muerta", "beta_alto", "crecimiento"],
    ),
]


# ── Resultado de un agente ─────────────────────────────────────────────────

@dataclass
class AgentVote:
    agent: str
    scores: dict[str, float]      # ticker → score
    rationale: str                 # resumen de por qué votó así
    conviction: float              # 0-1: qué tan seguro está el agente
    key_signal: str               # la señal más importante que detectó


# ── Fetch de datos de mercado ──────────────────────────────────────────────

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
        "sources": [],
    }

    # TC MEP y blue
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

    # Inflación BCRA
    try:
        r = httpx.get(
            "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/inflacion",
            timeout=8, headers={"User-Agent": "BuildFuture/1.0"}
        )
        if r.status_code == 200:
            rows = r.json().get("results", [])
            if rows:
                data["inflation_monthly"] = float(rows[-1].get("valor", 2.5))
                data["sources"].append("bcra")
    except Exception as e:
        logger.warning("BCRA fallo: %s", e)

    # Riesgo país (EMBI) via ambito/bluelytics fallback
    try:
        r = httpx.get("https://api.bluelytics.com.ar/v2/evolution.json?days=1", timeout=5)
        if r.status_code == 200:
            pass  # no tiene riesgo país pero confirma conectividad
    except Exception:
        pass

    tna_mensual = data["lecap_tna"] / 12
    data["tasa_real_mensual"] = round(tna_mensual - data["inflation_monthly"], 2)

    _market_cache[cache_key] = {"ts": time.time(), "data": data}
    return data


# ── Agentes expertos ───────────────────────────────────────────────────────

class AgenteCarryARS:
    """
    Especialista en carry trade en pesos.
    Detecta cuando la tasa real en ARS es positiva y recomienda LECAPs/letras
    como instrumento de capital garantizado con rendimiento real positivo.
    """
    name = "Carry ARS"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        tasa_real = market["tasa_real_mensual"]
        inflation = market["inflation_monthly"]
        spread = market["spread_pct"]

        scores = {}
        for inst in UNIVERSE:
            s = inst.affinity_carry * 100

            if tasa_real > 2:
                s += 40 if inst.asset_type == "LETRA" else 0
            elif tasa_real > 0:
                s += 20 if inst.asset_type == "LETRA" else 0
            elif tasa_real < -1:
                s -= 30 if inst.asset_type == "LETRA" else 0

            # Si spread MEP alto, carry ARS pierde atractivo relativo
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

        return AgentVote(
            agent=self.name,
            scores=scores,
            rationale=rationale,
            conviction=round(conviction, 2),
            key_signal=key,
        )


class AgenteDolarizacion:
    """
    Especialista en cobertura cambiaria.
    Cuando el spread MEP/oficial es alto, recomienda dolarización via CEDEARs.
    Diferencia entre dolarización defensiva (SPY/QQQ) y especulativa (GGAL/XLE).
    """
    name = "Dolarizacion"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        spread = market["spread_pct"]
        mep = market["mep"]
        oficial = market["oficial"]

        scores = {}
        for inst in UNIVERSE:
            s = inst.affinity_dolar * 100

            if spread > 8:
                s += 35 if inst.currency == "USD" else -15
            elif spread > 5:
                s += 20 if inst.currency == "USD" else -5
            elif spread > 2:
                s += 8 if inst.currency == "USD" else 0

            # CEDEARs indexados al CCL — prima por cobertura inmediata
            if inst.asset_type == "CEDEAR":
                s += 10 if spread > 5 else 0

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        conviction = min(spread / 10, 1.0)

        if spread > 8:
            key = f"Brecha MEP/oficial {spread:.1f}% — dolarizacion urgente (MEP ${mep:.0f} vs oficial ${oficial:.0f})"
        elif spread > 5:
            key = f"Brecha {spread:.1f}% — cobertura cambiaria recomendada"
        else:
            key = f"Brecha {spread:.1f}% — riesgo cambiario moderado, cobertura preventiva"

        rationale = (
            f"La brecha MEP/oficial del {spread:.1f}% "
            f"{'indica presion cambiaria alta — los pesos tienen riesgo de depreciacion acelerada' if spread > 6 else 'sugiere mantener algo de cobertura en USD'}. "
            f"CEDEARs ajustan automaticamente al CCL, protegiendo contra un salto del tipo de cambio."
        )

        return AgentVote(
            agent=self.name,
            scores=scores,
            rationale=rationale,
            conviction=round(conviction, 2),
            key_signal=key,
        )


class AgenteRentaFija:
    """
    Especialista en bonos soberanos y obligaciones negociables.
    Evalúa el contexto post-reestructuración: spread de crédito, riesgo país,
    y la relación cupón/precio para determinar entry points.
    """
    name = "Renta Fija"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        riesgo_pais = market.get("riesgo_pais", 700)
        spread = market["spread_pct"]
        mep = market["mep"]

        scores = {}
        for inst in UNIVERSE:
            s = inst.affinity_renta_fija * 100

            # Bonos soberanos — atractivos cuando riesgo país baja
            if inst.asset_type == "BOND":
                if riesgo_pais < 600:
                    s += 30  # compresion de spread → upside de capital
                elif riesgo_pais < 900:
                    s += 10
                else:
                    s -= 20  # riesgo alto, reducir exposicion soberana

            # ONs — flujo fijo en USD, menos correlacion con soberano
            if inst.asset_type == "ON":
                s += 20  # siempre atractivas como renta fija privada

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        if riesgo_pais < 600:
            conviction = 0.85
            key = f"Riesgo pais {riesgo_pais}pb — compresion de spreads favorece bonos soberanos"
        elif riesgo_pais < 900:
            conviction = 0.55
            key = f"Riesgo pais {riesgo_pais}pb — entrada moderada, preferir ONs sobre soberanos"
        else:
            conviction = 0.25
            key = f"Riesgo pais {riesgo_pais}pb — alta incertidumbre, priorizar ONs con colateral real"

        rationale = (
            f"Las ONs de empresas como YPF ofrecen flujo fijo en USD con menor riesgo soberano. "
            f"Con riesgo pais en {riesgo_pais}pb, "
            f"{'los bonos AL30/GD30 tienen upside de capital significativo si continua la compresion de spreads' if riesgo_pais < 700 else 'las ONs son preferibles para asegurar rendimiento con menor volatilidad'}."
        )

        return AgentVote(
            agent=self.name,
            scores=scores,
            rationale=rationale,
            conviction=round(conviction, 2),
            key_signal=key,
        )


class AgenteDiversificacion:
    """
    Analiza la concentración del portafolio actual.
    Penaliza lo que el usuario ya tiene en exceso y premia lo que falta.
    Objetivo: evitar > 60% en un solo asset_type.
    """
    name = "Diversificacion"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        scores = {}
        portfolio_set = set(t.upper() for t in portfolio_tickers)

        for inst in UNIVERSE:
            s = 50.0

            # Premio si no lo tiene
            if inst.ticker.upper() not in portfolio_set:
                s += 25
            else:
                s -= 20  # ya lo tiene, no concentrar

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
        key = f"Portfolio actual: {len(portfolio_set)} posiciones — {'faltan: ' + ', '.join(missing) if missing else 'bien diversificado'}"
        rationale = (
            f"Un portafolio equilibrado en Argentina deberia tener ARS (carry), USD (cobertura) y renta fija. "
            f"{'Te falta exposicion en: ' + ', '.join(missing) + '.' if missing else 'Tu portafolio esta bien distribuido.'}"
        )

        return AgentVote(
            agent=self.name,
            scores=scores,
            rationale=rationale,
            conviction=round(conviction, 2),
            key_signal=key,
        )


class AgenteMacro:
    """
    Contexto macro transversal. Ajusta el score de todos los instrumentos
    según el régimen macro actual: normalización (post-acuerdo FMI),
    brecha cambiaria, y dinámica inflacionaria.
    No penaliza ni premia por tipo de instrumento sino por el contexto global.
    """
    name = "Macro"

    def vote(self, market: dict, portfolio_tickers: list[str], capital_ars: float) -> AgentVote:
        spread = market["spread_pct"]
        inflation = market["inflation_monthly"]
        riesgo_pais = market.get("riesgo_pais", 700)
        tasa_real = market["tasa_real_mensual"]

        # Régimen: "normalizacion" si riesgo_país < 800 y spread < 10
        normalizando = riesgo_pais < 800 and spread < 10

        scores = {}
        for inst in UNIVERSE:
            s = 50.0

            if normalizando:
                # En normalización: bonos y renta fija tienen upside de capital
                if inst.asset_type in ("BOND", "ON"):
                    s += 25
                # CEDEARs siguen siendo buenos hedge pero menos urgencia
                if inst.asset_type == "CEDEAR":
                    s += 10
            else:
                # Estrés macro: liquidez y dolarización urgente
                if inst.asset_type == "FCI":
                    s += 30
                if inst.currency == "USD":
                    s += 20

            # Inflación alta → penalizar ARS largo plazo, premiar USD
            if inflation > 4:
                if inst.currency == "ARS" and "largo_plazo" in inst.tags:
                    s -= 20
                if inst.currency == "USD":
                    s += 10
            elif inflation < 3 and tasa_real > 2:
                # Desinflación con carry positivo → LECAPs atractivas
                if inst.asset_type in ("LETRA", "FCI"):
                    s += 20

            if capital_ars < inst.min_capital_ars:
                s = 0

            scores[inst.ticker] = max(s, 0)

        conviction = 0.7 if normalizando else 0.5

        if normalizando:
            key = f"Normalizacion macro: riesgo pais {riesgo_pais}pb, brecha {spread:.1f}% — bonos y renta fija con upside"
        else:
            key = f"Estrés macro activo: riesgo pais {riesgo_pais}pb, brecha {spread:.1f}% — priorizar liquidez y USD"

        rationale = (
            f"{'El proceso de normalizacion macro favorece compresion de spreads y revalorizacion de bonos.' if normalizando else 'Entorno de estres: preservar capital en USD y mantener liquidez.'} "
            f"Inflacion {inflation:.1f}%/mes, tasa real {'+' if tasa_real >= 0 else ''}{tasa_real:.1f}pp."
        )

        return AgentVote(
            agent=self.name,
            scores=scores,
            rationale=rationale,
            conviction=round(conviction, 2),
            key_signal=key,
        )


# ── Sets derivados de UNIVERSE — precalculados para no recalcular en cada vote() ──
_LECAP_TICKERS  = frozenset(i.ticker for i in UNIVERSE if i.asset_type == "LETRA")
_USD_TICKERS    = frozenset(i.ticker for i in UNIVERSE if i.currency == "USD")
_CEDEAR_TICKERS = frozenset(i.ticker for i in UNIVERSE if i.asset_type == "CEDEAR")

# ── Orquestador ───────────────────────────────────────────────────────────

RISK_PROFILE_FILTERS = {
    "conservador": {"bajo": 1.5, "medio": 0.4, "alto": 0.0},
    "moderado":    {"bajo": 1.0, "medio": 1.1, "alto": 0.7},
    "agresivo":    {"bajo": 0.3, "medio": 0.9, "alto": 1.6},
}

# ── Slot system — garantiza variedad por perfil ────────────────────────────
# Cada slot es una función que devuelve True si el instrumento califica.
# El orquestador elige el mejor instrumento que pasa el filtro sin repetir.


def _pick_by_slots(ranked: list, profile: str, target: int = 5) -> list:
    """
    Selecciona hasta `target` instrumentos usando el slot system.
    ranked: [(score, Instrument), ...] ordenado descendente.
    Garantiza variedad por perfil y rellena con los mejores restantes.
    """
    selected: list = []
    used: set = set()

    def best(condition=None):
        """Mejor instrumento no usado que cumple condition (None = cualquiera)."""
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
        # Slot 1: capital garantizado + liquidez → FCI money market, fallback LETRA
        if not pick(lambda i: i.asset_type == "FCI"):
            pick(lambda i: i.asset_type == "LETRA")
        # Slot 2: LETRA corto plazo (carry ARS)
        pick(lambda i: i.asset_type == "LETRA")
        # Slot 3: segunda LETRA (más largo) si hay, sino CEDEAR defensivo
        if not pick(lambda i: i.asset_type == "LETRA"):
            pick(lambda i: i.asset_type == "CEDEAR" and i.risk_level in ("bajo", "medio"))
        # Slot 4: dolarización defensiva → CEDEAR bajo/medio
        pick(lambda i: i.asset_type == "CEDEAR" and i.risk_level in ("bajo", "medio"))
        # Slot 5: mejor restante sin riesgo alto
        if not pick(lambda i: i.risk_level != "alto"):
            pick()

    elif profile == "agresivo":
        # Slot 1: mayor retorno → riesgo alto
        pick(lambda i: i.risk_level == "alto")
        # Slot 2: segundo riesgo alto de tipo distinto (BOND vs CEDEAR)
        used_types = {inst.asset_type for _, inst in selected}
        if not pick(lambda i: i.risk_level == "alto" and i.asset_type not in used_types):
            pick(lambda i: i.risk_level == "alto")
        # Slot 3: CEDEAR USD líquido (diversificación)
        pick(lambda i: i.asset_type == "CEDEAR")
        # Slot 4: riesgo medio USD (ej: SPY/QQQ/XLE)
        pick(lambda i: i.risk_level in ("medio", "alto"))
        # Slot 5: cualquier restante
        pick()

    else:  # moderado
        # Slot 1: mejor score global
        pick()
        # Slot 2: instrumento USD obligatorio (dolarización)
        pick(lambda i: i.currency == "USD")
        # Slot 3: tipo diferente a los ya seleccionados
        used_types = {inst.asset_type for _, inst in selected}
        pick(lambda i: i.asset_type not in used_types)
        # Slot 4: otro tipo o moneda diferente (ARS si todos son USD y viceversa)
        used_types = {inst.asset_type for _, inst in selected}
        if not pick(lambda i: i.asset_type not in used_types):
            used_currencies = {inst.currency for _, inst in selected}
            if not pick(lambda i: i.currency not in used_currencies):
                pick()
        # Slot 5: mejor restante sin restricción
        pick()

    # Rellenar hasta target con los mejores restantes (sin duplicar)
    while len(selected) < target:
        result = best()
        if not result:
            break
        selected.append(result)
        used.add(result[1].ticker)

    return selected


def _build_rationale(inst: Instrument, winning_agents: list[AgentVote], market: dict) -> tuple[str, str]:
    """Genera rationale compuesto con las voces de los agentes que votaron alto."""
    agents_for = [a for a in winning_agents if a.scores.get(inst.ticker, 0) > 50]

    if inst.asset_type == "FCI":
        rationale = (
            f"Money market en ARS con liquidez diaria — rescate acreditado en 24hs. "
            f"TNA {inst.base_yield_pct * 100:.0f}% sin riesgo de tasa ni plazo minimo."
        )
        why_now = (
            f"Ideal para el tramo conservador: rendimiento similar a LECAP con total liquidez. "
            f"Con inflacion {market['inflation_monthly']:.1f}%/mes, genera tasa real positiva sin atar el capital."
        )
    elif inst.asset_type == "LETRA":
        rationale = (
            f"TNA {inst.base_yield_pct * 100:.0f}% con capital garantizado al vencimiento. "
            f"Tasa real positiva de +{market['tasa_real_mensual']:.1f}pp/mes sobre inflacion."
        )
        why_now = (
            f"Con TNA {market['lecap_tna']:.0f}% e inflacion {market['inflation_monthly']:.1f}%/mes, "
            f"cada mes que pasa sin invertir en LECAPs es rendimiento real perdido."
        )
    elif inst.asset_type == "CEDEAR":
        rationale = (
            f"Exposicion en USD al mercado {'tecnologico' if 'tech' in inst.tags else 'internacional'} "
            f"via CCL. Ajusta automaticamente al tipo de cambio."
        )
        why_now = (
            f"Brecha MEP/oficial del {market['spread_pct']:.1f}% — "
            f"cada peso que queda sin cobertura pierde contra el dolar."
        )
    elif inst.asset_type == "ON":
        rationale = (
            f"Flujo fijo en dolares reales (hard dollar) al {inst.base_yield_pct * 100:.0f}% anual. "
            f"Emisor privado con respaldo en exportaciones — menor riesgo que soberano."
        )
        why_now = (
            f"Las ONs son el 'plazo fijo en dolares' del mercado de capitales argentino. "
            f"Cupones regulares en USD con menor volatilidad que bonos soberanos."
        )
    elif inst.asset_type == "BOND":
        rationale = (
            f"Bono soberano con {inst.base_yield_pct * 100:.0f}% TIR en USD. "
            f"Upside de capital si Argentina continua comprimiendo spreads."
        )
        why_now = (
            f"Post-acuerdo FMI, el spread soberano tiene recorrido a la baja. "
            f"Cada baja de 100pb en riesgo pais implica apreciacion de capital."
        )
    else:
        rationale = f"{inst.name} — {inst.base_yield_pct * 100:.0f}% anual en {inst.currency}."
        why_now = "Instrumento recomendado segun condiciones actuales."

    if agents_for:
        rationale += f" | Acuerdan: {', '.join(a.agent for a in agents_for[:2])}."

    return rationale, why_now


def get_committee_recommendations(
    capital_ars: float,
    risk_profile: str,
    freedom_pct: float,
    monthly_savings_usd: float,
    current_tickers: list[str],
    live_yields: Optional[dict] = None,
) -> dict:
    """
    Punto de entrada principal. Corre todos los agentes y devuelve
    las recomendaciones con el análisis del comité.
    """
    market = _fetch_market()
    fx_rate = market["mep"]

    # Actualizar yields con datos reales si están disponibles
    universe = UNIVERSE.copy()
    if live_yields:
        for inst in universe:
            if inst.ticker in live_yields:
                old = inst.base_yield_pct
                inst.base_yield_pct = live_yields[inst.ticker]
                logger.info("Yield actualizado %s: %.2f%% -> %.2f%%",
                            inst.ticker, old * 100, inst.base_yield_pct * 100)

    # Correr cada agente
    agents = [
        AgenteCarryARS(),
        AgenteDolarizacion(),
        AgenteRentaFija(),
        AgenteDiversificacion(),
        AgenteMacro(),
    ]

    votes: list[AgentVote] = [
        a.vote(market, current_tickers, capital_ars)
        for a in agents
    ]

    # Pesos de cada agente según perfil de riesgo
    agent_weights = {
        "conservador": {
            "Carry ARS": 0.35,
            "Dolarizacion": 0.20,
            "Renta Fija": 0.20,
            "Diversificacion": 0.10,
            "Macro": 0.15,
        },
        "moderado": {
            "Carry ARS": 0.25,
            "Dolarizacion": 0.25,
            "Renta Fija": 0.25,
            "Diversificacion": 0.10,
            "Macro": 0.15,
        },
        "agresivo": {
            "Carry ARS": 0.10,
            "Dolarizacion": 0.35,
            "Renta Fija": 0.30,
            "Diversificacion": 0.10,
            "Macro": 0.15,
        },
    }
    weights = agent_weights.get(risk_profile, agent_weights["moderado"])

    # Scoring final: weighted sum × conviction × perfil de riesgo
    risk_filter = RISK_PROFILE_FILTERS.get(risk_profile, RISK_PROFILE_FILTERS["moderado"])

    final_scores: dict[str, float] = {}
    for inst in universe:
        if capital_ars < inst.min_capital_ars:
            final_scores[inst.ticker] = 0
            continue

        score = 0.0
        for vote in votes:
            w = weights.get(vote.agent, 0.25)
            agent_score = vote.scores.get(inst.ticker, 0)
            score += w * agent_score * (0.5 + vote.conviction * 0.5)

        # Ajuste por perfil de riesgo
        score *= risk_filter.get(inst.risk_level, 1.0)

        # Freedom gap: si falta mucho para libertad financiera, priorizar yield
        freedom_gap = max(0, 1 - freedom_pct / 100)
        score += inst.base_yield_pct * freedom_gap * 20

        final_scores[inst.ticker] = round(score, 2)

    # Ordenar todos los instrumentos por score
    ticker_map = {inst.ticker: inst for inst in universe}
    ranked_all = sorted(
        [(s, ticker_map[t]) for t, s in final_scores.items() if s > 0],
        key=lambda x: x[0],
        reverse=True,
    )

    if not ranked_all:
        ranked_all = [(50.0, universe[0])]

    # Selección por slots — garantiza variedad por perfil (5 instrumentos)
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
                for v in votes
                if v.scores.get(inst.ticker, 0) > 50
            ],
        })

    # Context summary del comité
    spread = market["spread_pct"]
    tasa_real = market["tasa_real_mensual"]
    top_signals = [v.key_signal for v in sorted(votes, key=lambda x: x.conviction, reverse=True)[:2]]

    if tasa_real > 2 and spread < 6:
        context = f"Momento de carry: tasa real +{tasa_real:.1f}pp/mes con brecha controlada. Las LECAPs son la apuesta dominante."
    elif spread > 8:
        context = f"Brecha {spread:.1f}% — el comite prioriza dolarizacion. Cada peso sin cobertura pierde terreno."
    elif tasa_real > 0 and spread > 5:
        context = f"Contexto mixto: carry positivo (+{tasa_real:.1f}pp) pero brecha {spread:.1f}% elevada. El comite divide: ARS para el corto, USD para el largo."
    else:
        context = f"Mercado en transicion. El comite recomienda diversificacion entre ARS y USD."

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "valid_until": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "context_summary": context,
        "committee_signals": [
            {
                "agent": v.agent,
                "key_signal": v.key_signal,
                "conviction": v.conviction,
                "rationale": v.rationale,
            }
            for v in sorted(votes, key=lambda x: x.conviction, reverse=True)
        ],
        "market_data": {
            "mep": market["mep"],
            "blue": market["blue"],
            "spread_pct": market["spread_pct"],
            "inflation_monthly": market["inflation_monthly"],
            "tasa_real_mensual": market["tasa_real_mensual"],
            "sources": market["sources"],
        },
        "risk_profile": risk_profile,
        "live_yields_used": bool(live_yields),
        "recommendations": recommendations,
    }
