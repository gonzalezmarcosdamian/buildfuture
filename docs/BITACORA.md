# Bitácora BuildFuture

---

## Sesión v0.8.0 — 2026-04-01

### Objetivo
Portfolio page: switch unificado que afecta gráfico + listado de activos simultáneamente; modales informativos de cómo se calcula cada vista. Fix de recomendaciones duplicadas entre conservador y moderado. Fix crítico de FTU bloqueado cuando backend no tiene el endpoint `/profile/` aún.

### Cambios realizados

**Portfolio — switch unificado + modales info**
- `PortfolioClient.tsx` (nuevo): client wrapper que maneja `mode = "composicion" | "rendimientos"` y se lo pasa como prop a `PerformanceChart` (chartMode) y a `PortfolioTabs` (activeTab)
- `PerformanceChart`: eliminado switch interno; recibe `chartMode` como prop externa; conserva chips de período
- `PortfolioTabs`: eliminado tab bar interno; recibe `activeTab` como prop externa
- `PortfolioClient`: ícono ⓘ abre un panel inline con explicación de cálculo según el modo activo:
  - Tenencia: snapshot diario 17:30 ART, CEDEARs ARS÷MEP, LECAPs/FCI nominal×precio÷MEP
  - Rendimiento: delta vs día anterior, TNA÷365 para renta fija, precio de mercado para CEDEARs
- Card "Próximamente: ingreso manual de tenencias" al final de la página
- `portfolio/page.tsx` simplificado: usa `PortfolioClient` en lugar de instanciar los dos componentes por separado

**Recomendaciones — fix conservador duplica moderado**
- `IOLCAMA` agregado a `UNIVERSE`: FCI money market, TNA 64%, liquidez diaria, riesgo bajo, `min_capital_ars=1000`
- `conservador` slot 1: `pick(FCI)` con fallback a `LETRA` — ya no toma la misma LECAP que moderado
- `_build_rationale`: case para `FCI` con texto específico de money market

**FTU — fix bloqueado en production**
- Problema raíz: backend en producción era v0.6.1 (Railway sin redeploy); `/profile/` retornaba 404 → FTU bloqueado en "Confirmar perfil" sin error visible
- `fetchProfile()` en `api-server.ts`: ahora retorna `{ risk_profile, available }` — status 404 → `available: false`
- `dashboard/page.tsx`: solo bloquea por risk profile si `profile.available === true`; si el backend es viejo, el dashboard se muestra igual
- `FTUFlow.tsx`: check `res.ok` con mensaje de error visible; `window.location.href = "/dashboard"` (antes `router.refresh()`)

### Bugs encontrados y resueltos
- Railway no auto-deploying: el backend se quedó en v0.6.1 porque Railway no tenía auto-deploy desde GitHub habilitado → solución: redeploy manual desde dashboard Railway
- Token Railway expirado (947ef2f7 y 165f29bd): ambos fallan con "Not Authorized" en la GraphQL API → redeploy vía dashboard web
- TypeScript error: `profile.available` no existía en el tipo del catch → corregido a `catch(() => ({ risk_profile: null, available: false }))`

### Estado actual
Frontend v0.8.0 en Vercel. Backend pendiente redeploy Railway (v0.6.1 → v0.8.0).

---

## Sesión v0.7.0 — 2026-03-31

### Objetivo
Llevar la app a producción real con un usuario real. Migrar a multi-usuario con Supabase Auth, deployar backend en Railway y frontend en Vercel, reconstituir historial real de tenencia, y agregar login completo + flujo de onboarding FTU (First-Time User).

### Cambios realizados

**Infraestructura — deploy en producción**
- Backend deployado en Railway con `railway.toml` + `nixpacks`. URL: `api-production-7ddd6.up.railway.app`
- Frontend deployado en Vercel. URL: `frontend-teal-seven-22.vercel.app`
- Variables de entorno configuradas en Railway y Vercel (Supabase URL/key, DATABASE_URL PostgreSQL)

**Auth multi-usuario**
- `auth.py`: ES256 JWT verificado vía JWKS endpoint de Supabase. Dev fallback a `SEED_USER_ID` cuando no hay `SUPABASE_URL`
- `database.py` y `auth.py`: agregado `load_dotenv()` — sin esto, las variables de entorno no cargaban en Railway ni en local fuera del Makefile
- `DEV_USER_ID` cambiado a UUID válido (bug: `String(36)` column con value de 46 chars → `StringDataRightTruncation`)
- Todos los endpoints ahora son multi-usuario: `user_id = Depends(get_current_user)` en todos los routers

**Frontend — sesión correcta**
- Cambio crítico: `createClient` (@supabase/supabase-js, localStorage) → `createBrowserClient` (@supabase/ssr, cookies). Sin esto, `proxy.ts` en el servidor no podía leer la sesión → loop de redirect infinito
- Bearer token agregado en todos los componentes client (`BudgetEditor`, `IntegrationCard`, `ConnectIOLForm`, `ConnectNexoForm`, `PerformanceChart`, `RecommendationList`, `RecommendationCarousel`) — todos llaman `supabase.auth.getSession()` antes de cada fetch
- `NEXT_PUBLIC_API_URL` usado en todos los componentes (eliminados hardcodes a localhost:8007)
- `proxy.ts`: renombrado de `middleware.ts`, export `proxy` (Next.js 16 deprecó el nombre `middleware`)

**Login page completo**
- Tabs: Ingresar / Registrarse
- Flujo "Olvidaste tu contraseña": envía email vía `supabase.auth.resetPasswordForEmail`, redirige a `/login`
- Flujo "Cambiar contraseña": detecta evento `PASSWORD_RECOVERY` en `onAuthStateChange`, muestra form con nueva contraseña + confirmación, llama `supabase.auth.updateUser({ password })`
- BottomNav: retorna `null` cuando `pathname === "/login"`

**FTU flow (First-Time User)**
- `UserProfile` model + tabla `user_profiles` con `risk_profile` (conservative/moderate/aggressive)
- `GET /profile/` y `PUT /profile/` endpoints
- Dashboard server component: verifica `hasBudget`, `hasPortfolio`, `hasRiskProfile` — si falta alguno, muestra `FTUFlow` en lugar del dashboard
- `FTUFlow` client component: barra de progreso + card por cada paso faltante, selector inline de perfil de riesgo con guardado via `PUT /profile/`, `router.refresh()` al completar

**Historial real de tenencia**
- Eliminados 5 snapshots mock del usuario real (`f94d61c1-1b59-438c-bc79-a66139028c94`)
- Posiciones reales: IOLCAMA (FCI TNA 36%), QQQ (CEDEAR), S15Y6 (LETRA TNA 36%), S31G6 (LETRA TNA 41%)
- Precios QQQ: Yahoo Finance (Mar30=558.28, Mar31=577.18). MEP: 1430.8 ambos días
- LECAPs y IOLCAMA: acumulación diaria con `valor × (1 + TNA/365)`
- Snapshots: Mar 30 = USD 696.77 | Mar 31 = USD 699.40 | Abr 1 = USD 699.94

### Bugs encontrados y resueltos
- `StringDataRightTruncation`: `SEED_USER_ID` de 46 chars en columna `String(36)` → UUID válido de 36 chars
- `anthropic` module not found en Railway: faltaba en `requirements.txt` → crash al arrancar
- Login loop infinito: `createClient` (localStorage) incompatible con `proxy.ts` (lee cookies) → `createBrowserClient` (SSR)
- `NotNullViolation` al insertar snapshots: `monthly_return_usd`, `positions_count`, `fx_mep` son NOT NULL → incluidos en inserción
- Cloudflare bloqueaba Railway API desde Python urllib → curl con `User-Agent: Mozilla/5.0`
- `vercel.json` tenía `@buildfuture_supabase_url` (secret refs que no existían en Vercel) → removido env section

### Resultado validación
`npm run build` ✅. Backend v0.7.0 respondiendo en Railway. Frontend live en Vercel. Usuario real con historial de 3 días visible en `/portfolio`.

### Estado actual
App en producción con usuario real. FTU activo para nuevos usuarios. Login completo con registro, recuperación y cambio de contraseña.

---

## Sesión v0.6.1 — 2026-03-30 (code review)

### Objetivo
Revisión por expertos (3 agentes en paralelo: reuse, quality, efficiency). Consolidación de issues encontrados y aplicación de fixes.

### Cambios realizados

**Recomendaciones — slot system completo**
- Perfil `conservador`: slot 1 = LETRA, slot 2 = CEDEAR bajo/medio (no GGAL), slot 3 = mejor sin riesgo alto
- Perfil `moderado`: slot 1 = mejor global, slot 2 = USD obligatorio, slot 3 = tipo diferente a slot 1 (evita 2 BONDs correlacionados)
- Perfil `agresivo`: slot 1 = riesgo alto, slot 2 = CEDEAR, slot 3 = cualquier restante
- `RISK_PROFILE_FILTERS` más extremos: conservador 0.0× en alto, agresivo 1.6× en alto y 0.3× en bajo
- `AgenteDiversificacion`: tickers stale reemplazados por detección dinámica desde `UNIVERSE`
- `_LECAP_TICKERS`, `_USD_TICKERS`, `_CEDEAR_TICKERS`: `frozenset` precalculados a nivel módulo

**Backend — portfolio.py**
- Imports `PortfolioSnapshot` y `UNIVERSE` movidos al tope del módulo (eliminados deferred imports dentro de funciones)
- `_normalize_date()` y `_MONTH_NAMES` extraídos como helpers de módulo (reutilizables)
- Doble llamada a `_date()` eliminada: `date_iso` guardado en `grouped` dict y reutilizado
- Math redundante en `next-goal`: `max(remaining + (monthly_return - remaining), 0)` → `max(monthly_return, 0)`

**Frontend — formatters**
- `formatPct(value, decimals, signed)`: nuevo parámetro `signed = false` para prefijo `+` en rendimientos
- `PortfolioTabs`: eliminados `formatUSD` y `formatPct` locales → `import { formatUSD, formatPct } from "@/lib/formatters"`, uso `formatPct(v, 1, true)` para signed
- `NextGoalCard`: eliminados `formatUSD` y `formatARS` locales → importados de lib
- `portfolio/page.tsx`: ARS inline reemplazado con `formatARS()`
- `PerformanceChart`: `res.ok` check agregado en `changePeriod` — error HTTP ya no queda silencioso

### Resultado validación
`npx next build` ✅ sin errores. Backend v0.6.1 endpoints `/history` y `/next-goal` respondiendo correctamente.

---

## Sesión v0.6.0 — 2026-03-30

### Objetivo
Portafolio page v2: ver historial de tenencia y rendimiento en gráfico de barras, tabs de composición/rendimientos por posición. En dashboard: reemplazar "próximo hito" abstracto por card concreta basada en presupuesto real. Eliminar freedom % suelto del hero.

### Cambios realizados

**Backend — 2 endpoints nuevos**
- `GET /portfolio/history?period=daily|monthly|annual`: agrupa `PortfolioSnapshot` por período, calcula `delta_usd` vs punto anterior. Fix de `strftime` para Windows (sin `%-d` ni `%b`, usa array de meses en español hardcodeado).
- `GET /portfolio/next-goal`: encuentra la próxima categoría del presupuesto no cubierta, calcula capital necesario (`missing_return × 12 / annual_yield`), meses de ahorro (`capital / savings_usd`), ticker top del universo como recomendación.

**Frontend — nuevos componentes**
- `PerformanceChart` (client): chip Tenencia (barras azules, valor total del portafolio por período) / Rendimiento (barras verdes/rojas, `delta_usd` contra período anterior). Chips de período con fetch dinámico al backend. Estado vacío explícito cuando `has_data=false`.
- `PortfolioTabs` (client): tab Composición (barra apilada por `asset_type` coloreada + leyenda + lista de posiciones con %) / tab Rendimientos (posiciones ordenadas por `performance_pct` descendente, barra horizontal P&L, costo vs valor actual).
- `NextGoalCard` (server): card en dashboard — categoría objetivo, barra de progreso, capital en USD/ARS, ahorro disponible del mes, ticker + yield TNA recomendado. Link a `/goals`.
- Portfolio page refactor: header con total USD + equivalente ARS con MEP del presupuesto + renta mensual/anual. Integra `PerformanceChart` + `PortfolioTabs`.

**Dashboard — limpieza**
- Freedom % eliminado del hero (era abstracto, desconectado del presupuesto). Reemplazado por total USD del portafolio en la esquina derecha.
- Bloque "Próximo hito" abstracto (milestones 25/50/75/100%) reemplazado por `NextGoalCard` basada en el presupuesto real del usuario.

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|-----|-------|-----|
| `ValueError: Invalid format string` en `/portfolio/history` | `strftime("%-d %b")` no existe en Windows | Array `MONTH_NAMES` hardcodeado en español + acceso a `.month` y `.day` directamente |
| `snapshot_date` string vs date en SQLite | SQLAlchemy+SQLite puede devolver el campo Date como str | Helper `_date()` con `date.fromisoformat()` como fallback |

### Decisiones técnicas

- **Sin toggle ARS/USD**: se muestra total ARS como texto secundario (calculado con MEP del presupuesto) en lugar de un toggle interactivo. Reduce complejidad sin perder la información clave.
- **`has_data: false` con 1 snapshot**: el gráfico muestra estado vacío hasta acumular 2+ snapshots. Es correcto — el delta no tiene sentido con un solo punto. Se acumula automáticamente con el scheduler.
- **NextGoalCard usa primer instrumento LETRA del universo**: `top_instrument = next((i for i in UNIVERSE if i.asset_type == "LETRA"), UNIVERSE[0])`. Actualmente = S15Y6 68% TNA.

### Estado actual

Backend v0.6.0 corriendo en `localhost:8007`. Frontend v0.6.0 corriendo en `localhost:3001`. Dashboard con NextGoalCard funcional (muestra "Ropa — 1 mes"). Portafolio con gráfico y tabs. Snapshots acumulándose automáticamente L-V 17:30 ART.

---

## Sesión v0.5.0 — 2026-03-30

### Objetivo
Conectar el comité de expertos al router, sincronizar el portafolio real de IOL, y calcular rendimiento en USD con tipo de cambio real al momento de compra.

### Cambios realizados

**Comité de expertos — wiring completo**
- `expert_committee.py` conectado al router como recomendador default (reemplaza `smart_recommendations`)
- Frontend `RecommendationList` muestra panel "Comité de expertos" con señal y convicción de cada agente
- Badges `agents_agreed` en la hero card muestran qué agentes acuerdan en la recomendación
- Universo corregido: eliminado S31O5 (venció Oct-2025), S15G6 → S31G6, YCA6O reemplazado por AL30

**Tickers reales IOL corregidos**
- G = Agosto en nomenclatura de LECAPs (no Junio)
- S15Y6 = LECAP 15/May/2026 (confirmado en IOL) — ticker corto plazo
- S31G6 = LECAP 31/Ago/2026 (confirmado en IOL, ya comprada por el usuario)

**Fix crítico: valuaciones ARS→USD**
- IOL devuelve todos los precios en ARS (no USD como asumíamos)
- `get_portfolio()` ahora usa `valorizado / cantidad / MEP` para precio real en USD
- LECAPs: IOL cotiza ppc per 100 nominales → ajuste `ppc/100` para precio por nominal
- `_get_mep()`: método propio que consulta dolarapi en tiempo real

**Persistencia robusta**
- Tabla `InvestmentMonth`: meses con inversión real desde operaciones IOL (reemplaza proxy snapshot_date)
- Tabla `PortfolioSnapshot`: snapshot diario de valor total del portafolio
- Scheduler APScheduler: job L-V 17:30 ART (cierre de mercado) — sync IOL + snapshot
- Backup automático: `backups/buildfuture_YYYY-MM-DD.db` antes de cada job, 30 días de retención
- `POST /admin/snapshot` para trigger manual

**Costo base y rendimiento real en USD**
- `Position.ppc_ars`: precio promedio de compra en ARS crudo (directo de IOL)
- `Position.purchase_fx_rate`: MEP/CCL al momento de compra
- `Position.cost_basis_usd`: costo base real = `quantity × ppc_ars / purchase_fx_rate`
- `Position.performance_pct`: rendimiento en USD usando costo base real
- Para CEDEARs: CCL implícito via Yahoo Finance — `equiv = round(nyse × mep / bcba)` → `ccl = bcba × equiv / nyse_at_purchase`
- Para LECAPs/bonos: MEP histórico via bluelytics
- Endpoint `/portfolio/` expone `cost_basis_usd`, `purchase_fx_rate`, `ppc_ars`

**UX**
- BudgetEditor: `useBruto = true` por defecto

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|-----|-------|-----|
| S31O5 como recomendación #1 | Venció Oct-2025, estaba en universo | Reemplazado por S15Y6 |
| Valuaciones ×1430 incorrectas | IOL da precios en ARS, usábamos como USD | `valorizado/cantidad/MEP` |
| LECAP cost_basis $34k en vez de $347 | ppc=101.85 aplicado por nominal sin dividir/100 | `asset_type=="LETRA"→ppc/100` |
| Columnas faltantes en DB | `create_all` no altera tablas existentes | `ALTER TABLE` manual via sqlite3 |
| Servidor sin recargar cambios | Uvicorn sin `--reload` y proceso viejo activo | Restart + PowerShell kill |

### Decisiones técnicas

- **CCL implícito desde Yahoo Finance**: IOL endpoints de cotización devuelven 500 fuera de horario de mercado. Alternativa: Yahoo Finance para precio NYSE (sin auth) + ratio derivado de precios actuales.
- **Ratio CEDEAR derivado**: `equiv = round(nyse_price × mep / bcba_price)`. No requiere CNV lookup. Para QQQ calculó equiv=19, CCL_implícito=$1,406 (vs MEP $1,430).
- **Scheduler in-process**: APScheduler BackgroundScheduler. Apropiado para uso personal local. Limitación: no captura si el servidor está apagado a las 17:30.

### Estado actual

Portafolio real sincronizado: QQQ (2 CEDEARs, $58 USD), S15Y6 ($347 USD), S31G6 ($278 USD). Total $683 USD. FCI pendiente de liquidación. Rendimiento mensual: $35.95/mes. MEP en tiempo real: $1,432.

---

## Sesión v0.4.0 — 2026-03-29

### Objetivo
Convertir la app de un tracker financiero abstracto a una experiencia gamificable donde el portafolio compite contra los gastos reales del usuario.

### Cambios realizados

**Dashboard — rediseño hero**
- Eliminado el "Freedom Score %" como protagonista (demasiado abstracto)
- Nuevo hero: `+USD 175/mes` que genera el portafolio vs `USD 2,000/mes` de gastos
- Barra de progreso con separadores por categoría de presupuesto
- Categorías como niveles: ✓ verde (desbloqueado), amarillo (parcial), 🔒 gris (pendiente)
- CTA dinámico: "Próximo a desbloquear: 🚗 Transporte — faltan USD 84/mes"
- Freedom % pasa a stat secundario (top right)

**Metas — nueva lógica**
- Eliminados milestones abstractos (25%/50%/75%/100%)
- Roadmap concreto: para cada categoría pendiente muestra cuánto rendimiento mensual falta y cuánto capital habría que invertir
- Mini barra del juego: N/M categorías desbloqueadas
- InvestmentStreak: calendario de 12 meses + badges por racha

**Backend — gamificación**
- Nuevo endpoint `GET /portfolio/gamification` — retorna portfolio_covers + streak calendar
- Streak calendar: 7 meses de historial real (snapshot_dates distribuidos en seed)
- `smart_recommendations.py`: scoring engine con datos de mercado en tiempo real (dolarapi + BCRA)

**Fixes técnicos**
- Centralizacion de `NEXT_PUBLIC_API_URL` — eliminados 4 hardcoded `localhost:8007/8005`
- LECAP yield corregido a 68% TNA en seed, DB y iol_client
- Posiciones inactivas activadas (5 de 7 estaban `is_active=False`)
- `formatARS` local eliminada de 3 componentes

**Demo automatizado**
- `scripts/demo.js` — Playwright navega la app en viewport de iPhone 14 Pro
- Pauses interactivas con ENTER para grabar con Loom

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|-----|-------|-----|
| Racha siempre = 1 mes | Todas las posiciones con snapshot_date = today | Spread de fechas en DB: Sep-Mar |
| Rendimiento USD 34 en lugar de USD 175 | 5 posiciones con is_active=False | Activadas en DB |
| Yields distintos para LECAP | seed=0.40, iol_client=0.35, smart_recs=0.68 | Unificado a 0.68 en todos |
| Dos procesos uvicorn en 8007 | Kill fallaba con PID incorrecto en bash | Stop-Process de PowerShell |

### Decisiones técnicas

- **Nexo Platform vs Pro**: el usuario usa la app regular de Nexo (no Pro). Nexo Platform no tiene API pública. Decisión: marcar como pendiente entrada manual de cripto, no invertir más tiempo en auth Nexo.
- **Racha con snapshot_date como proxy**: solución rápida aceptable para demo. Para producción se necesita tabla `investment_months` con un registro por mes confirmado.
- **Freedom % como secundario**: el % abstracto no genera engagement. El "portafolio paga X categorías" es la métrica gamificable correcta.

### Estado actual

App funcional y demostrable. Portafolio mock con 7 posiciones activas (GGAL, MSFT, AL30, LECAP, BTC, USDT, CASH_ARS). Racha de 7 meses. Rendimiento USD 175/mes. Smart recommendations funcionando con datos de mercado en tiempo real.

---

## Sesión v0.3.0 — anterior

- IOL connect flow — credenciales, auth, sync de portafolio real
- Integrations settings page
- CORS fix (wildcard)

---

## Sesión v0.2.0 — anterior

- Arquitectura multi-usuario Supabase
- Modelos broker/crypto protocols
- CI/CD GitHub Actions
