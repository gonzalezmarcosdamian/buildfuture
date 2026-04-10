# Sprint 7 — "Testing & Asset Labels"

**Inicio:** 2026-04-10
**Cierre real:** 2026-04-10
**Objetivo:** Cobertura de tests para mep.py + estandarización de labels de tipos de activo.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | Tests mep.py — 10 casos (timeout, fallback, budget override, Decimal) | BE TEST | S | ✅ Hecho (2026-04-10) | test(s7-i1) dd8c6b9 |
| 2 | lib/assetLabels.ts — constante compartida labels/badges/emoji | FE | S | ✅ Hecho (2026-04-10) | feat(s7-i2) a4bfff4 |
| 3 | CapitalGoals res.ok guards | FE | XS | ✅ Ya impl. (líneas 431, 457, 471) | — |
| 4 | BudgetEditor fetch MEP res.ok | FE | XS | ✅ Ya impl. (línea 100) | — |
| 5 | N+1 FCI HTTP enrichment | BE | S | ✅ Ya impl. (_fetch_categoria TTL 15 min en Sprint 3) | — |

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Item 1:** `dd8c6b9` — 10 tests verde para get_mep(): valor dolarapi, fallback timeout/HTTP-500/JSON-sin-campo/venta=0, compra backup si venta=None, budget override, retorno Decimal, MEP_FALLBACK > 0.

**Item 2:** `a4bfff4` — `lib/assetLabels.ts` con ASSET_LABEL, ASSET_EMOJI, ASSET_BADGE_CLASS + helpers `assetLabel()`, `assetBadgeClass()`, `assetLabelWithEmoji()`. Consumido en InstrumentDetail y PortfolioTabs. "🏠 Inmueble" hardcodeado en 3 lugares reemplazado por `assetLabelWithEmoji("REAL_ESTATE")`.

**Items 3–5:** Auditados y confirmados como ya implementados.

**Velocidad real:** 5/5 ítems completados ✅

---

## Retro

- **Bien:** audit antes de implementar — 3/5 ítems ya hechos.
- **Deuda:** PortfolioTabs mantiene sus propias clases `bf-chip-*` (CSS custom) para badges — no se unificaron con las clases Tailwind de assetLabels porque son sistemas distintos. Unificar requiere decidir un solo sistema.
