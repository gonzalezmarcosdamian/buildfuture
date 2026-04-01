# BuildFuture — Roadmap de Producto

## Visión
App personal de libertad financiera para el mercado argentino. El usuario ve en tiempo real qué porcentaje de sus gastos mensuales cubre el rendimiento de su portafolio ("Freedom Bar"), y recibe recomendaciones contextuales de dónde invertir su ahorro mensual.

---

## Completado ✅

### Core
- [x] Freedom Bar — % de gastos cubiertos por rendimiento del portafolio
- [x] FTU flow — onboarding guiado (presupuesto → portafolio → perfil de riesgo)
- [x] Auth multi-usuario Supabase (JWT ES256)
- [x] Perfil de riesgo: conservador / moderado / agresivo

### Portafolio
- [x] Integración IOL (InvertirOnline) — sync de posiciones reales
- [x] Auto-sync IOL: background task al abrir dashboard/portafolio (umbral 60 min)
- [x] Desconectar integración con modal de confirmación
- [x] Snapshots diarios del portafolio
- [x] Historial gráfico (daily / monthly / annual)
- [x] Detalle de instrumento por tipo (FCI / CEDEAR / LETRA / BOND / CRYPTO)
- [x] MEP histórico al momento de compra para cálculo de costo base real
- [x] CCL implícito para CEDEARs
- [x] Posición manual — UI grisada "Próximamente"

### Recomendaciones
- [x] Comité de 5 agentes: CarryARS, Dolarización, Renta Fija, Diversificación, Macro
- [x] 5 recomendaciones por perfil (universo de 11 instrumentos)
- [x] Carousel horizontal swipeable con cards compactas
- [x] Modal ℹ por card: rationale completo + agentes del comité + barras de convicción
- [x] Tab "para vos" destacado con perfil del usuario
- [x] Retorno contextualizado: "Invertir $X USD → +$Y/mes"

### Gamificación
- [x] Racha mensual de inversiones (calendario 12 meses)
- [x] Portfolio covers — qué categorías de gasto cubre el portafolio
- [x] Roadmap de desbloqueo con capital necesario por meta

### Presupuesto
- [x] Ingresos, gastos por categoría, ahorro mensual
- [x] MEP dinámico para conversión ARS ↔ USD
- [x] Categorías con íconos y montos

### Infraestructura
- [x] CI/CD: GitHub Actions (ruff + bandit backend; tsc + eslint + build frontend)
- [x] Deploy: Railway (backend) + Vercel (frontend, auto-deploy en merge a master)
- [x] Checklist pre-deploy en memoria del agente
- [x] CLAUDE.md con reglas del equipo

---

## Pendiente 📋

### Alta prioridad
- [ ] Ingreso manual de posiciones: CRYPTO / FCI / ETF / OTRO (WIP local, pendiente deploy a prod con migración DB)
- [ ] Editar posición manual desde `/portfolio/[ticker]`
- [ ] FreedomGoal editable desde UI (hoy hardcodeado en DB)

### Media prioridad
- [ ] Integración PPI (Portfolio Personal) — "Próximamente" en UI
- [ ] Auto-deploy Railway desde GitHub (hoy es manual via GraphQL API)
- [ ] Notificaciones push cuando hay oportunidad de inversión destacada
- [ ] Comparar rendimiento real vs benchmark (inflación, MEP, S&P)

### Baja prioridad / ideas
- [ ] Exportar portafolio a CSV/PDF
- [ ] Proyección de libertad financiera: gráfico de cuándo llego al 100% con ahorro actual
- [ ] Soporte multi-moneda en presupuesto (hoy todo en ARS)
- [ ] Widget de resumen para iOS/Android

---

## Decisiones de producto tomadas
- **Retorno por instrumento** (no total): el carousel muestra cuánto genera cada instrumento sobre su slice del capital, no el total. Transparencia > simplicidad.
- **Perfil de riesgo en español**: `conservador / moderado / agresivo` — unificado en toda la app a partir de v0.10.0.
- **Auto-sync no bloqueante**: el usuario ve datos actuales mientras IOL sincroniza en background. UX > precisión instantánea.
