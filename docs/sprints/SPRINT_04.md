# Sprint 4 — "Trust & Onboarding"

**Inicio:** 2026-04-10
**Cierre previsto:** 2026-04-17
**Objetivo:** Generar confianza en beta users y mejorar el primer uso. Items de UX y seguridad percibida.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | COPY TOS — explicar modelo de credenciales de brokers | FE/COPY | S | ✅ Hecho (2026-04-10) | feat(trust) a4f6e1c |
| 2 | Cocos OTP help text inline | FE | S | ✅ Hecho (2026-04-10) | feat(trust) a4f6e1c |
| 3 | Error messages accionables (401/403/500/network) | FE | S | ✅ Hecho (2026-04-10) | feat(trust) a4f6e1c |
| 4 | Empty state dashboard sin posiciones | FE | M | ✅ Ya impl. (FTUFlow + ValuePropsScreen cubren el caso) | — |
| 5 | BYMA — acciones STOCK via leading-equity (TDD) | BE | M | ✅ Hecho (2026-04-10) | feat(byma) 0f6d1a2 |

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Items 1–3:** `a4f6e1c` frontend — TOS model de credenciales, OTP help Cocos, errores accionables con `syncErrorMsg()`
**Item 4:** ya cubierto por `FTUFlow` (sin portfolio → CTA conectar broker) + `ValuePropsScreen` (brand new user)
**Item 5:** `0f6d1a2` backend — `get_stock_price_ars()` via btnLideres, TDD verde 5/5

**Velocidad real:** 5/5 ítems completados ✅
