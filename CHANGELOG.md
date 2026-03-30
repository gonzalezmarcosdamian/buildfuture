# CHANGELOG

Formato: [SemVer](https://semver.org/) — `MAJOR.MINOR.PATCH`
Commits: [Conventional Commits](https://www.conventionalcommits.org/)

---

## [Unreleased]

### Pendiente
- Nexo Platform: no tiene API pública — agregar entrada manual de cripto
- ANTHROPIC_API_KEY: recomendaciones vía Claude API (preparado, falta key)
- IOL histórico: importar operaciones pasadas para base de costo
- FreedomGoal: hacer editable desde la UI
- Racha: tabla dedicada `investment_months` (actualmente proxy por snapshot_date)
- Port management: startup script para evitar acumulación de procesos

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
