# Producto BuildFuture

App de libertad financiera personal para el mercado argentino.
Usuario target: Marcos González — PM Ualá, Córdoba, ahorro USD 1000-1500/mes, cuenta IOL, dinero en Cocos.

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
- ✅ Costo base real en USD: `quantity × ppc_ars / purchase_fx_rate` con MEP histórico
- ✅ CCL implícito para CEDEARs: Yahoo Finance + ratio derivado automáticamente
- ✅ `PortfolioSnapshot`: snapshot diario automático al cierre de mercado (17:30 ART)
- ✅ Backup automático DB (30 días retención en `backups/`)
- ✅ Gráfico de área: Tenencia (valor total por período)
- ✅ Gráfico de barras: Rendimiento (delta diario verde-rojo vs día anterior)
- ✅ Chips de período: Diario / Mensual / Anual con fetch dinámico
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

### Metas de capital e interés compuesto (v0.11 — rama feat/capital-goals-gamification)
- ✅ **Campo `job` en UNIVERSE**: cada instrumento taggeado como `renta` | `capital` | `ambos`
- ✅ **Recomendaciones split**: sección 💰 Renta (LECAP, FCI, bonos) y 📈 Capital (CEDEAR, ETF) en `RecommendationList`
- ✅ **`current_month_invested`** en `/portfolio/gamification`: booleano si el mes actual tiene inversión registrada
- ✅ **InvestmentStreak mejorado**: card de estado del mes (✅ invertiste / ⏳ todavía no) al tope de la sección
- ✅ **`GET /portfolio/projection`**: curva de proyección a 10 años — `with_savings_usd` vs `without_savings_usd`
- ✅ **`ProjectionCard`**: gráfico de dos curvas (Recharts AreaChart), selector de horizonte 1/3/5/10 años, líneas de referencia de metas de capital, insight interactivo
- ✅ **Modal educativo DCA/interés compuesto**: bottom sheet con 3 secciones dinámicas usando datos reales del usuario — rendimiento del portfolio vs benchmarks, impacto DCA año 1/5/10, desglose interés compuesto (inicial + aportes + rendimientos)
- ✅ **`GET /portfolio/goal` + `PUT /portfolio/goal`**: endpoints para leer/guardar `monthly_savings_usd` y `target_annual_return_pct`
- ✅ **Modelo `CapitalGoal`** + migración `capital_goals` table
- ✅ **CRUD `/portfolio/capital-goals`**: GET (con cálculo de progreso y meses estimados), POST, PUT, DELETE
- ✅ **`CapitalGoals` ABM**: lista de metas con barra de progreso, emoji picker, horizonte en años, confirmación borrado con timer 3s
- ✅ **`GoalCompliance`**: card por meta con estado (En camino / Con retraso / Llegaste / Sin datos), fecha proyectada de llegada, delay en meses, barra de progreso coloreada por estado
- ✅ **Empty state dashboard**: cuando no hay metas, card con CTA "Agregar primera meta →" a /goals
- ✅ **Cap yield realista**: `annual_return_pct` capeado a 6–15% USD — evita que rendimiento nominal ARS de LECAPs infle la proyección
- ✅ **`ProjectionCard` con capital goals overlay**: líneas de referencia horizontales en el chart para cada meta dentro del rango visible

### Recomendaciones
- ✅ Comité de 4 agentes expertos: Carry ARS, Dolarización, Renta Fija, Diversificación
- ✅ Slot system: conservador/moderado/agresivo siempre con instrumentos distintos garantizados
- ✅ Señales de mercado en tiempo real (dolarapi + BCRA): MEP, spread, inflación, tasa real
- ✅ Selector perfil de riesgo: conservador / moderado / agresivo
- ✅ Hero card + panel de señales por agente con convicción y badges `agents_agreed`
- ✅ Universo con tickers IOL verificados: S15Y6, S31G6, AL30, GD30, QQQ, SPY, GGAL, XLE, IOLCAMA
- ✅ Capital de recomendación = ahorro disponible del presupuesto
- ✅ IOLCAMA (money market) en conservador slot 1 — no duplica LECAP con moderado

### Integraciones
- ✅ IOL: connect, auth, sync posiciones (precios ARS→USD corregidos)
- ✅ IOL: sync de operaciones → `InvestmentMonth` (racha real por mes)
- ✅ Scheduler: sync + snapshot automático L-V 17:30 ART (APScheduler)
- ✅ Error handling en sync con feedback diferenciado
- ✅ **PPI**: connect + sync posiciones + scheduler auto-sync
- ✅ **Cocos Capital (Iter 1)** — en producción desde 2026-04-02:
  - FCIs + CASH (ARS y USD disponible)
  - Auth: email + password + 2FA manual (código 6 dígitos) + TOTP secret opcional (habilita auto-sync)
  - `ConnectCocosForm` multi-paso: credenciales → 2FA + sección colapsable TOTP
  - `CocosSyncModal`: sync manual con código fresco cuando no hay TOTP
  - Badge ⚡ auto-sync (amarillo) / ⚡ manual (gris) según TOTP configurado
  - Rendimientos en moneda nativa: FCIs/LETRAs/ONs muestran `performance_ars_pct` (ARS) — no depende de MEP histórico
  - `purchase_fx_rate` preservado en resync — el costo base no cambia al re-sincronizar
  - `IntegrationDiscovery`: instrument_types desconocidos se guardan para iterar el mapper en Iter 2
  - `mep.py`: helper compartido para MEP — nunca retorna 0 — usado en scheduler + portfolio + sync
  - Snapshot garantizado al día del primer sync (no espera el scheduler de las 17:30)
  - `InvestmentMonth` marcado al sync si hay posiciones con costo > 0
  - Backfill automático: usuarios existentes ven COCOS en Settings sin intervención manual

### Portfolio UI (v3–v4)
- ✅ Switch unificado Composición / Rendimientos: un control que afecta gráfico + listado de activos
- ✅ Modal ⓘ inline explica cómo se calcula cada vista (tenencia / rendimiento)
- ✅ Posiciones clickeables → página de detalle por instrumento
- ✅ `/portfolio/[ticker]`: detalle con métricas diferenciadas por tipo de activo:
  - **FCI**: cuotapartes, VCP actual ARS, VCP compra ARS, tenencia valorizada ARS + USD
  - **CEDEAR**: PPC ARS con derivación `ppc_ars / MEP_compra = USD x.xx`
  - **LETRA**: PPC per 100 nominales + precio unitario
  - **CRYPTO/ETF**: precio de compra USD
- ✅ Ganancia neta en detalle: monto (verde/rojo) + % rendimiento + equivalente moneda opuesta
- ✅ Renta mensual estimada por instrumento (TNA × valor)
- ✅ Contexto por tipo de activo: descripción, nota de moneda, liquidez, fuente de datos
- ✅ `GET /portfolio/instrument/{ticker}`: endpoint con contexto enriquecido + `pnl_usd`

### Ingreso manual de posiciones (v0.10 — WIP local)
- ✅ CRYPTO: búsqueda live en CoinGecko, precio USD en tiempo real, yield TNA interpolado de variación 30 días
- ✅ FCI: búsqueda por nombre en ArgentinaDatos (todas las categorías), VCP live, TNA calculada de VCP 30 días. Cubre Cocos Ahorro, Cocos Dólares Plus y todos los FCI CAFCI
- ✅ ETF / acciones: validación y precio vía Yahoo Finance, yield TNA 30 días (SPY, QQQ, AAPL, etc.)
- ✅ OTRO: ticker + nombre manual + yield anual fijo definido por usuario
- ✅ `_refresh_manual_prices()` en scheduler: actualiza precios manuales en cada cierre de mercado
- ✅ `Position.external_id` + `Position.fci_categoria`: campos para tracking externo por fuente
- ✅ Formulario 3 pasos: tipo → buscar (live search) → cargar datos de compra
- 🔲 Pendiente deploy a producción (probado solo en local)

### Auth y deploy
- ✅ **Supabase Auth multi-usuario**: JWT ES256 via JWKS, sesión en cookies (SSR compatible)
- ✅ **Login completo**: tabs Ingresar/Registrarse + Olvidaste contraseña + form cambio de contraseña con token recovery
- ✅ **BottomNav oculto en /login**: sin nav en pantalla de autenticación
- ✅ **FTU flow**: onboarding con 3 checks (presupuesto / portafolio / perfil de riesgo) antes del dashboard
- ✅ **Perfil de usuario en /settings**: nombre, perfil de riesgo (animación + localStorage), contraseña, cerrar sesión
- ✅ **Perfil de riesgo persistido**: `UserProfile` model + `GET /profile/` + `PUT /profile/`
- ✅ **Railway deploy**: backend en producción (`api-production-7ddd6.up.railway.app`)
- ✅ **Vercel deploy**: frontend en producción (`frontend-teal-seven-22.vercel.app`)
- ✅ **Historial real de tenencia**: snapshots reconstruidos con precios reales (Yahoo Finance + TNA accrual)

### DevEx
- ✅ Demo automatizado Playwright (`scripts/demo.js`) — viewport iPhone 14 Pro
- ✅ URLs centralizadas en NEXT_PUBLIC_API_URL
- ✅ Yields consistentes en toda la app (LECAP 68%)

---

## APIs externas utilizadas

| API | Uso | Auth | Rate limit |
|-----|-----|------|------------|
| IOL (InvertirOnline) | Posiciones, precios, operaciones | OAuth2 password grant | — |
| PPI | Posiciones, operaciones | API key pública + privada | — |
| Cocos Capital | Posiciones (FCI), cash disponible | email + password + 2FA/TOTP (pycocos, API no oficial) | — |
| dolarapi.com | MEP / tipo de cambio | Sin auth | — |
| bluelytics.com.ar | Dólar blue | Sin auth | — |
| Yahoo Finance (`query1.finance.yahoo.com`) | Precios CEDEARs, ETFs, acciones | Sin auth | — |
| CoinGecko (`api.coingecko.com/api/v3`) | Crypto: búsqueda, precio, histórico 30d | Sin auth | ~15 req/min |
| ArgentinaDatos (`api.argentinadatos.com`) | FCI: VCP diario de todos los fondos CAFCI | Sin auth | — |
| Supabase | Auth JWT, base de datos PostgreSQL | Anon key + JWT | — |

---

## Stack técnico

| Capa | Tecnología |
|------|-----------|
| Frontend | Next.js 16 App Router, TypeScript, Tailwind CSS, Recharts |
| Backend | FastAPI, SQLAlchemy, PostgreSQL (Supabase), APScheduler |
| Auth | Supabase Auth — ES256 JWT via JWKS |
| Deploy frontend | Vercel (auto-deploy desde GitHub master) |
| Deploy backend | Railway (deploy manual via GraphQL API) |
| DB local dev | SQLite (`buildfuture.db`) |

---

## Pendiente 🔲

### Alta prioridad
- 🔲 **Bucket split renta/capital**: separar portfolio en dos carriles en DashboardHero, ProjectionCard y cálculos — ver diseño en BITACORA v0.11.0
- 🔲 **Deploy v0.11 a producción**: bump versión → Railway + Vercel
- 🔲 **Deploy ingreso manual a producción**: testear local completo → Railway + Vercel
- 🔲 **Editar posición manual desde detalle**: botón "Editar" en `/portfolio/[ticker]` para posiciones `source=MANUAL`

### Media prioridad
- 🔲 **Claude API recommendations**: preparado en `ai_recommendations.py`, falta `ANTHROPIC_API_KEY`
- 🔲 **PPI integration**: mock mode funcionando, credenciales reales pendientes
- 🔲 **Flujo "invertir ahora"**: presupuesto → recomendaciones → confirmar → registrar inversión del mes
- 🔲 **Port management**: startup script que mata procesos viejos antes de levantar

### Baja prioridad
- 🔲 Notificaciones: alerta cuando la racha está en riesgo
- 🔲 Multi-tenant onboarding: admin panel para crear nuevos usuarios
- 🔲 Historial retropolado desde fecha de compra (posiciones manuales)
