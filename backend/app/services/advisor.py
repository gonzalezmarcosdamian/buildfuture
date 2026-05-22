"""
Invest Advisor — motor de análisis con Claude AI.

5 tipos de consulta, 5 créditos por usuario por día.
Skills adaptados de github.com/tradermonty/claude-trading-skills para
el contexto del mercado argentino y el portafolio BuildFuture.

Tipos:
  portfolio   → Exposure Coach (postura del portafolio)
  technical   → Technical Analyst (soporte/resistencia, patrones)
  fundamental → US Stock Analysis adaptado para acciones ARG/USA
  macro       → Market Environment Analysis (régimen, risk-on/off)
  scenario    → Scenario Analyzer (impacto de evento/noticia)
"""

import logging
import os
from datetime import date, datetime, timezone, timedelta
from typing import Iterator

import anthropic
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("buildfuture.advisor")

DAILY_CREDIT_LIMIT = 5
ART_OFFSET = timedelta(hours=-3)  # UTC-3 Argentina

# ── Disclaimer ────────────────────────────────────────────────────────────────

DISCLAIMER = (
    "\n\n---\n"
    "*Este análisis es informativo y no constituye asesoramiento financiero "
    "ni recomendación de inversión. BuildFuture no es una sociedad de bolsa "
    "ni un asesor financiero registrado. Consultá con un profesional matriculado "
    "antes de tomar decisiones. Rendimientos pasados no garantizan resultados futuros.*"
)

# ── System prompts por skill ───────────────────────────────────────────────────

_SKILL_PORTFOLIO = """\
Sos un advisor de portafolio para inversores argentinos. Tu tarea es hacer un
diagnóstico rápido y accionable del portafolio del usuario.

Estructura tu respuesta así:
1. **Postura general** — ¿El portafolio está bien balanceado? (2-3 líneas)
2. **Renta vs Capital** — Qué % genera flujo mensual vs qué % es acumulación
3. **Concentración** — ¿Hay overexposure a algún activo/sector/moneda?
4. **Freedom %** — ¿Qué tan cerca está de cubrir sus gastos mensuales con renta?
5. **Una acción concreta** — La cosa más importante que podría hacer ahora

Sé directo, concreto y específico al portafolio del usuario. No des listas
genéricas. Máximo 350 palabras. Responde en español rioplatense.

Contexto del mercado argentino: operás en un entorno con alta inflación en pesos,
tipo de cambio MEP relevante para dolarización, y acceso a LECAP, FCI, CEDEARs,
bonos soberanos/ON y cripto. El usuario invierte en IOL, Cocos Capital o Binance.
"""

_SKILL_TECHNICAL = """\
Sos un analista técnico especializado en activos del mercado argentino y
mercados internacionales accesibles desde Argentina (CEDEARs, ETFs, cripto,
bonos soberanos).

Dado un ticker o instrumento, realizá el siguiente análisis:
1. **Tendencia** — Alcista / bajista / lateral en el marco temporal relevante
2. **Soporte y resistencia clave** — Los niveles más importantes
3. **Señales actuales** — Qué indica el momentum y el volumen
4. **Escenarios** — Bullish (probabilidad y target), Bearish (probabilidad y nivel de invalidación)
5. **Conclusión operativa** — Entry zone, stop sugerido, relación riesgo/retorno

Si no tenés datos de precio en tiempo real, trabajá con la información disponible
y aclará las limitaciones. Basate en análisis técnico puro — sin fundamentals.
Máximo 400 palabras. Responde en español rioplatense.

Nota: para instrumentos argentinos, el precio cotiza en ARS pero el retorno
real en USD depende del MEP. Mencioná esta distinción cuando sea relevante.
"""

_SKILL_FUNDAMENTAL = """\
Sos un analista fundamental especializado en empresas y activos disponibles
desde Argentina: acciones USA vía CEDEAR, bonos soberanos y corporativos,
ONs de empresas argentinas.

Para el activo solicitado, analizá:
1. **¿Qué es?** — Descripción del negocio / instrumento en 2 líneas
2. **Valuación** — ¿Caro, barato o justo? Métricas clave (P/E, EV/EBITDA, YTM, spread según corresponda)
3. **Calidad del negocio / crédito** — Fortalezas y riesgos estructurales
4. **Catalizadores** — Qué podría mover el precio en los próximos 3-6 meses
5. **Riesgo principal** — El riesgo que más importa monitorear
6. **Veredicto** — En una línea: atractivo / neutral / evitar y por qué

Usá datos de búsqueda web si están disponibles. Sé honesto con la incertidumbre.
Máximo 400 palabras. Responde en español rioplatense.

Contexto ARG: para CEDEARs, la paridad importa (ratio de conversión vs precio USA).
Para ONs, el spread sobre Treasury y el riesgo crediticio del emisor son clave.
"""

_SKILL_MACRO = """\
Sos un analista macro especializado en el contexto económico-financiero argentino
y global, con foco en cómo afecta a los inversores minoristas locales.

Producí un briefing del entorno actual:
1. **Régimen macro ARG** — ¿Estabilización / recuperación / estrés? Señales clave
2. **Tipo de cambio y dolarización** — MEP, dinámica de brecha, presión compradora/vendedora
3. **Tasa e inflación** — LECAP vs inflación esperada, ¿conviene tasa o dólar?
4. **Mercado global** — Risk-on / risk-off y cómo impacta en CEDEARs y cripto
5. **Posicionamiento sugerido** — ¿Más pesos o más dólares? ¿Renta o capital? ¿Plazo?

Usá los datos de mercado inyectados en el contexto. Sé concreto y específico.
Máximo 400 palabras. Responde en español rioplatense.
"""

_SKILL_SCENARIO = """\
Sos un analista de escenarios especializado en impacto de eventos macro y
noticias sobre portafolios de inversores argentinos.

Dado un evento o noticia, construí un análisis de escenarios a 6-18 meses:

**Fase 1: Clasificación del evento**
- Tipo (política monetaria / fiscal / geopolítica / sectorial / cripto)
- Probabilidad de cada escenario

**Fase 2: Escenarios**
Para cada uno (Bull / Base / Bear):
- Descripción en 2 líneas
- Impacto en: pesos, MEP/CCL, bonos ARG, CEDEARs, cripto
- Activos que se benefician / se perjudican

**Fase 3: Implicancias para el portafolio**
- Qué posiciones quedan bien posicionadas
- Qué exposiciones generan riesgo
- Una acción de cobertura o posicionamiento

Máximo 450 palabras. Responde en español rioplatense.

IMPORTANTE: Este análisis es educativo. No es recomendación de inversión.
"""

SKILL_PROMPTS: dict[str, str] = {
    "portfolio":   _SKILL_PORTFOLIO,
    "technical":   _SKILL_TECHNICAL,
    "fundamental": _SKILL_FUNDAMENTAL,
    "macro":       _SKILL_MACRO,
    "scenario":    _SKILL_SCENARIO,
}

QUERY_TYPE_LABELS = {
    "portfolio":   "📊 Mi cartera",
    "technical":   "📈 Análisis técnico",
    "fundamental": "🏢 Análisis fundamental",
    "macro":       "🌍 Contexto macro",
    "scenario":    "🎯 Escenario",
}

# ── Créditos ──────────────────────────────────────────────────────────────────

def _today_art() -> date:
    return (datetime.now(timezone.utc) + ART_OFFSET).date()


def get_credits_used(db: Session, user_id: str) -> int:
    today = _today_art()
    result = db.execute(
        text(
            "SELECT COUNT(*) FROM advisor_usage "
            "WHERE user_id = :uid "
            "AND created_at >= :start AND created_at < :end"
        ),
        {
            "uid": user_id,
            "start": datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone(ART_OFFSET)),
            "end": datetime.combine(today + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone(ART_OFFSET)),
        },
    ).scalar()
    return int(result or 0)


def consume_credit(db: Session, user_id: str, query_type: str, ticker: str | None) -> None:
    db.execute(
        text(
            "INSERT INTO advisor_usage (user_id, query_type, ticker) "
            "VALUES (:uid, :qt, :ticker)"
        ),
        {"uid": user_id, "qt": query_type, "ticker": ticker},
    )
    db.commit()


# ── Contexto del portafolio ───────────────────────────────────────────────────

def _build_portfolio_context(user_id: str, db: Session) -> str:
    """Construye un resumen del portafolio del usuario para inyectar al prompt."""
    from app.models import Position, BudgetConfig
    from app.services.freedom_calculator import split_portfolio_buckets
    from app.services.mep import get_mep

    positions = (
        db.query(Position)
        .filter(Position.user_id == user_id, Position.is_active.is_(True))
        .all()
    )
    if not positions:
        return "El usuario no tiene posiciones activas en su portafolio."

    budget = (
        db.query(BudgetConfig)
        .filter(BudgetConfig.user_id == user_id)
        .order_by(BudgetConfig.effective_month.desc())
        .first()
    )
    mep = float(get_mep(budget))
    expenses_usd = float(budget.total_monthly_usd) if budget else 2000.0

    buckets = split_portfolio_buckets(positions, db=db)
    total_usd = sum(float(p.current_value_usd) for p in positions)
    freedom_pct = float(buckets["renta_monthly_usd"]) / expenses_usd * 100 if expenses_usd > 0 else 0

    lines = [
        f"## Portafolio del usuario",
        f"- Total: USD {total_usd:,.0f} (ARS {total_usd * mep:,.0f})",
        f"- MEP actual: ${mep:,.0f}",
        f"- Gastos mensuales: USD {expenses_usd:,.0f}/mes",
        f"- Renta mensual estimada: USD {float(buckets['renta_monthly_usd']):,.2f}/mes",
        f"- Freedom %: {freedom_pct:.1f}% (cubre {freedom_pct:.0f}% de los gastos)",
        f"- Capital acumulado: USD {float(buckets['capital_total_usd']):,.0f}",
        f"- Renta total: USD {float(buckets['renta_total_usd']):,.0f}",
        "",
        "## Posiciones activas",
    ]

    for p in sorted(positions, key=lambda x: float(x.current_value_usd), reverse=True):
        pct_of_total = float(p.current_value_usd) / total_usd * 100 if total_usd > 0 else 0
        lines.append(
            f"- {p.ticker} ({p.asset_type}, {p.source}): "
            f"USD {float(p.current_value_usd):,.0f} ({pct_of_total:.1f}%), "
            f"yield {float(p.annual_yield_pct)*100:.1f}%"
        )

    return "\n".join(lines)


def _build_market_context() -> str:
    """Contexto macro mínimo. Se enriquece con datos live cuando están disponibles."""
    from app.services.mep import get_mep
    try:
        mep = float(get_mep(None))
    except Exception:
        mep = 1430.0
    return f"MEP actual: ~${mep:,.0f} ARS/USD"


# ── Streaming con Claude ──────────────────────────────────────────────────────

def stream_advisor_response(
    query_type: str,
    user_query: str,
    user_id: str,
    db: Session,
    ticker: str | None = None,
) -> Iterator[str]:
    """
    Genera la respuesta del advisor en streaming (chunks de texto).
    Lanza ValueError si no hay créditos o el query_type es inválido.
    """
    if query_type not in SKILL_PROMPTS:
        raise ValueError(f"query_type inválido: {query_type}")

    used = get_credits_used(db, user_id)
    if used >= DAILY_CREDIT_LIMIT:
        raise ValueError("Sin créditos disponibles. Volvé mañana.")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada.")

    system_prompt = SKILL_PROMPTS[query_type]

    # Construir user message con contexto
    context_blocks = []

    if query_type in ("portfolio", "scenario"):
        context_blocks.append(_build_portfolio_context(user_id, db))

    if query_type in ("macro", "scenario", "technical", "fundamental"):
        context_blocks.append(_build_market_context())

    if ticker:
        context_blocks.append(f"Instrumento a analizar: **{ticker.upper()}**")

    context = "\n\n".join(context_blocks)
    user_message = f"{context}\n\n---\n\n{user_query}" if context else user_query

    add_disclaimer = query_type == "scenario"

    # Consumir crédito antes de llamar a la API
    consume_credit(db, user_id, query_type, ticker)

    client = anthropic.Anthropic(api_key=api_key)

    with client.messages.stream(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text_chunk in stream.text_stream:
            yield text_chunk

    if add_disclaimer:
        yield DISCLAIMER
