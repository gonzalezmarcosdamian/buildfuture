# Snapshots — BuildFuture

> Última revisión: 2026-04-11  
> Ver también: `docs/TENENCIA.md` — arquitectura completa del gráfico de tenencia.

---

## Estado actual

El sistema de snapshots persiste el estado del portafolio en el tiempo. Dos tablas:

| Tabla | Granularidad | Uso |
|-------|-------------|-----|
| `portfolio_snapshots` | 1 fila / usuario / día | Fuente del gráfico de tenencia |
| `position_snapshots` | 1 fila / usuario / ticker / día | Detalle por instrumento, fuente del backfill histórico de Cocos/Manual |

---

## Quién crea cada snapshot

### `portfolio_snapshots`

| Creador | Cuándo | Comportamiento |
|---------|--------|---------------|
| `GET /portfolio/history` | Cada vez que el usuario abre el gráfico | **Upsert** — crea o actualiza hoy |
| Scheduler (17:30 ART L-V) | Una vez por día | **Solo crea** si no existe — SKIP si ya hay uno de hoy |
| `repair-user` (admin) | Invocado manualmente | **Purga y reconstruye** todo el histórico |
| `_snapshot_after_manual_change()` | Al crear/editar/borrar posición manual | **Upsert** — actualiza hoy con todas las posiciones activas |

### `position_snapshots`

| Creador | Cuándo |
|---------|--------|
| `GET /portfolio/history` → `save_position_snapshots()` | Cada vez que el usuario abre el gráfico |
| `_snapshot_after_manual_change()` | Al crear/editar/borrar posición manual |

**GAPs actuales (bugs conocidos):**
- `_sync_cocos()` NO crea `PositionSnapshot` — solo lo hace GET /portfolio/history
- `_sync_binance()` NO crea `PositionSnapshot` por ticker

---

## Scheduler — flujo diario

```
17:30 ART (L-V)
  ├─ _save_portfolio_snapshot()
  │   ├─ Si snapshot de hoy existe → SKIP  ← BUG-3: debería hacer UPDATE
  │   └─ Si no existe → CREATE con posiciones actuales
  ├─ _update_yields(db, mep)
  └─ _sync_all_users()  (si habilitado)
```

**BUG-3:** El scheduler skipea si ya existe snapshot de hoy. Si el usuario agregó una posición después de las 17:30, el snapshot del día no la incluye hasta la próxima visita al gráfico o hasta el día siguiente.

---

## repair-user — flujo unificado

El endpoint `POST /admin/support/repair-user?user_id=` ejecuta en un solo llamado:

```
1. Purgar todos los portfolio_snapshots del usuario
2. Re-sync IOL → reconstrucción histórica desde operaciones (hasta 730 días)
3. _sync_binance_history() → sumar 30 días de historia Binance (upsert aditivo)
4. backfill non-IOL → para cada snapshot histórico, sumar Cocos/Manual
   usando PositionSnapshot exactos por fecha + first_seen como límite
5. Crear/actualizar snapshot de HOY con todas las posiciones activas
```

`repair-user` es **idempotente**: se puede correr N veces sin efecto acumulativo.

**Cuándo correrlo:**
- Al conectar una nueva integración
- Al detectar un spike o valor falso en el gráfico
- Al agregar o eliminar una posición manual significativa
- Al purgar snapshots por cualquier razón

---

## backfill-non-iol — algoritmo

```python
# Para cada portfolio_snapshot histórico de IOL (fecha D):
for snap in historical_snapshots:
    offset = 0
    for ticker, pos in non_iol_positions.items():
        # first_seen = MIN(PositionSnapshot.snapshot_date) del ticker
        # NO usar Position.snapshot_date (refleja el ÚLTIMO sync, no el primero)
        start_date = first_seen.get(ticker, pos.snapshot_date)
        if start_date > snap.snapshot_date:
            continue  # Esta posición no existía en fecha D

        # Usar valor exacto del día si existe; valor actual como aproximación si no
        val = pos_snap_index.get((ticker, snap.snapshot_date), float(pos.current_value_usd))
        if val > 0:
            offset += val

    if offset > 0:
        snap.total_usd += Decimal(str(round(offset, 2)))
```

**Por qué `first_seen = MIN(PositionSnapshot.snapshot_date)` y no `Position.snapshot_date`:**  
`Position.snapshot_date` se actualiza en cada sync → refleja el ÚLTIMO sync. `MIN(PositionSnapshot.snapshot_date)` es inmutable y refleja la primera observación real.

---

## Comandos de soporte

```bash
BACKEND="https://api-production-7ddd6.up.railway.app"
ADMIN_KEY="8URlXkc8Xmz4p2oCBGG2mYklSxAmcqSk2AzgzbfuY4A"
USER_ID="f94d61c1-1b59-438c-bc79-a66139028c94"  # Marcos

# Flujo completo de reparación (siempre este primero)
curl -X POST "$BACKEND/admin/support/repair-user?user_id=$USER_ID" \
  -H "X-Admin-Key: $ADMIN_KEY"

# Solo backfill non-IOL (si repair-user ya corrió y solo faltan Cocos/Manual)
curl -X POST "$BACKEND/admin/support/backfill-non-iol?user_id=$USER_ID" \
  -H "X-Admin-Key: $ADMIN_KEY"

# Solo snapshot de hoy (útil si hubo cambios manuales post-scheduler)
curl -X POST "$BACKEND/admin/support/force-snapshot-today?user_id=$USER_ID" \
  -H "X-Admin-Key: $ADMIN_KEY"

# Verificar salud del historial
curl "$BACKEND/admin/support/snapshot-health?user_id=$USER_ID" \
  -H "X-Admin-Key: $ADMIN_KEY"

# Ver valores USD del historial
curl "$BACKEND/admin/snapshots/values?user_id=$USER_ID&limit=30" \
  -H "X-Admin-Key: $ADMIN_KEY"
```

---

## Bugs conocidos

| # | Bug | Severidad | Archivo |
|---|-----|-----------|---------|
| BUG-1 | `_sync_cocos` no crea `PositionSnapshot` al sincronizar | P1 | integrations.py:1785 |
| BUG-3 | Scheduler skipea snapshot existente → cambios post-17:30 no se reflejan hasta próxima visita | P1 | scheduler.py:~426 |
| BUG-4 | `_sync_binance` no crea `PositionSnapshot` por ticker | P2 | integrations.py:1996 |

BUG-2 (`create_manual_position` no actualizaba snapshot) → **RESUELTO 2026-04-11** via `_snapshot_after_manual_change()`.

---

## Cambios recientes

| Fecha | Cambio |
|-------|--------|
| 2026-04-11 | `_snapshot_after_manual_change()`: create/update/delete manual dispara PositionSnapshot + PortfolioSnapshot de hoy |
| 2026-04-11 | `repair-user` unificado: IOL + Binance 30d + backfill non-IOL + hoy en un solo endpoint |
| 2026-04-11 | `backfill-non-iol`: usa `MIN(PositionSnapshot.snapshot_date)` como `first_seen` — ya no retroactivo |
| 2026-04-11 | `_sync_binance_history()`: crea `PortfolioSnapshot` aditivos para 30 días de historia |
