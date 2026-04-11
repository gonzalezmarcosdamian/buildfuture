# Sistema de Tenencia (Portfolio Graph) — Documento de Resiliencia

> Última revisión: 2026-04-11  
> Contexto: arquitectura viva — actualizar cada vez que cambia la lógica de snapshots.

---

## ¿Qué es la "tenencia"?

El gráfico de tenencia muestra el valor total del portafolio (en USD) a lo largo del tiempo. Su fuente de verdad es la tabla **`portfolio_snapshots`** — un registro por usuario por día.

```
portfolio_snapshots
├── id
├── user_id
├── snapshot_date      ← clave
├── total_usd          ← lo que muestra el gráfico
├── monthly_return_usd
├── positions_count
├── cost_basis_usd
└── fx_mep
```

Detrás de cada snapshot diario vive el detalle por instrumento en **`position_snapshots`** (un registro por usuario/ticker/día). Esta tabla es la memoria histórica de cada posición y es **crítica** para reconstruir la historia de Cocos y Manual.

---

## Fuentes y su capacidad histórica

| Fuente | Historia disponible | Mecanismo | Limitación |
|--------|--------------------|-----------|----|
| **IOL** | Hasta 730 días | `get_operations()` → `historical_reconstructor.py` | Solo tickers activos hoy (vendidos = sin historia) |
| **Binance** | Últimos 30 días | `GET /sapi/v1/accountSnapshot` → `_sync_binance_history()` | Ventana fija de 30 días desde la API |
| **Cocos** | Desde el primer sync | `PositionSnapshot` acumulados en cada sync diario | Sin API de operaciones — solo lo que se grabó |
| **Manual (CASH, REAL_ESTATE)** | Desde la fecha de ingreso | `_snapshot_after_manual_change()` crea PositionSnapshot en el momento de create/update/delete | Sin historia previa a la fecha de entrada |

---

## Quién crea los `portfolio_snapshots`

### 1. `GET /portfolio/history` (portfolio.py)
- **Crea o actualiza** el snapshot de HOY en cada llamada.
- También graba un `PositionSnapshot` por cada posición activa.
- Es el único mecanismo que siempre tiene el estado más fresco.
- **El frontend lo llama cuando el usuario abre el gráfico.**

### 2. Scheduler (scheduler.py, 17:30 ART L-V)
- Crea el snapshot de hoy si no existe.
- **⚠️ Si ya existe → SKIP.** No actualiza. Cambios post-17:30 se pierden hasta el día siguiente o hasta que el usuario abra el gráfico.

### 3. `repair-user` (admin.py) — flujo unificado de 5 pasos
1. Purgar todos los `portfolio_snapshots` del usuario.
2. Re-sync IOL → reconstruir histórico desde operaciones (hasta 730 días).
3. Binance `accountSnapshot` → sumar 30 días de historia (upsert aditivo).
4. Backfill non-IOL: para cada snapshot histórico, sumar el valor de posiciones Cocos/Manual usando `PositionSnapshot` exactos por fecha + `first_seen` como límite de inicio.
5. Crear/actualizar snapshot de HOY con todas las posiciones activas.

---

## Los 3 invariantes que deben cumplirse siempre

### Invariante 1: Cada posición no-IOL debe tener un `PositionSnapshot` desde su fecha real de inicio

**Cocos:** `_sync_cocos()` → **NO crea `PositionSnapshot`** explícitamente. Los `PositionSnapshot` de Cocos los crea `GET /portfolio/history` en cada visita. Esto significa que si el usuario nunca abre el gráfico, no hay registro histórico.

**Manual:** `create_manual_position()` → **NO crea `PositionSnapshot`**. El primer snapshot se crea la próxima vez que el usuario abre el gráfico.

**Binance:** `_sync_binance()` → **NO crea `PositionSnapshot`**. Solo `_sync_binance_history()` crea `PortfolioSnapshots` directamente (no `PositionSnapshot`).

**Regla de oro:** Para que `backfill-non-iol` funcione correctamente, debe existir al menos un `PositionSnapshot` para cada posición no-IOL. Ese snapshot es la "memoria" que prueba desde cuándo existía la posición y a qué valor.

### Invariante 2: `repair-user` después de cualquier evento que altere el histórico

Eventos que requieren `repair-user`:
- Conectar una nueva integración (IOL, Cocos, Binance).
- Reconectar una integración (credenciales renovadas).
- Agregar o eliminar una posición manual.
- Detectar que el gráfico muestra un pico o valor falso.
- Purgar snapshots por cualquier razón.

`repair-user` es idempotente: se puede correr N veces sin efecto acumulativo.

### Invariante 3: El snapshot de HOY debe reflejar TODAS las fuentes activas

El scheduler solo corre una vez a las 17:30. Si el usuario tiene cambios después de esa hora, el snapshot del día no se actualiza hasta la próxima visita al gráfico.

`GET /portfolio/history` siempre actualiza el snapshot de hoy → esto es correcto y suficiente mientras el usuario abra el gráfico al menos una vez por día.

---

## Flujo de vida correcto de una posición nueva

### Posición IOL (automática)
```
Sync IOL (scheduler/manual)
  → _sync_iol() crea/actualiza Position(source=IOL)
  → Nada más en el momento

Usuario abre gráfico → GET /portfolio/history
  → Crea PositionSnapshot(ticker, hoy, value_usd)
  → Crea/actualiza PortfolioSnapshot(hoy, total_usd)
  → IOL tiene historia completa desde operaciones (vía historical_reconstructor)
```

### Posición Cocos (automática)
```
Sync Cocos (scheduler/manual)
  → _sync_cocos() crea Position(source=COCOS, snapshot_date=hoy)
  → NO crea PositionSnapshot ← GAP

Usuario abre gráfico → GET /portfolio/history
  → Crea PositionSnapshot(ticker, hoy, value_usd) ← primer registro histórico
  → Crea/actualiza PortfolioSnapshot(hoy, total_usd)

Día siguiente, usuario abre gráfico
  → PositionSnapshot(ticker, mañana, value_usd)
  → ... se acumula día a día

repair-user invocado
  → backfill-non-iol usa el primer PositionSnapshot como first_seen
  → Cocos aparece en el gráfico desde ese primer día, NO antes
```

### Posición Manual (CASH, REAL_ESTATE)
```
create_manual_position() llamado
  → Position(snapshot_date=hoy) creada
  → NO crea PositionSnapshot ← GAP
  → NO actualiza portfolio_snapshot de hoy ← GAP

Usuario abre gráfico → GET /portfolio/history
  → Crea PositionSnapshot(ticker, hoy, value_usd) ← primer registro histórico
  → Crea/actualiza PortfolioSnapshot(hoy, total_usd)
  → Posición aparece en el gráfico desde HOY en adelante
```

### Posición Binance (automática)
```
Sync Binance
  → _sync_binance() crea Position(source=BINANCE, snapshot_date=hoy)
  → _sync_binance_history() crea PortfolioSnapshots aditivos (30 días)
  → NO crea PositionSnapshot ← GAP (Binance usa PortfolioSnapshot directo)

Usuario abre gráfico → GET /portfolio/history
  → Crea PositionSnapshot(ticker, hoy, value_usd)
  → Crea/actualiza PortfolioSnapshot(hoy, total_usd)
```

---

## Bugs conocidos (P0 — rompen el gráfico)

### BUG-1: `_sync_cocos` no crea `PositionSnapshot` al sincronizar
- **Archivo:** `routers/integrations.py:1785`
- **Impacto:** Si el usuario no abre el gráfico el mismo día que conecta Cocos, ese día queda sin registro. `backfill-non-iol` no puede reconstruir ese día.
- **Fix:** Agregar creación de `PositionSnapshot` al final de `_sync_cocos()`.

### ~~BUG-2: `create_manual_position` no crea `PositionSnapshot` ni actualiza snapshot de hoy~~ ✅ RESUELTO 2026-04-11
- `_snapshot_after_manual_change()` en `positions.py` — llama `save_position_snapshots` + `_refresh_today_snapshot` tras create/update/delete.
- Toda mutación manual ahora dispara upsert de PositionSnapshot y PortfolioSnapshot de hoy inmediatamente.

### BUG-3: Scheduler skippea snapshot existente
- **Archivo:** `scheduler.py` (~línea 426)
- **Impacto:** Cambios post-17:30 (sync manual, nueva posición) no se reflejan hasta el día siguiente o próxima visita al gráfico.
- **Fix:** Scheduler debería hacer upsert (UPDATE si existe) en lugar de skip.

### BUG-4: `_sync_binance` no crea `PositionSnapshot`
- **Archivo:** `routers/integrations.py:1996`
- **Impacto:** Binance no acumula historia granular por ticker — solo el total agregado vía `_sync_binance_history`. Si el usuario tiene múltiples assets Binance y quiere ver el breakdown, no hay datos históricos por ticker.
- **Fix:** Agregar creación de `PositionSnapshot` al final de `_sync_binance()`.

---

## Protocolo de recuperación (cuando el gráfico está mal)

**NUNCA hacer solo DELETE de snapshots.** Siempre seguir este flujo:

```
POST /admin/support/repair-user/{user_id}
```

Ese endpoint en un solo llamado:
1. Purga `portfolio_snapshots`.
2. Re-sync IOL + reconstrucción histórica.
3. Binance 30d history.
4. Backfill non-IOL (Cocos/Manual) con valores reales de `PositionSnapshot`.
5. Snapshot de hoy con todas las fuentes.

Si el gráfico sigue mal después de `repair-user`, verificar:
- ¿Hay `PositionSnapshot` para las posiciones no-IOL? `SELECT * FROM position_snapshots WHERE user_id = '...' ORDER BY snapshot_date`
- ¿La posición Cocos/Manual fue vista al menos una vez vía GET /portfolio/history antes de correr repair-user?

---

## Arquitectura del `backfill-non-iol`

El algoritmo correcto (implementado post 2026-04-11):

```python
# Para cada snapshot histórico de IOL (fecha D):
for snap in historical_snapshots:
    offset = 0
    for ticker, pos in non_iol_positions.items():
        start_date = first_seen.get(ticker)  # MIN(PositionSnapshot.snapshot_date)
        if start_date > snap.snapshot_date:
            continue  # Esta posición no existía en fecha D
        # Usar valor exacto del día si existe; valor actual como fallback
        val = pos_snap_index.get((ticker, snap.snapshot_date), float(pos.current_value_usd))
        if val > 0:
            offset += val
    if offset > 0:
        snap.total_usd += Decimal(str(round(offset, 2)))
```

**Por qué `first_seen = MIN(PositionSnapshot.snapshot_date)` y no `Position.snapshot_date`:**  
`Position.snapshot_date` se actualiza en cada sync → refleja el ÚLTIMO sync, no el primero. `MIN(PositionSnapshot.snapshot_date)` es inmutable y refleja la fecha real de la primera observación.

---

## Resumen: qué perpetuar para que el gráfico sea confiable

| Qué | Cómo | Cuándo |
|-----|------|--------|
| `PositionSnapshot` de Cocos al sincronizar | Fix BUG-1 en `_sync_cocos` | Próximo sprint |
| `PositionSnapshot` + snapshot-hoy al crear/editar/borrar manual | ✅ Implementado — `_snapshot_after_manual_change()` en positions.py | 2026-04-11 |
| Scheduler hace upsert (no skip) en snapshot existente | Fix BUG-3 en `scheduler.py` | Próximo sprint |
| `repair-user` después de reconectar cualquier integración | Documentado — flujo actual ya lo resuelve | HOY ✅ |
| `PositionSnapshot` de Binance al sincronizar | Fix BUG-4 en `_sync_binance` | Baja prioridad (Binance ya tiene 30d vía PortfolioSnapshot) |
