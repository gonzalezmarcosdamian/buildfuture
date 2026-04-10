# Sprint 6 — "Instrument Detail Polish"

**Inicio:** 2026-04-10
**Cierre real:** 2026-04-10
**Objetivo:** Completar InstrumentDetail con contexto para tipos sin cobertura + verificar ítems ya implementados en sprints anteriores.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | ASSET_CONTEXT faltantes: ON, STOCK, ETF | BE | S | ✅ Hecho (2026-04-10) | feat(s6-i1) 91e1cda |
| 2 | BottomNav active state: startsWith | FE | XS | ✅ Ya impl. (pathname.startsWith en línea 43) | — |
| 3 | Tap targets 44px en Pencil/Trash/Check/X | FE | XS | ✅ Ya impl. (p-2.5 + min-w/h-[44px] en Sprint 3) | — |
| 4 | Feedback táctil active:scale en tarjetas | FE | XS | ✅ Ya impl. (active:scale-[0.98] en Sprint 3) | — |
| 5 | COPY COPY: labels broker amigables IOL/PPI/COCOS | FE | XS | ✅ Ya impl. (línea 607 InstrumentDetail.tsx) | — |

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Item 1:** `91e1cda` — ON (full_name + descripción + liquidez), STOCK (BCBA + ARS→USD MEP), ETF (replica índice + USD). Antes mostraban "Activo financiero." genérico.

**Items 2–5:** Auditados y confirmados como ya implementados en sprints anteriores.

**Velocidad real:** 5/5 ítems completados ✅ (1 implementado, 4 ya cubiertos)

---

## Retro

- **Bien:** El audit antes de implementar evitó re-trabajo en 4/5 ítems.
- **Pendiente de backlog:** Contexto BOND con variante por ticker (AL/GD → "soberano hard-dollar") — baja prioridad, aplazar.
