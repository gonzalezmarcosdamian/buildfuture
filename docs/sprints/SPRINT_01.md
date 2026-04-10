# Sprint 1 — "Quick wins de calidad"

**Inicio:** 2026-07-08  
**Cierre previsto:** 2026-07-14  
**Objetivo:** Eliminar fricciones visibles para beta users con ítems de bajo esfuerzo y alto impacto. Cero breaking changes.

---

## Definición de Done (DoD)

- [ ] Tests en verde (`pytest` backend, `eslint` frontend)
- [ ] Commiteado y pusheado a main
- [ ] Deploy Railway (backend) y Vercel (frontend) sin errores
- [ ] Ítem en ✅ Hecho del backlog

---

## Items del Sprint

| # | Ítem | Esfuerzo | Estado | PR/Commit |
|---|------|----------|--------|-----------|
| 1 | COPY urgente — 5 correcciones InstrumentDetail | S | ✅ Hecho (2026-04-10) | fix(content): copy audit |
| 2 | BottomNav active state `startsWith` | S | ✅ Hecho (2026-04-10) | fix(nav) |
| 3 | CapitalGoals mutations sin `res.ok` | S | ✅ Hecho (2026-04-10) | — |
| 4 | BudgetEditor fetch MEP sin `res.ok` | S | ✅ Hecho (2026-04-10) | — |
| 5 | Search endpoints sin límite de resultados | S | ✅ Hecho (2026-04-10) | feat(search): add result limits |
| 6 | Freedom % tooltip explicativo | S | ✅ Hecho (2026-04-10) | feat(ux): tooltip Cobertura gastos |
| 7 | Toast de confirmación tras guardar CASH (sonner) | M | ✅ Hecho (2026-04-10) | feat(ux): toast CASH guardado |

> Items 1-4 ya estaban completos de sesiones anteriores — se incorporan al sprint como trabajo reconocido.

---

## Daily Log

### 2026-07-08 — Kickoff

**Completado en sesiones anteriores (reconocido):**
- COPY urgente InstrumentDetail ✅
- BottomNav startsWith ✅
- CapitalGoals res.ok ✅
- BudgetEditor res.ok ✅

**Plan del día:**
1. Search endpoints límite de resultados
2. Freedom % tooltip
3. Toast CASH (si hay tiempo)

### 2026-04-10 — Cierre sprint

**Completado:**
- Item 5: Search endpoints con `max_length` en Query params y `results[:50]` — bba525d (backend)
- Item 6: Tooltip `(?)` inline en "Cobertura gastos" con copy explicativo — cc58724 (frontend)
- Item 7: Toast sonner "Saldo actualizado" tras guardar CASH — cc58724 (frontend). Sonner instalado y Toaster en layout global.

**Velocidad real:** 7/7 ítems completados ✅

---

## Impedimentos

*(ninguno al inicio)*

---

## Retrospectiva

*(se completa al cierre del sprint)*

**¿Qué salió bien?**

**¿Qué mejorar?**

**¿Qué aprendimos?**

**Velocidad real:** 7/7 ítems completados
