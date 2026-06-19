# Backlog — BuildFuture

> Pendientes vivos al 2026-06-02. Generado tras una tanda de fixes de auth/performance + testing E2E.
> Ver features hechas en [PRODUCTO.md](./PRODUCTO.md) y aprendizajes en [LEARNINGS.md](./LEARNINGS.md).

---

## 🔴 Bugs / deuda a corregir

### Tests
- [x] ~~8 tests backend rojos~~ **RESUELTO 2026-06-18**: cash_positions, manual_crypto_restate, byma_client, freedom_calculator, portfolio_router, yield_updater, argentinadatos. Suite backend **458 passed, 0 failed**. Incluyó fix de bug real (REAL_ESTATE yield_currency).
- [x] ~~3 E2E rojos~~ **RESUELTO 2026-06-18**: portfolio-detail (navegación robusta), mobile-ux (regex de error + auditoría touch targets ≥36-44px). Suite E2E mobile-chrome **39/39**.
- [x] ~~Sin unit tests frontend~~ **RESUELTO 2026-06-18**: vitest configurado + tests de formatters (9). Falta ampliar cobertura de componentes.
- [ ] **`seed_mock.py` roto** — `_pos()` pasa `performance_pct`/`current_value_usd` (properties read-only) al constructor → `AttributeError` con `MOCK_SEED=true`. Quitar esos kwargs computados.
- [ ] **Tests de `integrations` sync** (mapeo de posiciones por broker) — sigue sin cobertura directa (router más grande).
- [ ] **Ampliar unit tests frontend** — vitest ya está; falta testear componentes/hooks clave (auth-context, currency-context, helpers de PerformanceChart).

### CI / lint (preexistente)
- [ ] **Ruff CI en rojo** — ~94 errores en `backend/app` (E712 `== True` de SQLAlchemy + archivos sin `ruff format`), sin config de ruff. Agregar `ruff.toml` que ignore E712 en queries + `ruff format` global. (Nota: el CI no lintea `tests/`.)

---

## ⚡ Performance (siguiente vuelta)

- [ ] **Deprecación de snapshots (BLOQUEADA — son load-bearing)** — Hallazgo 2026-06-18: NO borrar `PositionSnapshot` todavía. Además del gráfico de tenencia, los leen: `yield_calculator_v2` (rendimiento observado por instrumento) y el endpoint `positions/delta` (toda la vista de Rendimiento). Borrarlos rompería yields + rendimiento. **Ruta segura por etapas**: (1) desacoplar `yield_calculator_v2` y `positions/delta` de `PositionSnapshot` (usar price store / fuente alternativa); (2) recién entonces deprecar la acumulación de snapshots para fuentes sin movimientos. La confusión del usuario YA está resuelta en la UI (gráfico honesto), así que esto pasó a ser limpieza interna de baja urgencia.
- [ ] **Cold-start devaluación ~18s** — mitigado con pre-warm al startup (sale del path del usuario), pero el fetch sigue tardando ~18s en background. Persistir el valor en DB para sobrevivir restarts, o acortar más la cadena ROFEX/BYMA (BYMA no es accesible desde Railway → es tiempo perdido).
- [ ] **Railway 1 solo worker de uvicorn** — las ~5 llamadas concurrentes del dashboard compiten. Subir `--workers` requiere primero **aislar APScheduler** (con N workers el scheduler corre N veces → jobs duplicados). Patrón: leader-election via advisory lock de Postgres.
- [ ] **Dashboard hace 5 llamadas separadas al backend** por carga (`budget`, `gamification`, `portfolio`, `profile`, `capital-goals`). Consolidar en 1-2 endpoints agregados.
- [ ] **Verificar región de Supabase** — se co-locaron las funciones de Vercel en `iad1` (junto a Railway us-east4). Si Supabase está en São Paulo, el `getUser()` del proxy quedó más lejos para usuarios logueados. Confirmar región y ajustar si hace falta.
- [ ] **Limpieza de observabilidad** — el `console.warn` del proxy y el `logger.info` del timing middleware quedaron como instrumentación. Evaluar bajarlos a nivel debug o gatearlos por env una vez estabilizado.

---

## 🔲 Features pendientes (de PRODUCTO.md)

- [ ] **Admin panel para crear usuarios** (baja prioridad). **Bloqueado**: requiere `SUPABASE_SERVICE_ROLE_KEY` (no configurado) para la Admin API. Probablemente superado por la iniciativa "Beta por invitación".
- [ ] **Beta por invitación** (en planificación, sin implementación). Ver [BETA_INVITE_PLAN.md](./BETA_INVITE_PLAN.md). Cuello: dominio + email provider + copy.

---

## 🧹 Hygiene

- [ ] **Bump del submodule `frontend` en `main`** — el repo backend quedó apuntando a un master anterior tras los últimos pushes directos. Bumpear el puntero para mantener sincronía (no afecta prod; Vercel deploya de su propio master).
- [ ] **Wrap-up de LEARNINGS.md** — quedó pendiente registrar la sesión (causa raíz del lag: hydration mismatch por emoji en `ticker[0]`; region co-location; cold-start devaluación). El cron diario 21:03 y el Weekly Learning Agent (domingos 17:00 ART) lo cubren, pero conviene una entrada manual de esta tanda.
