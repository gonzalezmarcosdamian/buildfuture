# Sprint 10 — "BYMA Market Data + DEVALUATION_PROXY Hotfixes"

**Inicio:** 2026-04-11
**Cierre real:** 2026-04-13
**Versión:** v0.12.0 → v0.12.1
**Objetivo:** BYMA real market data (CEDEAR variación/high/low), fix yields ARS→USD con DEVALUATION_PROXY correcto, audit backlog completo.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | `get_cedear_market_data()` — variación hoy, máx/mín, cierre ant. | BE | M | ✅ Hecho | — |
| 2 | InstrumentDetail CEDEAR: MetricRows variación + máx/mín | FE | S | ✅ Hecho | c498c0d |
| 3 | Tests TDD `get_cedear_market_data` (7 tests, 49 total byma_client) | BE TEST | S | ✅ Hecho | b74d06f (S8 carry) |
| 4 | `yield_currency` label InstrumentDetail ("Yield anual ARS" vs "USD") | FE | XS | ✅ Hecho | c498c0d |
| 5 | DEVALUATION_PROXY fix 15% (crawling peg 2026) | BE | XS | ✅ Hecho | hotfix |
| 6 | `yield_calculator_v2` no usa `value_usd` fallback para ARS — evita yields 100%+ | BE | XS | ✅ Hecho | hotfix |
| 7 | Audit backlog completo — marcar 12+ ítems ya resueltos | PM | S | ✅ Hecho | — |
| 8 | Cocos Pesos Plus FCI busca en todas categorías incl. rentaMixta | BE | XS | ✅ Auditado (ya estaba) | — |
| 9 | Hotfixes prod: DEVALUATION_PROXY 50%→15% en split_portfolio_buckets | BE | XS | ✅ Hecho | 52c0169 |

---

## Daily Log

### 2026-04-11 — BYMA market data implementation

**get_cedear_market_data():** Nueva función en `byma_client.py` usando panel `btnCedears`. Retorna:
- `price_ars` — precio spot (vwap o previousSettlementPrice como fallback)
- `prev_close_ars` — cierre anterior (previousClosingPrice)
- `high_ars` / `low_ars` — máximo/mínimo del día
- `variation_pct` — calculada: `(price - prev_close) / prev_close * 100`

Cache: TTL 5 min compartido con `_cedear_full_cache`. Sincroniza con `_cedear_cache` para que `get_cedear_price_ars()` no haga doble HTTP.

**Frontend InstrumentDetail CEDEAR:** MetricRows nuevos mostrando variación con color verde/rojo + máx/mín.

### 2026-04-13 — Audit + hotfixes

**Audit backlog:** 12+ ítems marcados como ✅ que ya estaban implementados en código:
- backfill-non-iol, scheduler update vs skip, create/update/delete snapshot, months_to_goal, fondo de reserva emoji, COPY InstrumentDetail (6), input horizonte años, CapitalGoals res.ok, Toast CASH, non_iol_offset_usd.

**DEVALUATION_PROXY hotfix:** El sprint anterior puso 15% pero los síntomas de $0 renta persistían. Root cause: `calculate_freedom_score` retornaba 0 cuando `monthly_expenses_usd == 0`. Fix: el proxy quedó en 15% (correcto para crawling peg 2026), y la carga de budget se hizo más robusta.

**yield_calculator_v2 ARS fix:** No usar `current_value_usd` como denominador para calcular rendimiento en ARS — produce yields >100% cuando el instrumento fue comprado en momento de alta devaluación.

---

## Decisiones de arquitectura

- **Cache compartido CEDEAR:** `get_cedear_market_data()` y `get_cedear_price_ars()` usan el mismo HTTP call, caches sincronizadas.
- **15% DEVALUATION_PROXY fijo:** Reconocido como limitación — el sprint siguiente (S12) lo reemplazará con estimación dinámica.
- **Audit antes de backlog:** Regla establecida: antes de reportar backlog, verificar en código real.

---

## Velocidad real
9/9 ítems completados ✅
