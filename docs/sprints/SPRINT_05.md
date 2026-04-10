# Sprint 5 — "CEDEAR Deep + Yield Integrity"

**Inicio:** 2026-04-10
**Cierre previsto:** 2026-04-17
**Cierre real:** 2026-04-10
**Objetivo:** Enriquecer InstrumentDetail para CEDEARs (los activos más comunes del portfolio) y cablear STOCK live price. Red de seguridad de yields con tests P1.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | STOCK live price: cablear get_stock_price_ars en yield_updater | BE | S | ✅ Hecho (2026-04-10) | feat(s5-i1) 4015ab2 |
| 2 | CEDEAR market data: variación diaria + High/Low desde BYMA | BE+FE | M | ✅ Hecho (2026-04-10) | feat(s5-i2/i3) 86184c9 + 7b509ec |
| 3 | CEDEAR CCL implícito de compra en InstrumentDetail | BE+FE | S | ✅ Hecho (2026-04-10) | (incluido en i2) |
| 4 | TEST suite — validación yield por tipo de instrumento (subset P1) | BE | M | ✅ Hecho (2026-04-10) | test(s5-i4) 6c4275d (14 tests verde) |
| 5 | Léxico Renta vs Rendimiento — audit copy en 3 componentes | FE | S | ✅ Hecho (2026-04-10) | fix(s5-i5) 2d8babf |

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Item 1:** `4015ab2` backend — `update_stock_prices()` en `yield_updater.py`, `_update_stock_prices()` en `scheduler.py`, conectado al daily_close_job.

**Item 2:** `86184c9` backend — `get_cedear_market_data()` en `byma_client.py` (price, prev_close, high, low, variation_pct). Cache TTL 5 min sincronizado con `_cedear_cache`. `get_instrument_detail()` enriquece respuesta.

**Item 3:** (incluido en Item 2) `ccl_compra_usd = PPC_ARS / avg_purchase_price_usd` en portfolio.py. MetricRows en InstrumentDetail mostrando variación diaria (con color), máx/mín y CCL de compra.

**Item 4:** `6c4275d` — 14 tests verde cubriendo LECAP (BYMA/TEA + fallback promedio + fórmula bajo par + CER), BOND (BYMA + tabla GD30 + ticker desconocido), ON (BYMA + tabla TLCMO), FCI (CAFCI fracción + sin external_id), STOCK (ARS→USD + BYMA None + sin MEP).

**Item 5:** `2d8babf` frontend — LECAP sub cambia `TNA` → `TEA` (es tasa efectiva anual de BYMA). Footnote: `TNA/YTM` → `TEA/TNA/YTM/TIR`.

**Velocidad real:** 5/5 ítems completados ✅

---

## Retro

- **Bien:** `get_cedear_market_data()` reutiliza la misma llamada HTTP y sincroniza ambos caches (`_cedear_cache` y `_cedear_full_cache`), sin doble request.
- **Deuda conocida:** CEDEAR `variation_pct` puede ser `null` si BYMA no entrega `previousClosingPrice` (primer día de cotización). UI ya maneja el caso con conditional render.
- **Deuda técnica pendiente:** Letras CER (X-prefix) yield calculado como 0 — requiere BCRA CER index o UVA proyección. Backlogeado como BUG P1.
