# CHANGELOG

Formato: [SemVer](https://semver.org/) — `MAJOR.MINOR.PATCH`
Commits: [Conventional Commits](https://www.conventionalcommits.org/)

---

## [Unreleased]

### Pendiente
- FCI manual entry: Nexo Platform y FCI sin API → entrada manual de posiciones
- FreedomGoal: hacer editable desde la UI
- Port management: startup script para evitar acumulación de procesos uvicorn
- ANTHROPIC_API_KEY: recomendaciones vía Claude API (preparado, falta key)
- PPI integration: `ppi-client` PyPI disponible, siguiente ALYC

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
