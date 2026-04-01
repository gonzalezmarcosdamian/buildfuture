# Bitácora BuildFuture

---

## v0.10.0 — 2026-04-01

### Objetivo
Mejorar la sección "Dónde invertir" (recomendaciones), agregar auto-sync de IOL, y solidificar el flujo de trabajo de desarrollo con CI y checklist de deploy.

---

### Cambios por módulo

#### Recomendaciones — frontend
- **Carousel horizontal**: `overflow-x-auto snap-x snap-mandatory`, cards de `58vw`, swipeable en mobile
- **Cards más compactas**: layout vertical con yield prominente (32px bold), fila "Invertir $X → +$Y/mes" contextualiza el retorno sobre el capital asignado
- **Modal ℹ por card**: bottom sheet vía `createPortal(document.body)` con rationale completo, "por qué ahora", y barra de convicción por agente del comité
- **Tab "para vos"**: tab del perfil del usuario con `bg-blue-600` cuando seleccionado, borde azul cuando no; texto "para vos ✦"
- **Fix crítico**: FTU guardaba `"moderate"` (inglés) pero los tabs comparaban contra `"moderado"` (español) → nunca matcheaban. Corregido en FTU (`conservative/moderate/aggressive` → `conservador/moderado/agresivo`) + normalización PROFILE_MAP en el componente para usuarios con valor legacy en DB

#### Recomendaciones — backend (expert_committee.py)
- **5 recomendaciones por perfil** (antes 3): `_pick_by_slots` expandido con slots estructurados + `fill_remaining`
- **AgenteMacro** (5to agente, peso 0.15): detecta régimen macro — "normalización" (riesgo_país < 800, spread < 10%) vs "estrés". Ajusta scores de todos los instrumentos transversalmente
- **2 nuevos instrumentos** (universo: 9 → 11):
  - `YCA6O`: YPF ON USD 2026 — hard dollar, renta fija privada, 8.5% TIR
  - `VIST`: Vista Energy CEDEAR — beta alto a Vaca Muerta, 22% upside estimado
- **Capital como penalidad suave** (0.25×) en lugar de exclusión dura: siempre aparecen 4+ recomendaciones independientemente del capital disponible

#### Auto-sync IOL (portfolio.py)
- `_auto_sync_iol(user_id)`: background task que sincroniza IOL si `last_synced_at > 60 min`
- Inyectado vía `BackgroundTasks` en `GET /portfolio/` y `GET /portfolio/freedom-score`
- No bloquea la respuesta: el usuario ve datos actuales y el sync corre después
- Usa su propia sesión de DB (`SessionLocal()`) para no interferir con la request

#### Desconectar integración
- Backend: `POST /integrations/iol/disconnect` — limpia credenciales, `is_connected = False`, soft-delete de todas las posiciones IOL del usuario
- Frontend: botón "Desconectar" en `IntegrationCard` con modal de confirmación (ícono AlertTriangle, Cancel + Desconectar)

#### Dashboard — racha de inversión
- `InvestmentStreak` movida de `/goals` a `/dashboard` (entre presupuesto y recomendaciones)
- Removida de `/goals`

#### Workflow y CI
- GitHub Actions: `pr-checks.yml` en ambos repos (ruff + bandit backend; tsc + eslint + build frontend)
- `CLAUDE.md` con reglas del equipo: feature branches, PR flow, no deploy sin autorización
- Checklist pre-deploy guardado en memoria (python import check, tsc, ruff, SHA 40 chars, db.rollback)

---

### Bugs encontrados y resueltos

| Bug | Causa | Fix |
|---|---|---|
| Tab "Moderado" nunca resaltado | FTU guardaba `"moderate"`, tabs comparaban `"moderado"` | Corregir FTU + PROFILE_MAP de normalización |
| Modal ℹ no aparecía | `fixed` position atrapado por `overflow-x-auto` del carousel | `createPortal(document.body)` + `z-[999]` |
| Retorno sin contexto (`+$2/mes`) | No se mostraba sobre qué capital se calculaba | Fila "Invertir $X USD → +$Y USD/mes" en cada card |
| 3 recs en lugar de 5 | Backend con 5 slots no estaba deployado | Merge PR #3 + deploy Railway |
| Push directo a master | Fix urgente de 1 línea, bajé la guardia | **Error de proceso** — ver decisiones pendientes |

---

### Decisiones técnicas
- Retorno estimado calculado sobre el monto asignado a ese instrumento específico (no sobre el capital total). Es más preciso pero requiere que el usuario entienda que la suma de todos los retornos es el retorno total.
- Auto-sync con umbral de 60 min es suficiente para datos de mercado del día; podría ajustarse a 30 min si se desea más frescura sin sobrecargar la API de IOL.

---

### Estado al cierre de sesión
- Prod: v0.10.0 backend en Railway, frontend en Vercel
- Carousel funcional con 5 recomendaciones por perfil, tab "Moderado" destacado correctamente
- Auto-sync activo: cada vez que el usuario abre dashboard o portafolio, IOL se sincroniza si hay datos > 60 min

---

## v0.9.0 — 2026-03-31

### Objetivo
Estabilización post-crisis de producción, pipeline de CI, y mejoras UX en portafolio e integraciones.

### Cambios principales
- Fix crítico: FCI precio en ARS guardado como USD → portafolio mostraba $73B. Fix: dividir VCP/MEP
- Fix: `PendingRollbackError` sin `db.rollback()` en except → app caía en cascada
- Startup cleanup: `_purge_bad_manual_positions()` desactiva posiciones manuales con valor > $10M USD
- IOL sync: MEP histórico por ticker, CCL implícito para CEDEARs
- Posición manual en portafolio: grisada con "Próximamente"
- ArgentinaDatos FCI: caché 15 min + `ThreadPoolExecutor(max_workers=5)` para fetch paralelo
- GitHub Actions CI en ambos repos
- `logger = logging.getLogger(...)` a nivel módulo (fix `NameError` en startup)

---

## v0.8.0 — anterior

Base del proyecto: portafolio IOL, freedom bar, presupuesto, gamificación, FTU flow.
