# Sprint 3 — "Mobile-first + Performance"

**Inicio:** 2026-04-10
**Cierre previsto:** 2026-04-17
**Objetivo:** Eliminar fricciones de UI en mobile y fixes de performance que afectan a todos los usuarios. Cero breaking changes.

---

## Definición de Done (DoD)

- [ ] Tests en verde (`pytest` backend)
- [ ] ESLint sin errores (frontend)
- [ ] Commiteado y pusheado a main
- [ ] Deploy Railway + Vercel sin errores

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | Tap targets 44px en PortfolioTabs (Pencil/Trash/Check/X) | FE | S | ✅ Ya impl. (sesión anterior) | — |
| 2 | Feedback táctil `active:scale` en tarjetas de posición | FE | S | ✅ Hecho (2026-04-10) | feat(mobile): tap feedback |
| 3 | Skeleton loading en `/portfolio/[ticker]` | FE | M | ✅ Hecho (2026-04-10) | feat(mobile): skeleton loading |
| 4 | N+1 HTTP en FCI enrichment — cachear CATEGORIAS antes del loop | BE | M | ✅ Ya mitigado (cache TTL 15min en _fetch_categoria) | — |
| 5 | MEP hint simétrico + mepLoaded + reset al cambiar moneda | FE | M | ✅ Ya impl. (CashForm líneas 44/93/105-110) | — |

---

## Criterios de éxito

- Item 1: botones CASH edit y tarjetas tienen min 40px de tap target
- Item 2: tocar una tarjeta da feedback visual inmediato (scale) antes de navegar
- Item 3: navegar a `/portfolio/BTC` muestra skeleton mientras carga, no pantalla blanca
- Item 4: sync con 20 FCIs hace 1 HTTP call a ArgentinaDatos, no 20
- Item 5: cambiar USD↔ARS limpia el campo; hint solo aparece cuando MEP cargó; hint simétrico en ambas monedas

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Item 2:** `active:scale-[0.98]` en PortfolioTabs.tsx tarjetas — `faaa6da`
**Item 3:** `loading.tsx` para `/portfolio/[ticker]` — `faaa6da`
**Items 1, 4, 5:** ya implementados en sesiones previas (reconocidos).

---

## Impedimentos

*(ninguno al inicio)*

---

## Retrospectiva

*(se completa al cierre)*

**Velocidad real:** 5/5 ítems completados ✅ (2 ya implementados en sesiones anteriores, 1 ya mitigado por cache existente)
