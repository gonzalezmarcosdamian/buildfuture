# Sprint 9 — "Yields v2 + Price Collector"

**Inicio:** 2026-04-10
**Cierre real:** 2026-04-11
**Versión:** v0.11.0
**Objetivo:** Infraestructura de yields sin APIs en runtime — price collector nocturno + yield_calculator_v2 + DEVALUATION_PROXY fix inicial.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | `instrument_metadata` tabla + BYMA fichatecnica job | BE DB | M | ✅ Hecho | — |
| 2 | `instrument_prices` tabla + price_collector.py (job nocturno) | BE DB | M | ✅ Hecho | — |
| 3 | `position_snapshots.value_ars` + `.mep` — efecto devaluación | BE DB | S | ✅ Hecho | — |
| 4 | `positions.yield_currency` — ARS vs USD | BE DB | S | ✅ Hecho | — |
| 5 | `yield_calculator_v2.py` — cadena compute_* sin APIs runtime | BE | L | ✅ Hecho | — |
| 6 | `yield_updater.py` integra v2 como primario con fallback | BE | M | ✅ Hecho | — |
| 7 | admin endpoints: collect-prices + collect-metadata | BE | S | ✅ Hecho | — |
| 8 | InstrumentDetail label yield_currency ARS vs USD | FE | XS | ✅ Hecho (S10) | c498c0d |
| 9 | Toasts sonner CapitalGoals + IntegrationCard | FE | S | ✅ Hecho | d1c57c6 |

---

## Daily Log

### 2026-04-10 — Arquitectura yields v2

**Problema identificado:** Los yields de LECAPs (TNA ~68%) aplicados sobre `current_value_usd` producían `renta_monthly_usd` inflada. Origen: mezcla de unidades ARS/USD sin corrección por devaluación.

**Solución diseñada:** Separar el ciclo de vida del yield en tres fases:
1. **Recolección nocturna** (`price_collector.py`): 5 HTTP calls post-cierre BYMA → almacenar en `instrument_prices`
2. **Cálculo offline** (`yield_calculator_v2.py`): compute_* functions usando datos en DB, sin APIs en runtime
3. **Actualización diaria** (`yield_updater.py`): aplica v2 como primario, sistema anterior como fallback

**Tablas nuevas:**
- `instrument_metadata(ticker, maturity_date, tem, emision_date, asset_type, updated_at)`
- `instrument_prices(ticker, price_date, price_ars, vwap, previous_close, high, low, source)`

**Campos nuevos:**
- `position_snapshots.value_ars`, `position_snapshots.mep` — para calcular retorno real en USD vs ARS
- `positions.yield_currency` — "ARS" o "USD" — distingue instrumento ARS de hard-dollar

### 2026-04-11 — Fix DEVALUATION_PROXY + backfill historial

**DEVALUATION_PROXY 50% → 15%:** El proxy inicial era 50% (Argentina 2023). Con crawling peg 2026 (~1%/mes = ~12.7% anual), 15% es más conservador pero más realista.

**Backfill historial no-IOL:** Implementado en `admin.py:1142-1244`. Usa `MIN(PositionSnapshot.snapshot_date)` por ticker como fecha de inicio. Historial de Marcos verificado: COCOSPPA desde 3-abr, CASH_USD desde 6-abr, rescate 10-abr reflejado.

**Vercel duplicado eliminado:** `buildfuture-two.vercel.app` borrado — solo existe `frontend-teal-seven-22.vercel.app`.

---

## Decisiones de arquitectura

- **v2 como primario, v1 como fallback:** Si `instrument_prices` tiene datos para el ticker, usar compute_*. Si no (instrumento nuevo, primera semana), caer al sistema legacy que llama BYMA en runtime.
- **yield_currency en Position:** Guardado en DB junto con el yield para que el cálculo de renta no necesite inferir la moneda en runtime.
- **price_collector vs runtime calls:** Correr post-cierre (22:00 ART) para tener datos antes del scheduler de sync nocturno.

---

## Velocidad real

9/9 ítems completados ✅ (algunos en S10 por arrastre de documentación)
