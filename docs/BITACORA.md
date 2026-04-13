# Bitácora BuildFuture

---

## Sesión v0.13.0 — 2026-04-13 (Sprint 11 — STOCK market data live)

### Objetivo
Igualar la experiencia de InstrumentDetail entre CEDEARs y STOCKs (acciones Merval). CEDEARs mostraban variación diaria + máx/mín desde BYMA btnCedears; STOCKs no tenían ningún dato de mercado live.

### Análisis previo
- `get_stock_price_ars()` ya hacía fetch de `btnLideres` pero solo guardaba precio (cache plano `dict[str, float]`)
- El cache `_stock_cache` se repoblaba con cada call a `get_stock_price_ars` pero descartaba prev_close/high/low
- `get_cedear_market_data()` tenía un segundo cache `_cedear_full_cache` con datos extendidos — mismo patrón a replicar

### Cambios backend
- `byma_client.py` — `_fetch_stock_panel()`: función interna que popula `_stock_cache` (precio) y `_stock_full_cache` (extendido: variation_pct, high_ars, low_ars) en un solo fetch a btnLideres. Evita doble HTTP call.
- `byma_client.py` — `get_stock_price_ars()`: refactorizado para delegar a `_fetch_stock_panel()` en lugar de fetch inline.
- `byma_client.py` — `get_stock_market_data(ticker)`: nueva función pública, estructura idéntica a `get_cedear_market_data`. Cache TTL 5 min compartido con `_stock_full_cache`.
- `routers/portfolio.py` — `get_instrument_detail()`: para STOCK, llama `get_stock_market_data()` e incluye `stock_market` en el response.

### Cambios frontend
- `InstrumentDetail.tsx` — tipo `InstrumentData`: agregado `stock_market` con misma forma que `cedear_market`.
- `InstrumentDetail.tsx` — import: `assetLabelWithEmoji` faltaba en el import de `@/lib/assetLabels` (bug preexistente, TypeScript no compilaba).
- `InstrumentDetail.tsx` — bloque STOCK en `PositionMetrics`: muestra "Variación hoy" (verde/rojo) y "Máx / Mín del día" con nota "20 min delay · BYMA Líderes".

### Audit de backlog (sesión 2026-04-13)
Durante la sesión se auditaron 12 ítems del backlog contra el código real. Todos estaban ya implementados pero marcados como pendientes:
- backfill-non-iol correcto (first_seen + pos_snap_index) ✅
- Scheduler actualiza en vez de skipear ✅
- create/update/delete disparan snapshot ✅
- months_to_goal <= 0 → "¡Ya llegaste!" ✅
- Fondo de reserva por emoji ✅
- COPY InstrumentDetail (6 puntos) ✅
- Input horizonte años solo enteros ✅
- CapitalGoals/BudgetEditor res.ok guards ✅
- Toast CASH guardado ✅
- non_iol_offset_usd en modelo + DB migration ✅

### Tests
- Sin tests nuevos (STOCK panel análogo a CEDEAR — misma lógica, mismo cache pattern)
- Pendiente: 5 tests TDD para `get_stock_market_data` análogos a `test_byma_client.py::get_cedear_market_data`

### Estado en Railway/Vercel
- Backend v0.13.0 en Railway
- Frontend v0.13.0 en Vercel
- Tag: v0.13.0

### Decisiones
- `_fetch_stock_panel()` privada: evita duplicación entre `get_stock_price_ars` (usada en yield_updater) y `get_stock_market_data` (usada en instrument_detail). Un solo fetch, dos consumidores.
- Si BYMA está caído: `stock_market: null` → el frontend no renderiza los MetricRows de mercado (no bloquea la pantalla).

---

## Sesión v0.12.1 — 2026-04-13 (Sprint 10 hotfixes — yields correctos en prod)

### Objetivo
Corregir cuatro bugs críticos que impedían ver renta mensual real en producción. Los bugs se descubrieron al verificar el portfolio real de Marcos post-deploy del price store.

### Root causes encontrados

**Bug 1 — BackgroundTasks no importado**
`main.py` usaba `BackgroundTasks` sin importarlo → `collect-prices` crasheaba en startup.
Fix: `from fastapi import FastAPI, BackgroundTasks`

**Bug 2 — diagnose endpoint no cubría LECAPs sanos**
`admin.py` tenía lógica solo para casos de error (maturity parseada pero precio 0, o no parseable). El happy path — LECAP válida con precio y maturity correctas — no calculaba `expected_yield` → `will_update: false` para todas las LECAPs buenas.
Fix: rama `else` que calcula TIR desde precio actual usando `_lecap_tir`. Además, X-prefix (CER letters) usaba `expected_yield = float(p.annual_yield_pct)` en vez de reportarse como no-parseable.

**Bug 3 — backfill_metadata no derivaba maturity de ticker**
`price_collector.py` esperaba respuesta de BYMA fichatecnica para derivar `maturity_date`. BYMA no alcanzable desde Railway → 0 tickers guardados en `instrument_metadata`. Fix: para LETRA, derivar maturity del ticker (S31G6 → ago/2026) via `_parse_lecap_maturity()` sin necesitar HTTP.

**Bug 4 — yield_calculator_v2 usaba value_usd como fallback para ARS**
`compute_position_actual_return`: cuando `value_ars/mep` no disponibles en snapshots viejos, caía a `value_usd` para LETRA/FCI. Problema: `value_usd = value_ars / mep_del_día_de_sync` → las variaciones de MEP entre snapshots generaban yields del 102%-108% para LECAPs. Fix: retornar `(None, None)` cuando no hay datos ARS suficientes — sin dato confiable, no calcular.

**Bug 5 — DEVALUATION_PROXY 50% consumía toda la renta**
`freedom_calculator.py`: proxy de devaluación anual MEP era 50% → cualquier yield ARS < 50% TNA producía renta real USD negativa → se truncaba a 0 → `renta_monthly_usd = $0`. Fix: 15% (crawling peg 2026: ~1%/mes = ~12.7%/año, proxy con buffer 15%). Con esto: S15Y6 30.8% TNA → $4.06/mes, COCOSPPA 19.78% → $8.56/mes.

### Cambios backend
- `main.py`: import BackgroundTasks
- `admin.py`: diagnose endpoint — happy-path para LECAP válida + X-prefix CER
- `price_collector.py`: backfill_metadata — fallback ticker para LETRA sin BYMA
- `yield_calculator_v2.py`: `compute_position_actual_return` — no usar value_usd para ARS instruments
- `freedom_calculator.py`: `DEVALUATION_PROXY` 50%→15%
- `byma_client.py`: `httpx.Timeout(connect=5.0, read=10.0)` en todos los POST — evita hang de price collector cuando BYMA no alcanzable desde Railway IPs

### Proceso — Mejora backlog audit
Detectado que el backlog en memoria quedaba desactualizado entre sesiones. Implementado:
- `UserPromptSubmit` hook: detecta keywords `backlog/pendientes/que falta` → inyecta `[BACKLOG AUDIT REQUERIDO]` context → Claude audita el código antes de reportar
- `/sm` actualizado: paso 1b obligatorio de audit contra código antes de reportar cualquier ítem como pendiente
- Resultado: 9 ítems marcados ✅ que el backlog tenía como pendientes (auditados 2026-04-13)

### Tests
- Sin tests nuevos en esta sesión (bugs fueron diagnosticados manualmente via admin endpoints)

### Estado en Railway/Vercel
- Backend v0.12.1 deployado en Railway
- Frontend sin cambios (v0.12.0 en Vercel)
- Tag: v0.12.1

### Decisiones
- DEVALUATION_PROXY se parametriza cuando haya suficiente historia MEP en la app (hoy hardcodeado 15%)
- byma_client: si BYMA sigue inaccesible desde Railway, evaluar proxy HTTP o scraping indirecto

---

## Sesión v0.12.0 — 2026-04-11 (Sprint 10 — Soberanía de yields + Price Store)

### Objetivo
Eliminar toda dependencia de APIs externas en tiempo real para el cálculo de yields. Construir un Price Store propio que persiste precios de cierre diarios de BYMA y VCP de ArgentinaDatos, y un Yield Calculator v2 que calcula desde datos propios. Corregir el problema conceptual de aplicar TNA ARS a valores USD.

### Análisis previo
- Diagnóstico: `impliedYield` en BYMA siempre es NULL — nunca nos dio yields
- BYMA sí da precios (vwap, prev_close, volume) y metadata estática (TEM, fechaEmision, fechaVencimiento via fichatecnica)
- El sistema actual calculaba yields correctamente pero los descartaba — sin persistencia
- Freedom score y renta mensual usaban TNA ARS × valor USD → unidades incoherentes

### Cambios backend
- `instrument_metadata` (tabla nueva): metadata estática de LECAP/BOND/ON — se guarda una sola vez por ticker via fichatecnica BYMA. TEM + fechaEmision + fechaVencimiento. Nunca cambia, nunca se vuelve a pedir.
- `instrument_prices` (tabla nueva): precios de cierre diarios por ticker. BYMA btnLetras/btnTitPublicos/btnObligNegociables/btnCedears + VCP FCI ArgentinaDatos. Una fila por (ticker, price_date).
- `position_snapshots`: agregadas columnas `value_ars` y `mep` — permite calcular retorno real USD capturando efecto devaluación
- `positions`: agregada columna `yield_currency` ('ARS' o 'USD') — indica denominación del yield almacenado
- `price_collector.py` (servicio nuevo): job de recolección diaria — 5 llamadas HTTP cubre todo el mercado argentino. Idempotente. Corre a las 18:30 post-cierre en el daily_close_job.
- `yield_calculator_v2.py` (servicio nuevo): 4 funciones compute_* — position_actual_return, lecap_tea, bond_yield, fci_yield. Cadena de fallback: retorno observado > precio store > sistema actual (bootstrap).
- `yield_updater.py`: integra v2 como fuente primaria. Sistema actual (BYMA/ArgentinaDatos en runtime) queda como bootstrap para instrumentos nuevos sin historia.
- `freedom_calculator.py`: yield_currency='USD' suma directo; yield_currency='ARS' aplica proxy devaluación 50% antes de sumar a renta_monthly_usd.
- `save_position_snapshots()`: ahora popula value_ars + mep desde Position.current_value_ars + BudgetConfig.fx_rate
- Startup: `_backfill_instrument_metadata()` rellena instrument_metadata para todos los tickers activos LETRA/BOND/ON en el primer deploy

### Cambios frontend
- `InstrumentDetail.tsx`: label "Yield anual" cambia a "Yield anual ARS" o "Yield anual USD" según yield_currency

### Tests
- `test_yield_calculator_v2.py`: 10 tests — sin snapshots, solo value_usd, con value_ars/mep, lecap_tea sin meta, lecap_tea con datos, bond < 7d, bond con historia, fci vcp, sanity fuera de rango

### Estado en Railway/Vercel
- Backend v0.12.0 en Railway
- Frontend v0.12.0 en Vercel (frontend-teal-seven-22.vercel.app)
- Tag: v0.12.0

### Decisiones
- No usar Alembic — proyecto usa _run_migrations() en main.py con SQL incremental
- `_BOND_YTM` tabla estática se mantiene como último fallback hasta que el price store tenga 30 días de historia
- BYMA fichatecnica: dato estático → se guarda una vez y nunca se vuelve a pedir

---

## Sesión v0.11.0 — 2026-04-11 (Sprint 9 — Resiliencia de datos + documentación)

### Objetivo
Hacer resiliente el gráfico de tenencia frente a cambios del portfolio. Reorganizar toda la documentación en docs/ por dominio funcional. Fixes de datos incorrectos en producción.

### Cambios realizados

**Gráfico de tenencia — resiliencia (BUG-1, BUG-2, BUG-3)**
- `_sync_cocos` (integrations.py): crea `PositionSnapshot` en cada sync. De ahora en más cada sync diario de Cocos acumula historia real, alimentando `backfill-non-iol` con valores exactos por fecha en lugar de aproximaciones planas.
- `_save_portfolio_snapshot` (scheduler.py): cambiado de skip-si-existe a **upsert**. El snapshot de hoy refleja el estado al cierre del día, no el estado de la primera vez que se generó. Cambios post-17:30 ahora se incluyen.
- `_snapshot_after_manual_change()` (positions.py): nuevo helper llamado en create/update/delete de posición manual. Crea `PositionSnapshot` + actualiza `PortfolioSnapshot` de hoy inmediatamente. La posición aparece en el gráfico sin esperar al scheduler.
- `repair-user` (admin.py): unificado en flujo de 5 pasos que incluye IOL + Binance 30d + backfill non-IOL con `first_seen = MIN(PositionSnapshot.snapshot_date)`.
- `backfill-non-iol` (admin.py): fix crítico — ya no suma el valor actual retroactivamente a todo el histórico. Usa `PositionSnapshot` exactos por fecha y `first_seen` como límite de inicio por posición.

**Datos incorrectos**
- `sync_binance` (integrations.py): rollback en todos los `except` (BinanceAuthError + Exception genérica).
- `COCOSPPA` → `("Cocos Pesos Plus", "rentaMixta")` en `_IOL_FCI_TICKER_MAP`. Yield calculado desde la categoría correcta en lugar de `mercadoDinero`.
- Binance `_COINGECKO_ID`: +35 tokens (ETHW, SHIB, ARB, OP, INJ, SUI, APT, FTM, etc.).
- `BinanceClient`: fix kwarg `secret` (no `secret_key`), import `Decimal` en admin.py.

**Documentación — reorganización completa**
- Nuevo template estándar: Estado actual / Invariantes / Flujo técnico / Bugs / Cambios / Decisiones
- Docs nuevos en `docs/`: INTEGRACIONES.md, POSICIONES.md, YIELDS.md, FREEDOM_SCORE.md, SNAPSHOTS.md, SEGURIDAD.md, MULTIUSER.md
- 14 archivos `feedback_*.md` de memoria consolidados en `feedback_operativo.md`
- Archivos de memoria de proyecto reducidos a punteros que apuntan a los docs del repo
- MEMORY.md actualizado con nueva estructura

**Frontend**
- Toasts con `sonner` en CapitalGoals (crear/editar/eliminar meta) y IntegrationCard (sync/disconnect).

### Historial Marcos (usuario principal) verificado
- `repair-user` purga 31 snapshots, reconstruye con IOL + Binance 30d + backfill Cocos/Manual
- Valores correctos: IOL desde 30-mar, Cocos desde 3-abr ($4,471), rescate 10-abr ($2,447), CASH_USD desde 6-abr
- BUG-2 resuelto: posiciones manuales ahora aparecen en el gráfico inmediatamente al crearlas

### Bugs encontrados y resueltos
- `first_seen = Position.snapshot_date` era incorrecto (refleja ÚLTIMO sync, no primero) → fix: `MIN(PositionSnapshot.snapshot_date)`
- `Decimal + float` en backfill loop → fix: `Decimal(str(round(offset, 2)))`
- `BinanceClient.__init__()` recibía `secret_key` en lugar de `secret` → fix
- `NameError: Decimal` en admin.py → import a nivel módulo

### Decisiones técnicas
- Scheduler hace upsert (no skip) en lugar de añadir campo `locked` — más simple, mismo resultado
- `_snapshot_after_manual_change()` es un helper centralizado en lugar de lógica duplicada en cada endpoint
- Template de docs vivos en repo; memoria Claude = punteros → reduce duplicación y conflictos entre sesiones

### Estado
Backend v0.11.0 en Railway. Frontend v0.11.0 en Vercel.

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
