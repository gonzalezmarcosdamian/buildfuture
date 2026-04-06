# Prompt: Análisis de Tarea — Iteración de Backlog BuildFuture

> Usar este prompt cada vez que surge una tarea nueva O cuando se itera el backlog existente.
> Objetivo: salir con un ítem listo para implementar — sin ambigüedades, sin sorpresas en prod,
> con riesgos identificados y decisiones de arquitectura tomadas antes de tocar código.

---

## Prompt base

```
Sos el analista técnico del producto BuildFuture.
Stack: Next.js 15 (App Router, TypeScript) · FastAPI (Python) · Supabase (PostgreSQL) · Railway (backend) · Vercel (frontend).
Patrones actuales del proyecto: services/ para lógica de negocio, routers/ para HTTP, modelos SQLAlchemy, Alembic para migrations, authFetch() en frontend, MEP centralizado en services/mep.py.

Tarea / idea / bug a analizar:
[DESCRIBIR LA TAREA AQUÍ]

Analizala en profundidad como analista antes de cargarla al backlog.
Respondé cada sección. Marcá con ❓ lo que necesita decisión antes de implementar.
Marcá con ⚠️ los riesgos que podrían causar regresión o pérdida de datos.

---

## 1. Problema y motivación
- ¿Qué problema resuelve o qué oportunidad captura?
- ¿Quién lo sufre, con qué frecuencia, qué impacto tiene?
- ¿Qué pasa si no lo hacemos? ¿Se agrava con el tiempo?

## 2. Criterios de aceptación
Lista de checks concretos y verificables. Cada uno tiene que poder responderse "pasó / no pasó" sin interpretación.
- [ ] ...

## 3. Capas impactadas
Para cada capa indicá si aplica, qué archivos se tocan y qué tipo de cambio es (nuevo / modificar / eliminar).

| Capa | ¿Aplica? | Archivos / módulos | Tipo de cambio |
|------|----------|--------------------|----------------|
| BE · `routers/` | | | |
| BE · `services/` | | | |
| BE · `models.py` | | | |
| FE · `components/` | | | |
| FE · `app/(app)/` | | | |
| FE · `app/(landing)/` | | | |
| DB · migration Alembic | | | |
| TEST · pytest | | | |
| TEST · frontend | | | |
| COPY · in-app | | | |
| COPY · landing | | | |
| INFRA · env vars / Railway / Vercel | | | |

## 4. Retrocompatibilidad
- ¿Los usuarios con datos existentes en prod van a ver algo roto o distinto sin hacer nada?
- ¿El nuevo schema de DB es compatible con la versión anterior del backend durante el deploy (ventana de downtime)?
- ¿Hay posiciones, metas, presupuestos o syncs ya creados que necesiten migración de datos, no solo de schema?
- ¿El cambio en un endpoint rompe algún cliente que ya lo consume (frontend, scheduler, scripts)?
- Si hay un rollback, ¿los datos escritos por la nueva versión siguen siendo válidos con la versión anterior?

## 5. Afectación a otros módulos
Listar cada módulo del sistema y evaluar si esta tarea lo toca indirectamente.

| Módulo | ¿Afectado? | Cómo |
|--------|------------|------|
| Scheduler / sync automático IOL/PPI/Cocos | | |
| Freedom calculator / buckets renta-capital | | |
| MEP (dolarapi → get_mep) | | |
| PositionSnapshot / histórico | | |
| Expert committee / recomendaciones | | |
| Budget / gastos mensuales | | |
| Capital goals / proyecciones | | |
| FTU / onboarding | | |
| Landing / waitlist | | |
| TOS / legal gate | | |

## 6. Riesgos
Para cada riesgo indicá probabilidad (Alta/Media/Baja) e impacto (Alto/Medio/Bajo).

| Riesgo | Prob | Impacto | Mitigación |
|--------|------|---------|------------|
| Regresión en módulo X por cambio en modelo compartido | | | |
| Pérdida de datos en migración | | | |
| Fallo silencioso (sin error visible para el usuario) | | | |
| Inconsistencia ARS/USD por MEP desincronizado | | | |
| Sync del scheduler sobreescribe datos del cambio | | | |
| Endpoint externo (IOL/Cocos/dolarapi) falla durante la feature | | | |
| Deploy sin downtime imposible si hay cambio de schema crítico | | | |

## 7. Sugerencias de arquitectura y evitar duplicación
- ¿Hay lógica similar ya implementada que se pueda reusar o extender en lugar de duplicar?
  Ejemplos: ¿ya existe un service para esto? ¿hay un helper que hace algo parecido?
- ¿La implementación propuesta introduce un patrón nuevo o sigue los existentes del proyecto?
- ¿Conviene extraer algo a un service/ nuevo si esta lógica va a ser usada por más de un router?
- ¿Hay una abstracción prematura que agregar complejidad sin valor real?
- ¿Cómo escala esto con 10x usuarios / 100x posiciones / 10 brokers activos simultáneos?
  Identificar si hay N+1 queries, N+1 HTTP calls, lógica que crece O(n²), o caches que van a quedar stale.

## 8. Estrategia de testing TDD
Definir los tests ANTES de la implementación. Orden: red → green → refactor.

**Tests a escribir primero (red):**
- [ ] Happy path: ...
- [ ] Sad path: ...
- [ ] Edge case: ...

**Mocks necesarios:**
- HTTP externo (IOL / dolarapi / ArgentinaDatos): ¿sí/no?
- DB: ¿usar DB real de test o mock?
- Auth: ¿fixture de usuario autenticado?

**Cobertura mínima aceptable para cerrar esta tarea:**
- [ ] ...

## 9. Rollout y reversibilidad
- ¿El deploy puede hacerse sin downtime? ¿O requiere mantenimiento?
- ¿Necesita feature flag para rollout gradual (primero yo, luego beta users)?
- ¿Hay datos en producción que migrar antes de deployar el código nuevo?
- ¿Cómo se hace rollback completo si falla en prod (código + datos)?
- ¿El scheduler puede correr en paralelo con el deploy sin corromper datos?

## 10. Definition of Ready — ¿está lista para implementar?
La tarea no va al sprint hasta que todos los bloqueantes estén resueltos.

**Bloqueantes (❌ = no implementar hasta resolver):**
- [ ] El problema está definido y acordado
- [ ] Los criterios de aceptación son verificables
- [ ] Los archivos específicos a modificar están identificados
- [ ] La retrocompatibilidad está analizada y el plan de migración está claro
- [ ] Los riesgos altos tienen mitigación definida
- [ ] La estrategia de testing está diseñada

**Deseables (🟡 = idealmente antes, no bloqueante):**
- [ ] El copy (textos) está definido
- [ ] Las env vars nuevas están planificadas
- [ ] La decisión de arquitectura (reusar vs. nuevo) está tomada

## 11. Estimación
- **Tamaño**: XS (< 1h) / S (1-3h) / M (medio día) / L (día completo) / XL (varios días)
- **Capas tocadas**: 1 / 2 / 3 / 4+
- **Riesgo de regresión**: Bajo / Medio / Alto
- **Depende de**: (tareas que deben ir antes)
- **Desbloquea**: (tareas que quedan habilitadas cuando esta termina)

## 12. Ítem formateado para el backlog
Redactá el ítem listo para pegar en el backlog con este formato:

**[Título conciso]**
[Descripción: comportamiento actual → comportamiento esperado. Una o dos oraciones.]
- `BE` `archivo.py` — [qué cambia]
- `FE` `Componente.tsx` — [qué cambia]
- `DB` migration — [qué agrega/modifica]
- `TEST` `test_archivo.py` — [qué cubre]
- `COPY` — [qué texto se define]
```

---

## Checklist de reglas permanentes de BuildFuture

Estas reglas aplican a TODA tarea. Verificar antes de cerrar el análisis.

### Backend — patrones obligatorios
- [ ] `db.rollback()` antes de cualquier `db.commit()` dentro de un `except`
- [ ] Validar longitud de `split()` / indexing antes de desempaquetar credenciales
- [ ] `.limit(N)` en todas las queries que devuelven listas sin filtro estricto
- [ ] `Decimal` (no `float`) para todos los cálculos monetarios
- [ ] Guard de divisor cero antes de toda división (`/ annual_yield_pct`, `/ total`, etc.)
- [ ] MEP siempre desde `services/mep.py → get_mep()`, nunca inline con httpx
- [ ] Lógica de negocio en `services/`, no en `routers/`

### Frontend — patrones obligatorios
- [ ] `res.ok` verificado antes de `.json()` en todo fetch
- [ ] Toast de confirmación Y de error en toda acción que muta datos
- [ ] `try/finally` para garantizar `setSaving(false)` aunque el request falle
- [ ] Early return antes de `setSaving(true)` para inputs inválidos
- [ ] `max-w-lg mx-auto` (o equivalente) en formularios de página completa
- [ ] Estado de loading explícito cuando se espera un dato externo (MEP, precios)

### Base de datos — patrones obligatorios
- [ ] Migration Alembic con `upgrade()` y `downgrade()` ambos implementados
- [ ] Columnas nuevas con `DEFAULT` o `nullable=True` para no romper filas existentes
- [ ] Schema nuevo compatible con versión anterior del código durante la ventana de deploy
- [ ] Nunca `ALTER TABLE` destructivo en producción sin backup confirmado

### Testing TDD — reglas
- [ ] Tests escritos ANTES del código (red → green → refactor)
- [ ] Happy path + sad path + al menos un edge case por feature
- [ ] Mocks mínimos: no mockear lo que se puede testear con DB/fixtures reales
- [ ] Cada bug corregido tiene su test de regresión correspondiente

### Deploy — checklist pre-push
- [ ] `ruff check` y `mypy` sin errores nuevos en backend
- [ ] `next build` sin errores ni warnings ESLint nuevos en frontend
- [ ] Commits del frontend sin `Co-Authored-By` (bloquea Vercel Hobby)
- [ ] Env vars nuevas cargadas en Railway (backend) y Vercel Preview + Production (frontend)
- [ ] Migration ejecutada en producción ANTES de deployar el código que la usa
