# Sprint 12 — "Devaluación Dinámica + Currency Toggle + Home Renta Fix"

**Inicio:** 2026-04-13
**Cierre real:** 2026-04-13
**Versión:** v0.14.0
**Objetivo:** Reemplazar DEVALUATION_PROXY hardcodeado con estimación real de mercado (paridad LECAP/ON), fix renta home vs portfolio, ProjectionCard currency toggle ARS/USD.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | `devaluation.py` — servicio con jerarquía 4 fuentes (ROFEX→paridad LECAP/ON→MEP trend→fallback 20%) | BE | M | ✅ Hecho | 2e9f8a4 |
| 2 | `split_portfolio_buckets(positions, db=None)` usa `get_expected_devaluation()` | BE | S | ✅ Hecho | 2e9f8a4 |
| 3 | `GET /portfolio/` expone `expected_devaluation_pct` en summary | BE | XS | ✅ Hecho | 2e9f8a4 |
| 4 | `PortfolioHeader` consume `expectedDevaluationPct` del servidor (no hardcodeado) | FE | XS | ✅ Hecho | 3c67b7d |
| 5 | Fix home: `portfolioTotal` usa `portfolio.summary.total_usd` si freedom-score falla | FE | XS | ✅ Hecho | f48383f |
| 6 | Fix desglose renta fija: aplica DEVALUATION_PROXY igual que servidor | FE | XS | ✅ Hecho | f48383f |
| 7 | `ProjectionCard` currency toggle — fmtK respeta ARS/USD via useCurrency() + mep prop | FE | S | ✅ Hecho | f48383f |
| 8 | Spike fuentes externas — POC todas las APIs, doc en SPIKE_DATA_SOURCES_2026_04.md | PM | M | ✅ Hecho | — |
| 9 | Sprints 9/10/11/12 documentados | PM | S | ✅ Hecho | — |

---

## Daily Log

### 2026-04-13 AM — Bugs renta home + rendimiento anualizado

**Bug 1 — Renta en home:**
- `PortfolioHeader.tsx` calculaba `monthlyRentaFija` client-side con TNA ARS cruda (~68%) aplicada a valor USD → sobreestimaba la renta ~50% vs el servidor
- Dashboard: si `fetchFreedomScore()` falla → `portfolioTotal = 0` (mostrado como $0 en header)
- Fix: server-side `expected_devaluation_pct` en summary + fallback `portfolio.summary.total_usd`

**Bug 2 — Rendimiento anualizado ARS = USD:**
- `ProjectionCard` usaba `fmtK()` (USD-only) para todos los montos del gráfico y acordeón
- Toggle ARS/USD no tenía efecto en los números proyectados
- Fix: `makeFmtK(currency, mep)` factory, `useCurrency()` en componente, `mep` prop desde dashboard

### 2026-04-13 PM — Devaluación dinámica

**Motivación:** El analista financiero identificó que 15% es demasiado conservador. Paridad LECAP/ON (Interest Rate Parity) da 19.4% con datos de hoy (TEA LECAP ~30% / TIR ON USD ~9%).

**devaluation.py — jerarquía de fuentes:**
1. **ROFEX futuros** — `(precio_futuro/mep_spot)^(365/dias) - 1`. API Matba: 404. Pendiente endpoint válido.
2. **Paridad LECAP/ON** ← **fuente activa (19.4%)** — `(1+TEA_LECAP)/(1+TIR_ON_USD)-1`. TEA desde `get_lecap_tna()` ya implementado; TIR ON desde tabla fallback `_ON_USD_TIR_TABLE` (BYMA no expone impliedYield).
3. **MEP trend 60 días** — desde `MepHistory` DB. Requiere `db` param, usado en callers con sesión activa.
4. **Fallback 20%** — reemplaza el 15% anterior, más conservador y realista.

**Impacto numérico:**
- Con 15%: LECAP 38% TNA → real USD ~20%
- Con 19.4%: LECAP 38% TNA → real USD ~15.6%
- Diferencia: -4pp en la renta mensual USD mostrada (más honesto con el riesgo cambiario)

**Cache:** 4 horas. Sanity bounds [8%, 80%].

---

## Decisiones de arquitectura

- **`split_portfolio_buckets(db=None)`** — backward compatible. Sin db: usa fuentes 1+2 (HTTP). Con db: habilita fuente 3 (MEP trend). `calculate_freedom_score` usa `db=None` — ok porque fuentes 1 y 2 tienen sus propios caches.
- **`expected_devaluation_pct` en summary** — el frontend no debería hardcodear el proxy. El servidor lo calcula y lo expone para que el frontend pueda replicar la misma lógica en el desglose.
- **`makeFmtK` factory pattern** — el formatter de recharts (YAxis.tickFormatter) necesita una función pura. Se crea la factory dentro del componente capturando currency+mep del closure.

---

## Velocidad real

9/9 ítems completados ✅

---

## Estado del sistema al cierre del sprint

- **Backend v0.14.0** deployado en Railway
- **Frontend** deployado en Vercel (auto-deploy desde master)
- **Devaluación estimada hoy:** 19.4% anual (paridad LECAP/ON)
- **MEP live:** ~$1404 ARS/USD
