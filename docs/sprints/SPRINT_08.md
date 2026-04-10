# Sprint 8 — "Test Coverage BYMA Extended"

**Inicio:** 2026-04-10
**Cierre real:** 2026-04-10
**Objetivo:** TDD para get_cedear_market_data + verificar cobertura de módulos críticos.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | Tests get_cedear_market_data — 7 TDD (49 total byma_client) | BE TEST | S | ✅ Hecho (2026-04-10) | test(s8-i1) b74d06f |
| 2 | Tests router/portfolio.py | BE TEST | L | ⬜ Aplazado — requiere FastAPI TestClient + fixtures DB | — |
| 3 | ArgentinaDatos 2do fallback BOND | BE | M | 🚫 Bloqueado — /bonos retorna 404 | — |

---

## Daily Log

### 2026-04-10 — Kickoff y cierre

**Item 1:** 7 tests TDD verde para `get_cedear_market_data()`:
- dict completo con price+prev_close+high+low+variation_pct calculada correctamente
- previousSettlementPrice como fallback si vwap=0
- prev_close=None y variation=None cuando previousClosingPrice=0
- ticker inexistente → None
- cache compartido: 2 calls distintos → 1 HTTP
- BYMA falla → None
- sincronización: `_cedear_cache` se actualiza desde `get_cedear_market_data` → `get_cedear_price_ars` usa cache sin HTTP adicional

**Item 2:** Aplazado. Requiere TestClient de FastAPI, fixtures de DB en memoria, y mocks de auth — esfuerzo L, no puede resolverse en una sesión de sprint.

**Item 3:** ArgentinaDatos `/v1/finanzas/bonos` retorna 404 — endpoint no existe. Bloqueado hasta que ArgentinaDatos lo publique.

**Velocidad real:** 1/1 ítems ejecutables completados ✅
