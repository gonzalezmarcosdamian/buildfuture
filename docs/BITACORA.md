# Bitácora BuildFuture

---

## Sesión v0.5.0 — 2026-03-30

### Objetivo
Conectar el comité de expertos al router, sincronizar el portafolio real de IOL, y calcular rendimiento en USD con tipo de cambio real al momento de compra.

### Cambios realizados

**Comité de expertos — wiring completo**
- `expert_committee.py` conectado al router como recomendador default (reemplaza `smart_recommendations`)
- Frontend `RecommendationList` muestra panel "Comité de expertos" con señal y convicción de cada agente
- Badges `agents_agreed` en la hero card muestran qué agentes acuerdan en la recomendación
- Universo corregido: eliminado S31O5 (venció Oct-2025), S15G6 → S31G6, YCA6O reemplazado por AL30

**Tickers reales IOL corregidos**
- G = Agosto en nomenclatura de LECAPs (no Junio)
- S15Y6 = LECAP 15/May/2026 (confirmado en IOL) — ticker corto plazo
- S31G6 = LECAP 31/Ago/2026 (confirmado en IOL, ya comprada por el usuario)

**Fix crítico: valuaciones ARS→USD**
- IOL devuelve todos los precios en ARS (no USD como asumíamos)
- `get_portfolio()` ahora usa `valorizado / cantidad / MEP` para precio real en USD
- LECAPs: IOL cotiza ppc per 100 nominales → ajuste `ppc/100` para precio por nominal
- `_get_mep()`: método propio que consulta dolarapi en tiempo real

**Persistencia robusta**
- Tabla `InvestmentMonth`: meses con inversión real desde operaciones IOL (reemplaza proxy snapshot_date)
- Tabla `PortfolioSnapshot`: snapshot diario de valor total del portafolio
- Scheduler APScheduler: job L-V 17:30 ART (cierre de mercado) — sync IOL + snapshot
- Backup automático: `backups/buildfuture_YYYY-MM-DD.db` antes de cada job, 30 días de retención
- `POST /admin/snapshot` para trigger manual

**Costo base y rendimiento real en USD**
- `Position.ppc_ars`: precio promedio de compra en ARS crudo (directo de IOL)
- `Position.purchase_fx_rate`: MEP/CCL al momento de compra
- `Position.cost_basis_usd`: costo base real = `quantity × ppc_ars / purchase_fx_rate`
- `Position.performance_pct`: rendimiento en USD usando costo base real
- Para CEDEARs: CCL implícito via Yahoo Finance — `equiv = round(nyse × mep / bcba)` → `ccl = bcba × equiv / nyse_at_purchase`
- Para LECAPs/bonos: MEP histórico via bluelytics
- Endpoint `/portfolio/` expone `cost_basis_usd`, `purchase_fx_rate`, `ppc_ars`

**UX**
- BudgetEditor: `useBruto = true` por defecto

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|-----|-------|-----|
| S31O5 como recomendación #1 | Venció Oct-2025, estaba en universo | Reemplazado por S15Y6 |
| Valuaciones ×1430 incorrectas | IOL da precios en ARS, usábamos como USD | `valorizado/cantidad/MEP` |
| LECAP cost_basis $34k en vez de $347 | ppc=101.85 aplicado por nominal sin dividir/100 | `asset_type=="LETRA"→ppc/100` |
| Columnas faltantes en DB | `create_all` no altera tablas existentes | `ALTER TABLE` manual via sqlite3 |
| Servidor sin recargar cambios | Uvicorn sin `--reload` y proceso viejo activo | Restart + PowerShell kill |

### Decisiones técnicas

- **CCL implícito desde Yahoo Finance**: IOL endpoints de cotización devuelven 500 fuera de horario de mercado. Alternativa: Yahoo Finance para precio NYSE (sin auth) + ratio derivado de precios actuales.
- **Ratio CEDEAR derivado**: `equiv = round(nyse_price × mep / bcba_price)`. No requiere CNV lookup. Para QQQ calculó equiv=19, CCL_implícito=$1,406 (vs MEP $1,430).
- **Scheduler in-process**: APScheduler BackgroundScheduler. Apropiado para uso personal local. Limitación: no captura si el servidor está apagado a las 17:30.

### Estado actual

Portafolio real sincronizado: QQQ (2 CEDEARs, $58 USD), S15Y6 ($347 USD), S31G6 ($278 USD). Total $683 USD. FCI pendiente de liquidación. Rendimiento mensual: $35.95/mes. MEP en tiempo real: $1,432.

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
