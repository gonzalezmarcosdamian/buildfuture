# Bitácora BuildFuture

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
