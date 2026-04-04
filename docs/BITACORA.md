# Bitácora BuildFuture

---

## Sesión v0.10.1 — 2026-04-03/04 (ramas: fix/cedear-iol-historical-prices, cherry-picks)

### Objetivo
Soporte urgente cliente Matías Morón: snapshots de portfolio mostraban millones de dólares en lugar del valor real (~$135K). Investigación profunda, fix, deploy y documentación de learnings para no repetir.

### Root cause (3 bugs encadenados)

**Bug A — Unit mismatch BOND/ON ppc (per 100 VN nominal)**
IOL devuelve `ppc` en ARS por 100 VN para BOND/ON (igual que LETRA, convención BYMA). El código solo dividía `/100` para LETRA → `ppc_usd` de AL30 era 61.74 en vez de 0.61 (100x inflado). No afecta `current_price_usd` (calculado de `valorizado/cantidad/mep`).

**Bug B — Yahoo Finance devuelve precio NYSE, no precio CEDEAR ARS/MEP**
`yfinance` descarga el precio de la acción en NYSE (AMZN=$210 USD). El CEDEAR vale ARS/MEP (~$1.52 USD). Ratio = 138x. Sin corrección, 13 CEDEARs × cantidades grandes = portfolio aparente de $3.7M → $5.7M.

**Bug C — NDT25/NDT26/NDT27 clasificados como STOCK por IOL**
Bonos duales soberanos ignorados en reconstrucción histórica (solo procesa BOND/ON/CEDEAR/FCI/LETRA).

### Fix implementado (PR #29 — mergeado 2026-04-03)

- `iol_client.py`: extender `/100` a `("LETRA", "BOND", "ON")`. Agregar overrides NDT25/26/27 → BOND.
- `historical_prices.py`: `get_iol_prices_cached()` generalizado para BOND/ON (`divide_by_100=True`) y CEDEAR/ETF (`divide_by_100=False`). UPSERT en `price_history` sobreescribe Yahoo con IOL. Cache lookup ignora filas `source=YAHOO` para CEDEARs.
- `historical_reconstructor.py`: pre-fetch IOL-first para BOND/ON/CEDEAR/ETF. Yahoo solo como fallback con corrección `equiv = round(yahoo_price / current_price_usd)`.
- `admin.py`: 3 nuevos endpoints de soporte: `POST /admin/support/repair-user`, `GET /admin/support/snapshot-health`, `DELETE /admin/cache/price-source-purge`.
- `docs/SUPPORT_PLAYBOOK_HISTORICOS.md`: playbook de soporte completo.

### Cherry-picks post-PR (2026-04-04)
- `fix(iol): trackea saldo USD disponible en IOL (CASH_IOL_USD)` — multi-cuenta USD en IOL, `result["usd"] += disponible`.
- `feat(recs): yield ranges dinámicos` — expert_committee.py con rangos desde riesgo país + yfinance percentiles.

### Hallazgo crítico de deploy: Railway no redesplegó tras PR #29
Railway no redesplegó automáticamente porque los commits intermedios (playbook, cherry-picks) no tocaban `backend/`. Cada auto-sync en Railway con código viejo generaba snapshots inflados nuevamente. Fix: bump version 0.10.1 en `main.py` para forzar trigger Railway.

### Usuarios afectados y reparación

| Usuario | Problema | Acción |
|---------|----------|--------|
| Matías Morón (mgmatias008) | 1 snapshot inflado $5.7M, NDT25 como STOCK | Purge Yahoo cache, re-sync local con código nuevo |
| Cristian Coloca (coloca.cristian) | SUPV y MELI Yahoo sin equiv correction | Purge SUPV/MELI Yahoo cache, re-sync local |
| Marcos González (dev) | SPY/QQQ con Yahoo — ratios pequeños, sin inflación | Sin acción requerida |

### Lección aprendida
El problema puede re-generarse mientras Railway tenga código viejo. El auto-sync cada 4h regenera snapshots inflados. Nunca confiar en que Railway se autodesplegó — verificar siempre con un endpoint nuevo (404 = deploy pendiente).

---

## Sesión v0.11.0 — 2026-04-02 (rama: feat/capital-goals-gamification)

### Objetivo
Completar el journey de metas de capital: gamificación del ahorro mensual (DCA, interés compuesto, racha), ABM de objetivos de capital (casa/auto/viaje), proyección a largo plazo con visualización educativa, y separación conceptual de recomendaciones por propósito (renta vs capital).

### Cambios backend

**Nuevos endpoints:**
- `GET /portfolio/goal` — retorna `monthly_savings_usd` + `target_annual_return_pct` del FreedomGoal activo
- `PUT /portfolio/goal` — crea o actualiza FreedomGoal (upsert)
- `GET /portfolio/projection` — curva de proyección a 10 años: `with_savings_usd` vs `without_savings_usd`, puntos anuales con yield real del portfolio capeado a 6–15% USD
- `GET /portfolio/capital-goals` — lista capital goals con progreso calculado: `progress_pct`, `months_to_goal` (iteración numérica), `portfolio_usd`, `monthly_savings_usd`
- `POST /portfolio/capital-goals` — crea meta
- `PUT /portfolio/capital-goals/{id}` — edita meta
- `DELETE /portfolio/capital-goals/{id}` — borra meta

**Modelo nuevo:**
- `CapitalGoal`: `id`, `user_id`, `name`, `emoji`, `target_usd`, `target_years`, `created_at`
- Migración automática en startup: `CREATE TABLE IF NOT EXISTS capital_goals` + índice `idx_capital_goals_user`

**Cambios a endpoints existentes:**
- `GET /portfolio/gamification`: agrega campo `current_month_invested` (bool — si el mes actual tiene fila en `investment_months`)
- `GET /portfolio/projection`: usa `FreedomGoal.target_annual_return_pct` si existe, sino yield calculado del portfolio **capeado a máx 15% USD** (evita que rendimiento nominal ARS de LECAPs infle la proyección)
- `GET /portfolio/capital-goals`: cap de yield en 6–15% también en cálculo de `months_to_goal`

**Expert committee:**
- Campo `job: str` en dataclass `Instrument`: `"renta"` | `"capital"` | `"ambos"`
- Todo el UNIVERSE taggeado: renta (IOLCAMA, S15Y6, S31G6, YCA6O), capital (QQQ, SPY, GGAL, XLE, VIST), ambos (AL30, GD30)
- `"job"` incluido en el dict de respuesta de recomendaciones

**Fix:**
- `fetchPortfolioHistory` retorna `null` en error en lugar de lanzar excepción (evitaba crash en `/portfolio` page)

### Cambios frontend

**Nuevos componentes:**
- `components/goals/ProjectionCard.tsx` — gráfico Recharts de dos curvas (con/sin aportes), selector horizonte 1/3/5/10a, líneas de referencia horizontales por capital goal visible en rango, bottom sheet educativo (3 secciones: rendimiento, DCA, interés compuesto) con datos reales del usuario
- `components/goals/CapitalGoals.tsx` — ABM completo: list vacía con CTA, GoalForm (emoji picker, nombre, objetivo USD, horizonte años), GoalCard con barra de progreso, tiempo estimado, confirmación borrado con auto-cancel 3s
- `components/goals/GoalCompliance.tsx` — card por meta con estado tipado (achieved/on_track/delayed/no_savings), fecha proyectada ("Llegás en diciembre 2028"), delay en meses, barra de progreso coloreada, empty state con CTA a /goals (solo en dashboard via `showEmptyState` prop), link a /settings cuando falta presupuesto
- `components/goals/GoalEditor.tsx` — form colapsable para editar `monthly_savings_usd` y `target_annual_return_pct` (4 opciones de perfil de yield). Construido pero **removido de la UI** — el sistema usa el presupuesto directamente como fuente de verdad (mismo comportamiento que el dashboard). Backend endpoints se mantienen para uso futuro.

**Componentes modificados:**
- `components/goals/InvestmentStreak.tsx` — card de estado del mes actual (✅/⏳) al tope, mes actual resaltado en el calendario con `ring-1 ring-slate-400`
- `components/recommendations/RecommendationList.tsx` — split en dos secciones: 💰 Renta (job=renta) y 📈 Capital (job=capital/ambos). Cards de capital muestran `+X%/año` en azul en lugar de `+$/mes` en verde. Modal diferencia "Apreciación estimada X% USD/año"
- `app/goals/page.tsx` — integra `GoalCompliance` (silencioso cuando vacío, CapitalGoals lo maneja) + `CapitalGoals` + baja `budgetSavingsUSD` del server component al `CapitalGoals` client component
- `app/dashboard/page.tsx` — agrega `ProjectionCard`, `GoalCompliance` (con `showEmptyState`), pasa `currentMonthInvested` a `InvestmentStreak`

**Fixes UX:**
- Empty state `GoalCompliance` en dashboard cuando no hay metas: card dashed con CTA
- `ProjectionCard` null state cuando el endpoint falla
- Delete en `CapitalGoals`: timer 3s auto-cancel en lugar de `onBlur` (frágil en mobile)
- Barra de progreso en `CapitalGoals`: ancho mínimo 2% para que 0% sea visible
- Texto "Sin presupuesto" → link a /settings

### Decisiones técnicas

**¿Por qué cap 15% en projection?**
El yield calculado del portfolio mezcla rendimiento nominal ARS (LECAPs ~50-60%) con activos USD. La proyección es en USD, así que un LECAP no contribuye al 50% sino a ~0-5% real en USD. El cap asegura que la proyección sea educativamente honesta.

**¿Por qué no mostrar GoalEditor en UI?**
El usuario tiene su presupuesto configurado con ingreso + categorías. `savings_monthly_ars / fx_rate` ya es la fuente de verdad de "cuánto invertís por mes". Pedir otro input sería redundante y confuso. El `FreedomGoal.target_annual_return_pct` se puede setear en el futuro desde el perfil de riesgo.

**Próxima iteración planeada: Bucket split renta/capital**
Separar el portfolio en dos carriles en toda la app:
- Bucket 🔵 Renta: LETRA, FCI, BOND cupón → alimenta freedom bar y monthly return
- Bucket 🟢 Capital: CEDEAR, ETF → alimenta ProjectionCard y CapitalGoals
- DashboardHero con dos métricas: `$X/mes generados` (renta) + `$Y acumulado` (capital)
- Cálculos más precisos: yield de renta = ARS→USD real; yield de capital = USD histórico

Clasificación por `asset_type`:
| asset_type | bucket |
|-----------|--------|
| LETRA, FCI | renta |
| BOND | ambos (cupón → renta, valor → capital) |
| CEDEAR, ETF | capital |
| CASH | neutral |
| CRYPTO | capital |

### Estado al cierre
- Backend: corriendo local en puerto 8008 con todos los endpoints nuevos ✅
- Frontend: corriendo local en puerto 3001 apuntando a 8008 ✅
- Rama: `feat/capital-goals-gamification` — sin commit aún, cambios unstaged
- Pendiente: commit + versionar + deploy a producción

---

## Sesión v0.10.0 — 2026-04-01

### Objetivo
Ingreso manual de posiciones (Fase 1 + 2): CRYPTO vía CoinGecko, FCI vía ArgentinaDatos (incluye Cocos Capital), ETFs/acciones vía Yahoo Finance. Correcciones al detalle de instrumento por tipo. Arreglo de producción: detalle de instrumento crasheaba en Vercel por cambio en Next.js 16.

### Cambios realizados

**Ingreso manual de posiciones (WIP — local)**

*Servicios nuevos (backend):*
- `crypto_prices.py`: búsqueda CoinGecko (`/search`), precio live (`/simple/price`), TNA interpolada de variación 30 días (`/coins/{id}/market_chart`)
- `fci_prices.py`: búsqueda en ArgentinaDatos por nombre (todas las categorías), VCP live, TNA calculada de VCP hace 30 días vs hoy. Cubre todos los FCI argentinos incluyendo Cocos Ahorro y Cocos Dólares Plus
- `external_prices.py`: validación y precio live vía Yahoo Finance (`/v8/finance/chart/{ticker}`), TNA interpolada 30 días. Soporta SPY, QQQ, cualquier ETF/acción listada

*Modelo:*
- `Position`: dos nuevos campos — `external_id` (CoinGecko ID, nombre fondo ArgentinaDatos, o ticker Yahoo) y `fci_categoria` (categoría para filtrar en ArgentinaDatos)
- Migración SQLite local aplicada con ALTER TABLE. En PostgreSQL (Railway) se aplica automáticamente con `create_all`

*Router `positions.py` (nuevo):*
- `GET /positions/search/crypto?q=` → CoinGecko
- `GET /positions/search/fci?q=` → ArgentinaDatos (filter client-side)
- `GET /positions/search/etf?ticker=` → Yahoo Finance validate
- `POST /positions/manual` → crea posición, obtiene precio live y yield 30d automáticamente
- `PATCH /positions/manual/{id}` → actualiza cantidad / precio / yield
- `DELETE /positions/manual/{id}` → soft delete
- `POST /positions/manual/{id}/refresh-price` → fuerza actualización precio

*Scheduler:*
- `_refresh_manual_prices()` corre antes del snapshot diario (17:30 ART). Actualiza `current_price_usd` y `annual_yield_pct` para todas las posiciones manuales activas según su fuente (CRYPTO/FCI/ETF)

*Frontend:*
- `/portfolio/add-manual`: formulario 3 pasos (tipo → buscar → datos). Dinámico según tipo: FCI pide cuotapartes + VCP compra + MEP; CRYPTO/ETF pide precio USD; OTRO pide yield manual
- `AddManualPosition.tsx`: live search mientras escribís, muestra VCP/precio antes de confirmar
- `PortfolioClient.tsx`: card "coming soon" reemplazada por botón real que navega a `/portfolio/add-manual`
- `portfolio/page.tsx`: botón "Agregar manual" en el header

**Detalle de instrumento — correcciones**

- `InstrumentDetail.tsx` ahora renderiza métricas distintas por tipo de activo:
  - **FCI**: cuotapartes, VCP actual en ARS, VCP de compra en ARS, tenencia valorizada en ARS + equivalente USD, costo base, ganancia neta, renta mensual
  - **CEDEAR**: PPC en ARS con derivación explícita `ppc_ars / MEP_compra = USD x.xx`, costo base, precio actual, tenencia, ganancia neta, renta mensual
  - **LETRA**: PPC per 100 nominales + precio unitario calculado
  - **CRYPTO/ETF**: precio de compra en USD directo
- Fila "Ganancia neta" agregada en la tabla (verde/rojo) con monto + % + equivalente en moneda opuesta
- Label P&L del héroe contextual: "vs VCP compra" (FCI), "vs PPC (ARS/MEP)" (CEDEAR), "vs precio compra" (resto)

**Fix producción — detalle instrumento crasheaba en Vercel**

- Causa: Next.js 15+ requiere `await params` en dynamic routes (`params` es una `Promise`)
- `/app/portfolio/[ticker]/page.tsx`: `params: Promise<{ ticker: string }>` + `const { ticker } = await params`
- Sin este fix la página devolvía 404 sin mensaje de error

### Bugs encontrados y resueltos
- Railway no deployó el commit `811b183` automáticamente (sin repo trigger configurado) → backend seguía en v0.8.0 sin el endpoint de instrumento → `fetchInstrumentDetail` devolvía null → `notFound()` en Vercel
- Next.js 16 rompe silenciosamente si no se awaita `params` en server components de dynamic routes
- Rendimiento con `pnl_usd` mostraba barras en cero porque los datos iniciales (cacheados del SSR) no tenían el campo — revertido a `delta_usd` (día anterior) para el gráfico; P&L vs PPC queda en la página de detalle de cada instrumento

### Estado
- Backend v0.10.0 (WIP manual) — solo local, no deployado a prod aún
- Frontend `b6c3cd1` deployado en Vercel — fixes de detalle instrumento en prod
- Railway en `811b183` — endpoint instrumento disponible en prod

---

## Sesión v0.9.0 — 2026-03-31

### Objetivo
Corregir la lógica de rendimiento: mostrar P&L vs PPC (costo base real) en lugar de delta día anterior. Agregar detalle de instrumento al tocar cualquier posición del portafolio.

### Cambios realizados

**Rendimiento — pnl_usd en history**
- `GET /portfolio/history`: calcula `total_cost_basis` como suma de `cost_basis_usd` de posiciones activas (fuera del try de snapshot live para que siempre esté disponible)
- Cada punto histórico incluye `pnl_usd = total_usd − total_cost_basis` y `pnl_pct`
- Revertido en el gráfico: `displayDelta` (día anterior) es más estable visualmente porque `pnl_usd` no estaba en datos cacheados del SSR → barras en 0. El campo `pnl_usd` se usa en el detalle individual de instrumento

**Detalle de instrumento**
- `GET /portfolio/instrument/{ticker}`: retorna datos completos de la posición + contexto estático por tipo de activo (descripción, nota de moneda, liquidez)
- `fetchInstrumentDetail(ticker)` en `api-server.ts`
- `PortfolioTabs`: filas de posiciones son botones con `ChevronRight`; navegan a `/portfolio/{ticker}`
- `/app/portfolio/[ticker]/page.tsx`: server component con fetch + back link
- `InstrumentDetail.tsx`: héroe P&L, tabla métricas, contexto activo, MEP, fecha actualización

**Info modales**
- Tenencia: explicación simplificada + nota dual currency
- Rendimiento: mantiene explicación de delta día anterior (revertido desde P&L vs PPC)

### Estado
Backend v0.9.0 en Railway. Frontend en Vercel.

---

## Sesión v0.8.0 — 2026-04-01

### Objetivo
Portfolio page: switch unificado que afecta gráfico + listado de activos simultáneamente; modales informativos de cómo se calcula cada vista. Fix de recomendaciones duplicadas entre conservador y moderado. Fix crítico de FTU bloqueado cuando backend no tiene el endpoint `/profile/` aún. Perfil de usuario en `/settings`.

### Cambios realizados

**Portfolio — switch unificado + modales info**
- `PortfolioClient.tsx` (nuevo): client wrapper `mode = "composicion" | "rendimientos"`, controla `PerformanceChart` (chartMode) y `PortfolioTabs` (activeTab)
- `PerformanceChart`: switch interno eliminado; recibe `chartMode` como prop
- `PortfolioTabs`: tab bar interno eliminado; recibe `activeTab` como prop
- Modal ⓘ inline por modo activo: tenencia (snapshot 17:30, CEDEARs ARS÷MEP, LECAPs/FCI nominal×precio÷MEP) / rendimiento (delta vs día anterior)
- Card "Próximamente: ingreso manual" al final de portfolio

**Recomendaciones — fix conservador duplica moderado**
- `IOLCAMA` agregado a `UNIVERSE`: FCI money market, TNA 64%, liquidez diaria, `min_capital_ars=1_000`
- Conservador slot 1: `pick(FCI)` con fallback a `LETRA` — ya no toma la misma LECAP que moderado
- `_build_rationale`: case para `FCI` con texto específico de money market

**FTU — fix bloqueado en production**
- `fetchProfile()`: retorna `{ risk_profile, available }` — status 404 → `available: false`
- `dashboard/page.tsx`: solo bloquea por risk profile si `profile.available === true`
- `FTUFlow.tsx`: check `res.ok` con error visible; `window.location.href = "/dashboard"` en éxito

**Perfil de usuario en `/settings`**
- `ProfileSection.tsx`: nombre (Supabase metadata), perfil de riesgo (con animación al cambiar, tilde en opción guardada, localStorage fallback), cambiar contraseña, cerrar sesión
- Perfil de riesgo: 3 estados visuales — guardado (verde + CheckCircle2), pendiente (azul), default
- Botón guardar animado: slide-in solo cuando `selectedRisk !== riskProfile`

### Bugs encontrados y resueltos
- Railway sin auto-deploy → backend en v0.6.1 sin `/profile/` → FTU bloqueado sin error → fix: `fetchProfile` distingue 404 de error real
- TypeScript: `profile.available` no existía en el tipo del catch → `catch(() => ({ risk_profile: null, available: false }))`

### Estado
Frontend v0.8.0 en Vercel. Backend v0.8.0 en Railway.

---

## Sesión v0.7.0 — 2026-03-31

### Objetivo
Deploy en producción real con un usuario real. Migración a multi-usuario con Supabase Auth. Login completo + FTU flow.

### Cambios realizados

**Deploy**
- Backend en Railway (`api-production-7ddd6.up.railway.app`) con `railway.toml` + nixpacks
- Frontend en Vercel (`frontend-teal-seven-22.vercel.app`)
- Variables de entorno: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `DATABASE_URL` (PostgreSQL Supabase)

**Auth multi-usuario**
- `auth.py`: ES256 JWT verificado vía JWKS de Supabase. Dev fallback a `SEED_USER_ID`
- `load_dotenv()` en `database.py` y `auth.py` — sin esto las env vars no cargaban en Railway
- `DEV_USER_ID` corregido a UUID válido (36 chars, antes 46 → `StringDataRightTruncation`)
- Todos los endpoints: `user_id = Depends(get_current_user)`

**Login completo**
- 4 modos: `login | register | forgot | reset`
- `PASSWORD_RECOVERY` event Supabase → switch a modo reset
- Reset: `supabase.auth.updateUser({ password })`
- BottomNav oculto en `/login`

**FTU flow**
- Dashboard gateado: hasBudget + hasPortfolio + hasRiskProfile
- `FTUFlow.tsx`: 3 cards con progress dots, risk profile inline
- `UserProfile` model + `GET /profile/` + `PUT /profile/`

**Historial real de tenencia**
- Snapshots reconstruidos con precios reales: Yahoo Finance para CEDEARs, TNA accrual para LECAPs
- `PortfolioSnapshot`: snapshot diario al cierre, backup automático 30 días
