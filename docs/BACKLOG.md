# Backlog — BuildFuture

> Pendientes vivos al 2026-06-02. Generado tras una tanda de fixes de auth/performance + testing E2E.
> Ver features hechas en [PRODUCTO.md](./PRODUCTO.md) y aprendizajes en [LEARNINGS.md](./LEARNINGS.md).

---

## 🔴 Bugs / deuda a corregir

### Tests
- [ ] **`seed_mock.py` roto** — `_pos()` pasa `performance_pct` y `current_value_usd` (properties read-only de `Position`, sin setter) al constructor → `AttributeError` al arrancar con `MOCK_SEED=true`. Bloquea seedear personas de QA. Quitar esos kwargs computados del dict de `_pos()`.
- [ ] **E2E `06-mobile-ux:176` (FTU portfolio vacío) — falso positivo**: la aserción `text=/500|error interno/i` matchea "500.000 u." (cantidad de un LECAP), no un error. Ajustar el regex (ej: `/error interno|status.*500/i`) o scopearlo.
- [ ] **E2E `05-portfolio-detail:9`** (navegar a instrumento desde portfolio) — falla, investigar si es bug real de navegación o dato/entorno.
- [ ] **E2E `06-mobile-ux:114`** (touch targets en botones de acción de portfolio) — falla, verificar tamaño mínimo de tap targets o selector del test.

### CI / suite backend (preexistente)
- [ ] **Ruff CI en rojo** — ~94 errores en `backend/app` (E712 `== True` de SQLAlchemy + archivos sin `ruff format`), sin config de ruff. Agregar `ruff.toml` que ignore E712 en queries + correr `ruff format` global.
- [ ] **8 tests backend fallan en `main`** (preexistente): `test_cash_positions` (5), `test_manual_crypto_restate` (3) — ej. `PortfolioSnapshot` sin `current_value_ars`. Más `test_byma_client` (2): TEA fuera de rango `201.51`.

---

## ⚡ Performance (siguiente vuelta)

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
