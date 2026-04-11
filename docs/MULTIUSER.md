# Multi-usuario — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

BuildFuture soporta múltiples usuarios. No hay tabla `users` propia — los `user_id` emergen de Supabase Auth y aparecen en las demás tablas (positions, portfolio_snapshots, integrations, etc.) cuando el usuario empieza a usar la app.

---

## Onboarding de usuario nuevo

### Problema original (2026-04-01)
Un usuario nuevo veía la sección "DISPONIBLES" vacía en Config porque los registros IOL/PPI solo existían para el seed user.

### Solución implementada: dos mecanismos complementarios

**1. Lazy creation en `GET /integrations`** (`integrations.py`)
Si el usuario no tiene ningún registro de integración, se crean IOL y PPI automáticamente en ese request. Cubre el 99% de los casos: el usuario va a Config antes que a cualquier otra sección.

**2. Startup backfill en `_backfill_integrations()`** (`main.py`)
Al arrancar el servidor, escanea todos los `user_id` únicos en `positions` y crea los registros IOL/PPI faltantes. Cubre usuarios que existían antes de que el lazy-creation se implementara.

```python
# main.py — al arrancar
_backfill_integrations()  # crea registros IOL/PPI para usuarios sin integrations
```

---

## Usuarios conocidos

| Usuario | ID | Rol |
|---------|-----|-----|
| Marcos González | `f94d61c1-1b59-438c-bc79-a66139028c94` | Usuario principal (prod) |
| Damián (seed/admin) | `00000000-0000-0000-0000-000000000001` | Seed / testing |

---

## Aislamiento de datos

Toda operación de DB se filtra por `user_id`. No hay datos compartidos entre usuarios excepto:
- Caché de precios (`price_history` por ticker) — compartida entre usuarios, sin datos personales
- Caché MEP — global, sin datos personales

---

## Agregar nuevas integraciones por defecto

Si se agrega una nueva integración que debe aparecer disponible para todos los usuarios nuevos (ej. NEXO), agregarla a `_DEFAULT_INTEGRATIONS` en **dos lugares**:

```python
# main.py — para el startup backfill
_DEFAULT_INTEGRATIONS = ["IOL", "PPI", "NUEVA_INTEGRACION"]

# integrations.py — para el lazy creation en GET /integrations
_DEFAULT_INTEGRATIONS = ["IOL", "PPI", "NUEVA_INTEGRACION"]
```

**Por qué dos lugares:** usuarios completamente nuevos (sin posiciones) no son cubiertos por el backfill de startup (que itera sobre `positions`). Solo el lazy en `GET /integrations` los cubre. Esto es correcto: un usuario sin posiciones llega a Config antes que a Portfolio.

---

## Scheduler y multi-usuario

El scheduler corre para todos los usuarios con integraciones activas. El job de sync global itera sobre todos los `user_id` con `auto_sync_enabled=True` en sus integraciones.

**Consideraciones de escala:**
- Con muchos usuarios, el sync global puede tardar → evaluar paralelismo o cola de jobs
- Los errores de un usuario no deben detener el sync de los demás (try/except por usuario)
