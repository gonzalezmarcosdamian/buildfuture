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
- ✅ Sync manual IOL (OAuth2 password grant)
- ✅ Milestone projections (25/50/75/100%)

### Presupuesto
- ✅ Ingreso bruto → neto con descuentos AFIP (slider 10-35%)
- ✅ Categorías editables con slider + input % + input ARS sincronizados
- ✅ Vacaciones como categoría separada (no va a inversión)
- ✅ MEP dinámico desde dolarapi.com con refresh manual
- ✅ Indicador "sin guardar" cuando FX cambia

### Gamificación
- ✅ "Tu portafolio trabaja por vos": bar portafolio vs gastos
- ✅ Categorías como niveles: ✓ desbloqueado / ~ parcial / 🔒 bloqueado
- ✅ CTA "próximo a desbloquear" con capital necesario
- ✅ Racha mensual: calendario 12 meses estilo GitHub
- ✅ Badges: 🌱 3m · 🌿 6m · 🌳 12m
- ✅ Roadmap de desbloqueo: cuánto rendimiento y capital necesita cada categoría

### Recomendaciones
- ✅ Motor de scoring sin AI (dolarapi + BCRA en tiempo real)
- ✅ 9 instrumentos argentinos: LECAPs, CEDEARs, bonos soberanos, ONs, crypto
- ✅ Selector perfil de riesgo: conservador / moderado / agresivo
- ✅ Hero card + lista rankeada con rationale y why_now dinámicos
- ✅ Capital de recomendación = ahorro disponible del presupuesto

### Integraciones
- ✅ IOL: connect, auth, sync posiciones
- ✅ Error handling en sync con feedback diferenciado
- ⚠️ Nexo Pro: auth implementada pero 401 (usuario usa Platform, no Pro)

### DevEx
- ✅ Demo automatizado Playwright (`scripts/demo.js`) — viewport iPhone 14 Pro
- ✅ URLs centralizadas en NEXT_PUBLIC_API_URL
- ✅ Yields consistentes en toda la app (LECAP 68%)

---

## Pendiente 🔲

### Alta prioridad
- 🔲 **Nexo Platform**: no tiene API → entrada manual de cripto en UI
- 🔲 **FreedomGoal editable**: target_annual_return_pct y monthly_savings_usd desde UI
- 🔲 **Tabla investment_months**: racha real (actualmente proxy por snapshot_date)

### Media prioridad
- 🔲 **Claude API recommendations**: preparado en ai_recommendations.py, falta ANTHROPIC_API_KEY
- 🔲 **IOL histórico**: importar operaciones pasadas 2020→hoy para base de costo
- 🔲 **Flujo "invertir ahora"**: desde presupuesto → recomendaciones → confirmar → registrar inversión del mes
- 🔲 **Port management**: startup script que mata procesos viejos antes de levantar

### Baja prioridad
- 🔲 Supabase Auth (multi-usuario)
- 🔲 Railway deploy (producción)
- 🔲 Notificaciones: alerta cuando la racha está en riesgo
- 🔲 Metas custom del usuario (vacaciones, seña depto, fondo emergencia)
