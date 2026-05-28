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

# ── System prompts — v2 ───────────────────────────────────────────────────────
# Principios:
# 1. Respondés SOLO sobre lo que el usuario preguntó en sus respuestas al cuestionario
# 2. Si el portafolio tiene datos, usá los números exactos — no generalices
# 3. Máximo 300 palabras. Sin listas genéricas. Sin disclaimer al principio.
# 4. Terminá con UNA sola acción concreta, no con "considerá diversificar".

_TONO = """\
TONO OBLIGATORIO — aplicar en todos los análisis:
- NUNCA uses imperativo directo ("vendé", "comprá", "reducí", "poné", "salí")
- SIEMPRE usá condicional o potencial: "podría considerarse", "una alternativa sería",
  "en este contexto se observa que", "algunos inversores en esta situación optan por",
  "valdría la pena evaluar si..."
- El análisis describe factores, escenarios y posibilidades — no instruye acciones.
- Cerrá con un factor clave a considerar, no con una orden.
"""

_SKILL_PORTFOLIO = """\
Sos un advisor financiero para inversores argentinos. Recibís el portafolio real
del usuario y las respuestas a un cuestionario previo que define su contexto.

REGLAS ESTRICTAS:
- Usá los números exactos del portafolio (tickers, montos, %)
- Respondé SOLO el problema que el usuario describió en sus respuestas
- No hagas diagnóstico genérico de 5 puntos si solo preguntó una cosa
- Máximo 280 palabras. Español rioplatense. Sin intro corporativa.

OBJETIVO DECLARADO POR EL USUARIO (campo "objetivo_priority" o "¿Qué objetivo..."):
- Si priorizó RENTA: enfocate en freedom % y renta mensual en USD. Mencioná cuánto
  falta en USD para cubrir gastos. El yield importa más que el capital total.
- Si priorizó CAPITAL: NO penalices el freedom % bajo ni la poca renta. El objetivo
  es acumulación. Analizá crecimiento patrimonial y calidad de los activos de largo plazo.
- Si priorizó AMBOS con renta primero: balance entre yield actual y crecimiento,
  dando más peso a la renta mensual.
- Si priorizó AMBOS con capital primero: balance entre crecimiento y yield,
  sin penalizar el freedom % bajo si el horizonte es largo plazo.
- Si no declaró objetivo: usá el contexto del horizonte temporal para inferirlo.

Contexto ARG: MEP vigente, LECAP como renta fija en ARS, FCI como liquidez,
CEDEARs como dolarización, bonos ON como USD fijo. Inflación ~4% mensual.

""" + _TONO

_SKILL_TECHNICAL = """\
Sos un analista técnico para inversores argentinos. Analizás un instrumento específico
considerando el horizonte e intención que el usuario declaró.

REGLAS:
- Si no tenés precio actual, decilo en una línea y analizá con lo que sabés
- Nombrá niveles numéricos concretos cuando puedas (precios aproximados en ARS o USD)
- Para bonos ARG en USD: precio en paridad (% del VN), no en pesos
- Para CEDEARs: precio en ARS pero siempre mencioná el precio del subyacente en USD
- Adaptá el plazo al horizonte que declaró el usuario
- Cerrá con: zonas de interés / niveles a monitorear (no órdenes de entrada/salida)
- Máximo 280 palabras. Sin intro. Directo al análisis.

""" + _TONO

_SKILL_FUNDAMENTAL = """\
Sos un analista fundamental para inversores argentinos. El usuario declaró qué
quiere saber específicamente — no hagas análisis completo si solo preguntó valuación.

REGLAS:
- Respondé primero lo que el usuario pidió explícitamente
- Para CEDEAR: comparar precio ARS vs precio USA × ratio conversión × MEP
- Para ON: YTM aproximada y riesgo crediticio del emisor en 2 líneas
- Para bono soberano: spread sobre UST, paridad, rating implícito de mercado
- Datos aproximados con fecha estimada son mejor que "no hay datos"
- Cerrá con: un factor clave que el usuario debería considerar al evaluar este instrumento
- Máximo 280 palabras. Sin listas de 6 puntos si no son necesarias.

""" + _TONO

_SKILL_MACRO = """\
Sos un analista macro para inversores argentinos minoristas. Respondés sobre
el contexto actual enfocándote en la situación específica que el usuario describió.

REGLAS:
- Empezá por el contexto del usuario: "En el escenario que describís, el entorno actual..."
- MEP actual: usá el dato del portafolio si está disponible
- Sé específico con números: "LECAP al 38% TNA vs inflación estimada 50%..."
- No hagas roadmap de 5 puntos si la pregunta es simple
- Cerrá con los factores que podrían inclinar la balanza en un sentido u otro
- Máximo 280 palabras.

""" + _TONO

_SKILL_SCENARIO = """\
Sos un analista de escenarios para inversores argentinos. El usuario describió
un evento o noticia y declaró cuáles son sus posiciones relevantes.

REGLAS:
- Analizá el impacto potencial en las posiciones específicas que mencionó
- Si tiene AL30 y el evento es macro fiscal: describí los posibles efectos en AL30
- Tres escenarios: Bull/Base/Bear con probabilidad estimada (ej: 20/60/20%)
- Para cada uno: posible impacto en MEP y en las posiciones del usuario
- Mencioná qué factores podrían funcionar como cobertura natural si el Bear ocurre
- Máximo 300 palabras. Disclaimer en una línea al final, no al principio.

""" + _TONO

_SKILL_TICKER = """\
Sos un analista de instrumentos financieros para inversores argentinos. El usuario
te pide información sobre un ticker específico y tiene acceso a su portafolio real.

REGLAS:
- Combiná contexto técnico + fundamental según lo que el usuario quiere saber
- Para ON: emisor, calificación estimada, YTM aproximada, liquidez en BYMA
- Para CEDEAR: ratio de conversión, precio implícito vs subyacente NYSE/NASDAQ
- Para bono soberano: paridad, legislación (NY vs ARG), duration, comparación con pares
- Para acciones ARG: sector, drivers principales, relación con el ciclo local
- Usá los datos del portafolio del usuario para contextualizar si es relevante
  (ej: "ya tenés X% en este sector, lo que implica...")
- Cerrá con: los dos o tres factores más relevantes a considerar para este instrumento
- Máximo 280 palabras. Sin intro. Directo al instrumento.

""" + _TONO

_SKILL_LIBRE = """\
Sos un advisor financiero para inversores argentinos. El usuario te hace una consulta
abierta — puede ser sobre dónde poner capital, comparar alternativas, entender un
instrumento o explorar una estrategia. Tenés acceso a su portafolio real.

REGLAS:
- Interpretá la consulta y respondé lo más útil posible con los datos disponibles
- Si pregunta "dónde poner X USD en Y instrumento": describí 2-3 alternativas concretas
  con sus características (emisor, YTM estimada, riesgo, liquidez) sin recomendar una
- Si pregunta por una estrategia: describí los factores que la hacen viable o no en el
  contexto argentino actual
- Usá los datos del portafolio si son relevantes para la respuesta
- Máximo 300 palabras. Español rioplatense. Sin intro corporativa.

""" + _TONO

SKILL_PROMPTS: dict[str, str] = {
    "portfolio":   _SKILL_PORTFOLIO,
    "technical":   _SKILL_TECHNICAL,
    "fundamental": _SKILL_FUNDAMENTAL,
    "macro":       _SKILL_MACRO,
    "scenario":    _SKILL_SCENARIO,
    "ticker":      _SKILL_TICKER,
    "libre":       _SKILL_LIBRE,
}

QUERY_TYPE_LABELS = {
    "portfolio":   "📊 Mi cartera",
    "technical":   "📈 Análisis técnico",
    "fundamental": "🏢 Análisis fundamental",
    "macro":       "🌍 Contexto macro",
    "scenario":    "🎯 Escenario",
    "ticker":      "🔍 Ticker",
    "libre":       "💬 Consulta libre",
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


def consume_credit(db: Session, user_id: str, query_type: str, ticker: str | None, context_answers: dict | None = None) -> int:
    """Inserta registro de uso y devuelve el id creado."""
    import json
    result = db.execute(
        text(
            "INSERT INTO advisor_usage (user_id, query_type, ticker, context_answers) "
            "VALUES (:uid, :qt, :ticker, :ctx) RETURNING id"
        ),
        {
            "uid": user_id,
            "qt": query_type,
            "ticker": ticker,
            "ctx": json.dumps(context_answers) if context_answers else None,
        },
    )
    row = result.fetchone()
    db.commit()
    return row[0] if row else 0


def save_response(db: Session, usage_id: int, response: str) -> None:
    """Guarda el response completo en el registro de uso."""
    try:
        db.execute(
            text("UPDATE advisor_usage SET response = :r WHERE id = :id"),
            {"r": response, "id": usage_id},
        )
        db.commit()
    except Exception as e:
        logger.warning("save_response failed: %s", e)
        db.rollback()


def get_today_history(db: Session, user_id: str) -> list[dict]:
    """Devuelve las consultas del día con sus respuestas, ordenadas desc."""
    today = _today_art()
    rows = db.execute(
        text(
            "SELECT id, query_type, ticker, context_answers, response, created_at "
            "FROM advisor_usage "
            "WHERE user_id = :uid "
            "AND created_at >= :start AND created_at < :end "
            "AND response IS NOT NULL "
            "ORDER BY created_at DESC"
        ),
        {
            "uid": user_id,
            "start": datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone(ART_OFFSET)),
            "end": datetime.combine(today + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone(ART_OFFSET)),
        },
    ).fetchall()
    return [
        {
            "id": r[0],
            "query_type": r[1],
            "ticker": r[2],
            "context_answers": r[3],
            "response": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]


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
    context_answers: dict | None = None,
) -> Iterator[str]:
    """
    Genera la respuesta del advisor en streaming.
    context_answers: respuestas del cuestionario previo {pregunta: respuesta}.
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

    # ── Contexto del portafolio (siempre para portfolio y scenario) ────────────
    context_blocks: list[str] = []

    if query_type in ("portfolio", "scenario", "macro", "ticker", "libre"):
        context_blocks.append(_build_portfolio_context(user_id, db))

    if query_type in ("macro", "scenario", "technical", "fundamental", "ticker", "libre"):
        context_blocks.append(_build_market_context())

    if ticker:
        context_blocks.append(f"**Instrumento a analizar:** {ticker.upper()}")

    # ── Respuestas del cuestionario — el corazón del v2 ───────────────────────
    if context_answers:
        qa_lines = ["**Contexto declarado por el usuario:**"]
        for pregunta, respuesta in context_answers.items():
            qa_lines.append(f"- {pregunta}: {respuesta}")
        context_blocks.append("\n".join(qa_lines))

    if user_query.strip():
        context_blocks.append(f"**Pregunta / instrucción del usuario:** {user_query}")

    user_message = "\n\n".join(context_blocks) if context_blocks else user_query

    add_disclaimer = query_type == "scenario"

    usage_id = consume_credit(db, user_id, query_type, ticker, context_answers)

    client = anthropic.Anthropic(api_key=api_key)
    full_response: list[str] = []

    with client.messages.stream(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text_chunk in stream.text_stream:
            full_response.append(text_chunk)
            yield text_chunk

    if add_disclaimer:
        full_response.append(DISCLAIMER)
        yield DISCLAIMER

    # Guardar response completo para historial
    if usage_id:
        save_response(db, usage_id, "".join(full_response))
