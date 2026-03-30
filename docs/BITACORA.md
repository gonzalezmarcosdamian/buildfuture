# Bitácora BuildFuture

---

## Sesión v0.4.0 — 2026-03-29

### Objetivo
Convertir la app de un tracker financiero abstracto a una experiencia gamificable donde el portafolio compite contra los gastos reales del usuario.

### Cambios realizados

**Dashboard — rediseño hero**
- Eliminado el "Freedom Score %" como protagonista (demasiado abstracto)
- Nuevo hero: `+USD 175/mes` que genera el portafolio vs `USD 2,000/mes` de gastos
- Barra de progreso con separadores por categoría de presupuesto
- Categorías como niveles: ✓ verde (desbloqueado), amarillo (parcial), 🔒 gris (pendiente)
- CTA dinámico: "Próximo a desbloquear: 🚗 Transporte — faltan USD 84/mes"
- Freedom % pasa a stat secundario (top right)

**Metas — nueva lógica**
- Eliminados milestones abstractos (25%/50%/75%/100%)
- Roadmap concreto: para cada categoría pendiente muestra cuánto rendimiento mensual falta y cuánto capital habría que invertir
- Mini barra del juego: N/M categorías desbloqueadas
- InvestmentStreak: calendario de 12 meses + badges por racha

**Backend — gamificación**
- Nuevo endpoint `GET /portfolio/gamification` — retorna portfolio_covers + streak calendar
- Streak calendar: 7 meses de historial real (snapshot_dates distribuidos en seed)
- `smart_recommendations.py`: scoring engine con datos de mercado en tiempo real (dolarapi + BCRA)

**Fixes técnicos**
- Centralizacion de `NEXT_PUBLIC_API_URL` — eliminados 4 hardcoded `localhost:8007/8005`
- LECAP yield corregido a 68% TNA en seed, DB y iol_client
- Posiciones inactivas activadas (5 de 7 estaban `is_active=False`)
- `formatARS` local eliminada de 3 componentes

**Demo automatizado**
- `scripts/demo.js` — Playwright navega la app en viewport de iPhone 14 Pro
- Pauses interactivas con ENTER para grabar con Loom

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|-----|-------|-----|
| Racha siempre = 1 mes | Todas las posiciones con snapshot_date = today | Spread de fechas en DB: Sep-Mar |
| Rendimiento USD 34 en lugar de USD 175 | 5 posiciones con is_active=False | Activadas en DB |
| Yields distintos para LECAP | seed=0.40, iol_client=0.35, smart_recs=0.68 | Unificado a 0.68 en todos |
| Dos procesos uvicorn en 8007 | Kill fallaba con PID incorrecto en bash | Stop-Process de PowerShell |

### Decisiones técnicas

- **Nexo Platform vs Pro**: el usuario usa la app regular de Nexo (no Pro). Nexo Platform no tiene API pública. Decisión: marcar como pendiente entrada manual de cripto, no invertir más tiempo en auth Nexo.
- **Racha con snapshot_date como proxy**: solución rápida aceptable para demo. Para producción se necesita tabla `investment_months` con un registro por mes confirmado.
- **Freedom % como secundario**: el % abstracto no genera engagement. El "portafolio paga X categorías" es la métrica gamificable correcta.

### Estado actual

App funcional y demostrable. Portafolio mock con 7 posiciones activas (GGAL, MSFT, AL30, LECAP, BTC, USDT, CASH_ARS). Racha de 7 meses. Rendimiento USD 175/mes. Smart recommendations funcionando con datos de mercado en tiempo real.

---

## Sesión v0.3.0 — anterior

- IOL connect flow — credenciales, auth, sync de portafolio real
- Integrations settings page
- CORS fix (wildcard)

---

## Sesión v0.2.0 — anterior

- Arquitectura multi-usuario Supabase
- Modelos broker/crypto protocols
- CI/CD GitHub Actions
