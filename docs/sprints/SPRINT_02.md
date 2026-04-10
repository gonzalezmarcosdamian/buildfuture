# Sprint 2 — "Correctness + Polish"

**Inicio:** 2026-04-10
**Cierre previsto:** 2026-04-16
**Objetivo:** Eliminar datos engañosos y bugs silenciosos que erosionan la confianza del usuario. Cero breaking changes. Prioridad: bugs P1 de bajo esfuerzo antes que features nuevas.

---

## Definición de Done (DoD)

- [ ] Tests en verde (`pytest` backend)
- [ ] Commiteado y pusheado a main
- [ ] Deploy Railway (backend) y Vercel (frontend) sin errores
- [ ] Ítem en ✅ Hecho del backlog

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | COPY urgente — 5 correcciones InstrumentDetail | FE | S | ✅ Ya impl. (sesión anterior) | — |
| 2 | ON label: TNA → TIR en rentaSub de InstrumentDetail | FE | S | ✅ Ya impl. (sesión anterior) | — |
| 3 | `db.rollback()` faltante en sync Cocos/Nexo + IOL len check | BE | S | ✅ Hecho (2026-04-10) | fix(sync): rollback + validación credenciales |
| 4 | Credenciales `split()` sin validación de longitud | BE | S | ✅ Hecho (2026-04-10) | incluido en ítem 3 |
| 5 | `months_to_goal` negativo → "¡Ya llegaste!" sin presupuesto | FE | S | ✅ Hecho (2026-04-10) | fix(goals): meta alcanzada |
| 6 | Fondo de reserva reaparece al renombrar: detectar por emoji 🛡️ | FE | S | ✅ Hecho (2026-04-10) | incluido en ítem 5 |
| 7 | ArgentinaDatos como segundo fallback BOND/ON yield | BE | M | 🚫 Bloqueado | ArgentinaDatos no tiene endpoint /bonos — 404 |

---

## Criterios de éxito

- Item 1: `InstrumentDetail` no muestra "cupones semestrales", "Rendimiento" → "% desde compra", "Renta mensual estimada" → "Renta estimada / mes *", sin fila CASH, "Rolleo" → "Vence"
- Item 2: ON muestra "TIR X% · cupones periódicos" en lugar de "TNA X%"
- Item 3: sync fallido parcial no persiste posiciones duplicadas en DB
- Item 4: credenciales corruptas devuelven 400 con mensaje claro, no 500/IndexError
- Item 5: meta alcanzada sin presupuesto muestra "¡Ya llegaste!" no "Configurá presupuesto"
- Item 6: meta renombrada con emoji 🛡️ no reaparece la sugerencia de fondo de reserva
- Item 7: BYMA falla → ArgentinaDatos retorna TIR → se usa; ambos fallan → tabla hardcoded

---

## Daily Log

### 2026-04-10 — Kickoff y cierre del sprint

**Items 1 y 2:** ya implementados en InstrumentDetail.tsx en sesión anterior (reconocidos).

**Items 3 y 4:** fix en integrations.py — `5ce369d` backend
- sync_cocos: `db.rollback()` antes de commit en ambos excepts
- sync_nexo: `db.rollback()` + HTTPException si split falla
- sync_iol: `len(creds) != 2` → 400 antes de IndexError

**Items 5 y 6:** fix en CapitalGoals.tsx — `59e3dda` frontend
- GoalCard: `progress_pct >= 100` → "¡Ya llegaste!" sin importar months_to_goal/savings
- Fondo de reserva: detectar también por `emoji === "🛡️"`

**Item 7:** BLOQUEADO — ArgentinaDatos no expone `/bonos` ni `/bonos/soberanos` (404). El endpoint solo tiene letras y FCI. Alternativa: usar CAFCI o tabla estática hasta que BYMA live funcione.

**Velocidad real:** 6/7 ítems completados (1 bloqueado por datos externos)

---

## Impedimentos

*(ninguno al inicio)*

---

## Retrospectiva

*(se completa al cierre del sprint)*

**¿Qué salió bien?**

**¿Qué mejorar?**

**¿Qué aprendimos?**

**Velocidad real:** X/7 ítems completados
