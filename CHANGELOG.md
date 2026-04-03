# CHANGELOG

Formato: [SemVer](https://semver.org/) — `MAJOR.MINOR.PATCH`
Commits: [Conventional Commits](https://www.conventionalcommits.org/)

---

## [0.11.0] — 2026-04-03

### Added
- **Persistencia de enriquecimiento entre re-syncs** (`_get_enrichment`): helper en `integrations.py` que preserva `annual_yield_pct`, `external_id` y `fci_categoria` (campos platform-owned) entre re-syncs de IOL, PPI y Cocos. El yield real ya no se pisa con el DEFAULT del ALYC cada vez que el usuario sincroniza.
- **yield_updater post-sync**: los 3 syncs (IOL, PPI, Cocos) llaman `update_yields()` inmediatamente después del INSERT — yield correcto disponible en segundos, sin esperar al scheduler de 17:30.
- **ONs corporativas en `_BOND_YTM`**: 13 ONs calibradas con precios de mercado abril 2026 (ARC1O, DNC5O, DNC7O, LOC6O, MR39O, RUCDO, TLCMO, TLCPO, TLCTO, VSCVO, YM34O, YM39O, YMCJO). Yields 7–12% USD.
- **Endpoints admin yields**: `GET /admin/yields/diagnose` y `POST /admin/yields/run` para inspección y disparo manual del yield_updater.
- **Yields reales por instrumento**: LECAP → TIR real desde precio + días al vencimiento decodificados del ticker. FCI → promedio ArgentinaDatos mercadoDinero (~17% TNA). BOND → tabla `_BOND_YTM` calibrada.
- **MEP diario en posiciones ARS**: `current_price_usd` de LETRA/FCI se recalcula con MEP del día en cada cierre.
- **Badge de vencimiento en InstrumentDetail**: alerta "Rolleo en Nd" cuando la LECAP vence en ≤60 días.

### Fixed
- LECAP con precio técnico acumulado (>par en IOL) ya no pisa el yield con 0%. Auto-restaura a 68% TNA si fue pisado.
- FCI con match incorrecto en ArgentinaDatos (>150% TNA) cae al promedio de mercado.
- `timedelta` import en `yield_updater.py` — bug que forzaba fallback a 38% TNA en FCIs.
- `current_value_ars=0` en posiciones históricas reconstruido desde `price_usd × mep` antes del cálculo de TIR.

### Chore
- Eliminado `.docs/` (stale, `docs/` es el directorio canónico)
- Eliminado `requirements.txt` raíz (stale, el activo es `backend/requirements.txt`)
- Movidos `test_iol_auth.py` y `test_nexo_auth.py` a `backend/scripts/`
- Cerrado PR stale #4 (feat/autosync-gamification, 100 commits behind main)

---

## [0.10.0] — 2026-04-01

### Added
- **Reconstructor histórico v2**: algoritmo backwards-anchored con `cantidadOperada` real de IOL. Detecta ventas invisibles y preserva posiciones conocidas. Snapshots diarios reconstruidos desde operaciones reales.
- **Admin endpoints**: `/admin/snapshots/info`, `/admin/reconstruct/dry-run`, `/admin/reconstruct/raw-ops`, `/admin/positions/inspect`, `/admin/positions/dupes`, `/admin/cache/mep-info`, `/admin/cache/price-info`.
- **Fix precio LECAP**: `ppc_ars / 100` — IOL expresa precio en ARS por 100 VN.

---

## [0.8.0] — 2026-04-01

### Added
- **Switch unificado Composición / Rendimientos**: un solo control en `/portfolio` que afecta simultáneamente al gráfico de barras y al listado de activos — eliminados los switches independientes de `PerformanceChart` y `PortfolioTabs`
- **Modales informativos de cálculo**: ícono ⓘ junto al switch abre un panel inline con:
  - *Composición/Tenencia*: cómo se calcula el valor total diario (snapshot 17:30 ART, CEDEARs via ARS÷MEP, LECAPs/FCI via nominal×precio)
  - *Rendimientos*: cómo se calcula el delta del día (barra verde/roja, TNA÷365 para renta fija, movimiento de mercado para CEDEARs)
- **"Próximamente: ingreso manual de tenencias"**: card al final de `/portfolio` con descripción de la feature pendiente
- **`IOLCAMA` en universo de recomendaciones**: FCI money market con liquidez diaria, TNA ~64%, riesgo bajo — aparece en slot 1 del perfil conservador
- **Conservador: slot 1 → FCI money market** (antes era LECAP): elimina duplicado con perfil moderado que también tomaba la misma letra
- **Rationale para FCI** en `_build_rationale`: texto específico de money market (liquidez diaria, tasa real positiva sin atar el capital)
- **FTU fix crítico**: el gate de risk profile solo bloquea cuando el endpoint `/profile/` existe en el backend (`available: true`); si el backend es viejo (404), el dashboard se muestra igual
- **FTU error handling**: mensaje de error visible cuando `PUT /profile/` falla; `window.location.href` en lugar de `router.refresh()` para recargar estado del servidor

### Changed
- `PerformanceChart`: ya no tiene switch interno de modo; recibe `chartMode: "tenencia" | "rendimiento"` como prop
- `PortfolioTabs`: ya no tiene tab bar interno; recibe `activeTab: "composicion" | "rendimientos"` como prop
- `portfolio/page.tsx`: usa nuevo `PortfolioClient` wrapper que orquesta el estado unificado
- `fetchProfile()` en `api-server.ts`: ahora retorna `{ risk_profile, available }` — distingue 404 (backend viejo) de null (sin perfil configurado)

### Fixed
- Perfiles **conservador** y **moderado** ya no recomiendan la misma LECAP: conservador ahora recibe IOLCAMA (money market) en slot 1
- Login: `router.refresh()` reemplazado por `window.location.href` en FTU para asegurar re-evaluación completa del server component

---

## [Unreleased]

### Pendiente
- FCI manual entry: Nexo Platform y FCI sin API → entrada manual de posiciones
- FreedomGoal: hacer editable desde la UI
- Port management: startup script para evitar acumulación de procesos uvicorn
- ANTHROPIC_API_KEY: recomendaciones vía Claude API (preparado, falta key)
- PPI integration: `ppi-client` PyPI disponible, siguiente ALYC

---

## [0.7.0] — 2026-03-31

### Added
- **Auth multi-usuario**: JWT ES256 verificado vía Supabase JWKS; dev fallback a `SEED_USER_ID` sin Supabase URL
- **Deploy Railway + Vercel**: backend en Railway (`api-production-7ddd6.up.railway.app`), frontend en Vercel (`frontend-teal-seven-22.vercel.app`)
- **Login page completo**: tabs Ingresar / Registrarse + flujo "olvidaste contraseña" + form de nueva contraseña al recibir el link de recovery (evento `PASSWORD_RECOVERY` de Supabase)
- **BottomNav oculto en /login**: `usePathname()` detecta la ruta y retorna `null`
- **FTU flow (First-Time User)**: dashboard gatea acceso hasta completar 3 pasos — configurar presupuesto, sincronizar portafolio, elegir perfil de riesgo
- **`FTUFlow` component**: cards individuales por paso faltante con CTA buttons + selector inline de perfil de riesgo (conservador/moderado/agresivo) + barra de progreso
- **`UserProfile` model**: tabla `user_profiles` con `risk_profile` (conservative/moderate/aggressive)
- **`GET /profile/` + `PUT /profile/`**: endpoints para leer/guardar perfil de usuario
- **Historial real de tenencia**: snapshots reconstituidos con precios reales — QQQ via Yahoo Finance, LECAPs y FCI vía acumulación TNA diaria, MEP 1430.8
  - Mar 30: USD 696.77 | Mar 31: USD 699.40 (+2.63) | Abr 1: USD 699.94 (+3.17)

### Fixed
- **`createBrowserClient` (SSR)**: reemplaza `createClient` de `@supabase/supabase-js` — sesión en cookies en lugar de localStorage, compatible con proxy server-side
- **Bearer token en todos los componentes client**: `BudgetEditor`, `IntegrationCard`, `ConnectIOLForm`, `ConnectNexoForm`, `PerformanceChart`, `RecommendationList`, `RecommendationCarousel` — todos usan `supabase.auth.getSession()` antes de cada fetch
- **`NEXT_PUBLIC_API_URL` centralizado**: eliminados `localhost:8007` hardcodeados en componentes
- **`load_dotenv()` en `database.py` y `auth.py`**: sin esto, Railway/local no cargaba `DATABASE_URL` ni `SUPABASE_URL`
- **`anthropic>=0.40.0`** agregado a `requirements.txt` (crash en Railway al arrancar)
- **`DEV_USER_ID`** cambiado a UUID válido `00000000-0000-0000-0000-000000000001` (evita `StringDataRightTruncation` en columna `String(36)`)
- **`proxy.ts`**: Next.js 16 deprecó `middleware.ts` como nombre de export — renombrado y export actualizado

---

## [0.6.1] — 2026-03-30

### Fixed (code review)
- **Slot system recomendaciones**: 3 perfiles ahora garantizan instrumentos distintos — conservador (LETRA + CEDEAR defensivo + sin riesgo alto), moderado (mejor global + USD obligatorio + tipo diferente), agresivo (riesgo alto + CEDEAR + restante)
- **`RISK_PROFILE_FILTERS` extremos**: agresivo 1.6× para riesgo alto, conservador 0.0× para riesgo alto
- **`formatUSD`/`formatARS`/`formatPct` duplicados** en `PortfolioTabs`, `NextGoalCard`, `portfolio/page.tsx` → eliminados, importados de `@/lib/formatters`
- **`formatPct` con signo**: parámetro `signed = false` agregado a lib para el prefijo `+` en rendimientos
- **`_date()` doble llamada** en loop de history: `date_iso` guardado en `grouped` dict, eliminada segunda conversión
- **Math redundante** en `next-goal`: `max(remaining + (monthly_return - remaining), 0)` → `max(monthly_return, 0)`
- **Imports dentro de funciones** (`PortfolioSnapshot`, `UNIVERSE`) → movidos al tope del módulo
- **Sets de UNIVERSE** recalculados en cada `vote()` → `frozenset` precalculados a nivel módulo (`_LECAP_TICKERS`, `_USD_TICKERS`, `_CEDEAR_TICKERS`)
- **`res.ok` check** faltante en `changePeriod` de `PerformanceChart` → error ya no queda silencioso
- **Tickers stale** en `AgenteDiversificacion` (`S31O5`, `S15G6`, `YCA6O`) → detección dinámica desde `UNIVERSE`

---

## [0.6.0] — 2026-03-30

### Added
- **`GET /portfolio/history`**: historial de `PortfolioSnapshot` agrupado por período (daily/monthly/annual), con `delta_usd` contra período anterior
- **`GET /portfolio/next-goal`**: próxima categoría a desbloquear del presupuesto — capital necesario USD/ARS, meses de ahorro, ticker recomendado
- **`PerformanceChart`**: gráfico de barras con dos modos (Tenencia = valor acumulado / Rendimiento = ganancia/pérdida diaria en verde-rojo) y chips de período (Diario/Mensual/Anual)
- **`PortfolioTabs`**: tabs Composición (barra apilada por tipo de activo + % del total) y Rendimientos (posiciones ordenadas por performance, barra horizontal, P&L USD)
- **`NextGoalCard`**: card en dashboard con próxima categoría a desbloquear, progreso actual, capital necesario, ahorro disponible, ticker recomendado con yield
- **Portfolio page v2**: header con total USD + equivalente ARS + renta anual, integra PerformanceChart y PortfolioTabs

### Changed
- **Dashboard**: Freedom % eliminado del hero (reemplazado por total USD del portafolio)
- **Dashboard**: bloque "Próximo hito" abstracto (25/50/75/100%) reemplazado por `NextGoalCard` basada en presupuesto real

### Fixed
- `strftime("%-d %b")` → formato explícito sin directives de Unix para compatibilidad Windows

---

## [0.5.0] — 2026-03-30

### Added
- **Comité de expertos**: `expert_committee.py` conectado como recomendador default — 4 agentes (Carry ARS, Dolarización, Renta Fija, Diversificación) con señales en tiempo real
- **Frontend recomendaciones**: panel "Comité de expertos" con convicción por agente, badges `agents_agreed` en hero card
- **`InvestmentMonth`**: tabla con meses de inversión real desde operaciones IOL — reemplaza proxy `snapshot_date`
- **`PortfolioSnapshot`**: snapshot diario de valor total del portafolio al cierre de mercado
- **Scheduler**: APScheduler L-V 17:30 ART — sync IOL + snapshot automático
- **Backup automático**: `backups/buildfuture_YYYY-MM-DD.db` antes de cada job (30 días retención)
- **`POST /admin/snapshot`**: trigger manual de snapshot + sync
- **`get_operations()`**: historial de compras/ventas desde IOL API
- **CCL implícito CEDEARs**: Yahoo Finance + ratio derivado → CCL real al momento de compra
- **`Position.ppc_ars`**: precio de compra en ARS crudo (sin conversión)
- **`Position.purchase_fx_rate`**: MEP/CCL al momento de compra por ticker
- **`Position.cost_basis_usd`**: costo base real en USD con MEP histórico
- **`Position.performance_pct`**: rendimiento real en USD (no ARS convertido hoy)
- **BudgetEditor**: modo bruto como default

### Fixed
- **Valuaciones ARS→USD**: IOL devuelve precios en ARS — fix `valorizado/cantidad/MEP` en `get_portfolio()`
- **LECAP ppc convention**: `ppc` de IOL es per 100 nominales → `ppc/100` para costo por nominal
- **Tickers IOL reales**: S31O5 (vencida Oct-2025) → S15Y6; S15G6 → S31G6; YCA6O (no en IOL) → AL30
- **Nomenclatura LECAP**: G = Agosto (no Junio), Y = Mayo

---

## [0.4.0] — 2026-03-29

### Added
- **Dashboard**: hero gamificable — portafolio vs gastos, barra de progreso, categorías como niveles a desbloquear con 🔒, CTA "próximo a desbloquear"
- **Metas**: roadmap de desbloqueo con capital necesario por categoría, progreso del juego (N/M categorías)
- **Gamificación**: `PortfolioCovers` — qué categorías cubre el rendimiento mensual (covered/partial/pending)
- **Gamificación**: `InvestmentStreak` — calendario estilo GitHub de 12 meses, badges 🌱🌿🌳, racha actual y mejor racha
- **Backend**: endpoint `GET /portfolio/gamification` — monthly_return, portfolio_covers, streak calendar
- **Recomendaciones**: `smart_recommendations.py` — motor de scoring sin AI, consulta dolarapi.com + BCRA en tiempo real
- **Recomendaciones**: selector de perfil de riesgo (conservador/moderado/agresivo)
- **Recomendaciones**: hero card + lista rankeada con rationale dinámico por condiciones de mercado
- **Presupuesto**: BudgetEditor — toggle bruto/neto, slider de descuentos AFIP, MEP dinámico desde dolarapi.com
- **Presupuesto**: inputs tipeables de % y ARS sincronizados con sliders
- **Presupuesto**: indicador naranja "sin guardar" cuando FX cambia sin guardar
- **Demo**: script Playwright automatizado (`scripts/demo.js`) — navega la app frame por frame para grabación

### Fixed
- URLs hardcodeadas en todos los componentes — centralizadas en `NEXT_PUBLIC_API_URL`
- `formatARS` duplicada en 3 componentes — ahora se importa desde `lib/formatters`
- LECAP yield inconsistente (35%/40% → 68% en seed, iol_client y DB)
- Posiciones con `is_active=False` en DB — activadas todas
- `snapshot_date` de posiciones spread en 7 meses consecutivos — racha muestra historial real
- Import muerto `recommendation_engine` eliminado de portfolio router
- `IntegrationCard`: error handling real con mensaje diferenciado (red vs HTTP)
- NavBar: "Gastos" renombrado a "Presupuesto"

---

## [0.2.0] — 2026-03-29

### Added
- Arquitectura multi-usuario con Supabase Auth
- Envelope encryption para credenciales de brokers (KEK + DEK por usuario)
- Modelo multi-ALYC: Protocol `BrokerClient` — IOL v1, Balanz/Cocos planificados
- Modelo multi-crypto: Protocol `CryptoClient` — Nexo + Bitso v1, Binance planificado
- ADRs iniciales en `docs/ARCHITECTURE.md`
- CI/CD con GitHub Actions (backend + frontend)
- `.gitignore` con protección de secrets
- Estructura de carpetas completa incluyendo `settings/integrations`

## [0.1.0] — 2026-03-29

### Added
- Contexto inicial del proyecto (`CONTEXT.md`)
- Arquitectura base: Next.js + FastAPI + Supabase + Railway
- Stack de agentes: Portfolio, Budget, MarketContext, Advisor
- Concepto "Freedom Bar" validado
- Milestones: 25% / 50% / 75% / 100%
- `docs/LEARNINGS.md` iniciado
