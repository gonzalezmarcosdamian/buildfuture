# Producto BuildFuture

App de libertad financiera personal para el mercado argentino.
Usuario target: Marcos González — PM Ualá, Córdoba, ahorro USD 1000-1500/mes, cuenta IOL.

---

## Core loop

1. **Configurar presupuesto** → ingreso bruto/neto, categorías, %s
2. **Ver portafolio vs gastos** → qué categorías cubre el rendimiento mensual
3. **Desbloquear categorías** → invertir más para que el portafolio cubra más gastos
4. **Mantener racha** → invertir todos los meses sin faltar

---

## Features implementadas ✅

### Portafolio
- ✅ Posiciones con ticker, tipo, valor USD, yield anual
- ✅ Freedom score (portfolio_return / monthly_expenses)
- ✅ Sync manual IOL (OAuth2 password grant) — precios ARS→USD con MEP real
- ✅ Costo base real en USD: `ppc_ars / purchase_fx_rate` con MEP histórico
- ✅ CCL implícito para CEDEARs: Yahoo Finance + ratio derivado automáticamente
- ✅ `PortfolioSnapshot`: snapshot diario automático al cierre de mercado (17:30 ART)
- ✅ Backup automático DB (30 días retención en `backups/`)
- ✅ Milestone projections (25/50/75/100%)

### Presupuesto
- ✅ Ingreso bruto → neto con descuentos AFIP (slider 10-35%), default bruto
- ✅ Categorías editables con slider + input % + input ARS sincronizados
- ✅ Vacaciones como categoría separada (no va a inversión)
- ✅ MEP dinámico desde dolarapi.com con refresh manual
- ✅ Indicador "sin guardar" cuando FX cambia

### Gamificación
- ✅ "Tu portafolio trabaja por vos": bar portafolio vs gastos
- ✅ Categorías como niveles: ✓ desbloqueado / ~ parcial / 🔒 bloqueado
- ✅ CTA "próximo a desbloquear" con capital necesario
- ✅ Racha mensual: tabla `investment_months` desde operaciones reales IOL
- ✅ Calendario 12 meses estilo GitHub + badges: 🌱 3m · 🌿 6m · 🌳 12m
- ✅ Roadmap de desbloqueo: cuánto rendimiento y capital necesita cada categoría

### Recomendaciones
- ✅ Comité de 4 agentes expertos: Carry ARS, Dolarización, Renta Fija, Diversificación
- ✅ Señales de mercado en tiempo real (dolarapi + BCRA): MEP, spread, inflación, tasa real
- ✅ Selector perfil de riesgo: conservador / moderado / agresivo
- ✅ Hero card + panel de señales por agente con convicción y badges `agents_agreed`
- ✅ Universo con tickers IOL verificados: S15Y6, S31G6, AL30, GD30, QQQ, SPY, GGAL, XLE
- ✅ Capital de recomendación = ahorro disponible del presupuesto

### Integraciones
- ✅ IOL: connect, auth, sync posiciones (precios ARS→USD corregidos)
- ✅ IOL: sync de operaciones → `InvestmentMonth` (racha real por mes)
- ✅ Scheduler: sync + snapshot automático L-V 17:30 ART (APScheduler)
- ✅ Error handling en sync con feedback diferenciado

### DevEx
- ✅ Demo automatizado Playwright (`scripts/demo.js`) — viewport iPhone 14 Pro
- ✅ URLs centralizadas en NEXT_PUBLIC_API_URL
- ✅ Yields consistentes en toda la app (LECAP 68%)

---

## Pendiente 🔲

### Alta prioridad
- 🔲 **Entrada manual de posiciones**: FCI + cripto sin API → form manual en UI
- 🔲 **FreedomGoal editable**: target_annual_return_pct y monthly_savings_usd desde UI

### Media prioridad
- 🔲 **Claude API recommendations**: preparado en ai_recommendations.py, falta ANTHROPIC_API_KEY
- 🔲 **PPI integration**: `ppi-client` PyPI disponible, siguiente ALYC a integrar
- 🔲 **Flujo "invertir ahora"**: desde presupuesto → recomendaciones → confirmar → registrar inversión del mes
- 🔲 **Port management**: startup script que mata procesos viejos antes de levantar

### Baja prioridad
- 🔲 Supabase Auth (multi-usuario)
- 🔲 Railway deploy (producción)
- 🔲 Notificaciones: alerta cuando la racha está en riesgo
- 🔲 Metas custom del usuario (vacaciones, seña depto, fondo emergencia)
