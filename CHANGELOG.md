# CHANGELOG

Formato: [SemVer](https://semver.org/) — `MAJOR.MINOR.PATCH`
Commits: [Conventional Commits](https://www.conventionalcommits.org/)

---

## [Unreleased]

### Planificado
- Setup inicial del proyecto (Next.js + FastAPI + Supabase)
- IOL client con auth OAuth2
- Freedom Calculator (core logic)
- Freedom Bar component
- PortfolioSyncAgent
- Supabase Auth + multi-usuario
- Integrations settings page (conectar broker/exchange)

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
