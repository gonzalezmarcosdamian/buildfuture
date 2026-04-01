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
- ✅ Gráfico de barras: Tenencia (valor total por período) / Rendimiento (delta diario verde-rojo)
- ✅ Chips de período: Diario / Mensual / Anual con fetch dinámico
- ✅ Tabs: Composición (barra apilada por tipo + %) y Rendimientos (P&L por posición)
- ✅ Header portafolio: total USD + equivalente ARS + renta mensual + renta anual

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
- ✅ `NextGoalCard` en dashboard: próxima categoría, capital ARS/USD, meses de ahorro, ticker recomendado
- ✅ Freedom % abstracto eliminado del hero — reemplazado por portafolio total USD

### Recomendaciones
- ✅ Comité de 4 agentes expertos: Carry ARS, Dolarización, Renta Fija, Diversificación
- ✅ Slot system: conservador/moderado/agresivo siempre con instrumentos distintos garantizados
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

### Portfolio v3
- ✅ Switch unificado Composición / Rendimientos: un control que afecta gráfico + listado de activos
- ✅ Modales informativos: ⓘ explica cómo se calcula la tenencia y los rendimientos del día
- ✅ "Próximamente: ingreso manual de tenencias" card al final de portfolio
- ✅ IOLCAMA en universo de recomendaciones (FCI money market, liquidez diaria)
- ✅ Conservador slot 1 → FCI money market (ya no duplica LECAP con moderado)

### Auth y deploy
- ✅ **Supabase Auth multi-usuario**: JWT ES256 via JWKS, sesión en cookies (SSR compatible)
- ✅ **Login completo**: tabs Ingresar/Registrarse + Olvidaste contraseña + form cambio de contraseña con token recovery
- ✅ **BottomNav oculto en /login**: sin nav en pantalla de autenticación
- ✅ **FTU flow**: onboarding con 3 checks (presupuesto / portafolio / perfil de riesgo) antes de mostrar el dashboard
- ✅ **Perfil de riesgo persistido**: `UserProfile` model + `GET /profile/` + `PUT /profile/`
- ✅ **Railway deploy**: backend en producción (`api-production-7ddd6.up.railway.app`)
- ✅ **Vercel deploy**: frontend en producción (`frontend-teal-seven-22.vercel.app`)
- ✅ **Historial real de tenencia**: snapshots reconstruidos con precios reales (Yahoo Finance + TNA accrual)

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
- 🔲 Notificaciones: alerta cuando la racha está en riesgo
- 🔲 Metas custom del usuario (vacaciones, seña depto, fondo emergencia)
- 🔲 Multi-tenant onboarding: admin panel para crear nuevos usuarios
