# Playbook — Integración de nuevos proveedores

**Aplica a:** cualquier nueva fuente de datos financieros (ALYC, exchange, broker, bank)  
**Origen:** proceso seguido en integración Cocos Capital (2026-04-02)  
**Leer antes de:** abrir cualquier branch de integración nueva

---

## El principio rector

> "No escribir código de producción hasta tener certeza de que todo lo que depende del entorno externo funciona."

Los proveedores financieros argentinos tienen APIs no documentadas, Cloudflare, 2FA, tokens que expiran,
y endpoints que dan 404 sin aviso. Un branch que arranca con supuestos incorrectos sobre la API
termina siendo reescrito o abandonado. La exploración y el DoR son inversiones, no burocracia.

---

## Fase 0 — Viabilidad (antes de cualquier documento)

**Duración estimada:** 1–2 días  
**Output:** confirmar que la integración es técnicamente posible

### 0.1 — Identificar la librería o mecanismo de acceso

- ¿Existe una librería Python que maneje la auth? (pycocos, iol-api, ppi-sdk, etc.)
- ¿Tiene Cloudflare? Si sí, ¿la librería usa `cloudscraper` o similar?
- ¿Tiene API pública oficial con docs? Si no, ¿hay reverse engineering comunitario?
- ¿Qué tipo de auth usa? (OAuth2, API keys, email+password+2FA, certificados)

### 0.2 — Ejecutar el primer PoC exitoso

Crear `backend/scripts/{provider}_explore.py` — **nunca va a producción**.  
El script debe:
1. Autenticar y lograr un 200
2. Llamar al endpoint de portafolio/posiciones
3. Imprimir la respuesta cruda en JSON

```python
# Estructura mínima del script de exploración
import json
from {librería} import Client

client = Client(email=EMAIL, password=PASSWORD)
response = client.get_portfolio()
print(json.dumps(response, indent=2, ensure_ascii=False))
```

Guardar la respuesta exitosa en `backend/docs/integraciones/{provider}/explore_{fecha}.json`.

### 0.3 — Criterio de corte de Fase 0

Si no se logra autenticar y obtener al menos una respuesta exitosa en 2 días → escalar y revisar
si la integración es viable. No entrar a la Fase 1 sin esto.

---

## Fase 1 — Exploración profunda

**Duración estimada:** 2–4 días  
**Output:** BITACORA.md con todos los endpoints mapeados y campos disponibles

### 1.1 — Mapear todos los endpoints relevantes

Para cada endpoint del proveedor, documentar:

| Endpoint | Status | Descripción | Campos útiles |
|---|---|---|---|
| `api/v1/portfolio` | ✅ 200 | Posiciones | ticker, quantity, avg_price |
| `api/v1/balance` | ✅ 200 | Cash disponible | ars, usd |
| `api/v1/movements` | ❌ 404 | Historial | — |

### 1.2 — Mapear campos del proveedor vs campos BuildFuture

La tabla de mapping es obligatoria y debe incluir disponibilidad explícita:

| Campo BuildFuture | Fuente proveedor | Disponible | Notas |
|---|---|---|---|
| `ticker` | `symbol` | ✅ | |
| `quantity` | `shares` | ✅ | unidad: piezas, no nominales |
| `ppc_ars` | `average_price` | ✅ | VCP real, validado contra UI |
| `annual_yield_pct` | No disponible | ⚠️ | usar DEFAULT_YIELDS por asset_type |
| `purchase_fx_rate` | No disponible | ❌ | fallback: MEP actual |

### 1.3 — Validar los campos críticos contra la UI del proveedor

**Nunca confiar en la API sin cruzar contra la UI.**  
Para cada campo cuantitativo:
- Abrir la app/web del proveedor
- Comparar el valor de la API con lo que muestra la UI
- Documentar la validación: `4,862,074 cuotapartes × $1,322.91 = $6,432,130 ARS ✅`

### 1.4 — Identificar ambigüedades de tipos y unidades

Preguntas obligatorias para cada campo numérico:
- `quantity` ¿es piezas, nominales, cuotapartes?
- `price` ¿es ARS o USD? ¿por unidad o por cada 100 nominales?
- `performance` ¿es anual, mensual, o total histórico?
- ¿Puede ser `null`? ¿En qué circunstancias?

### 1.5 — Output: BITACORA.md

Crear `backend/docs/integraciones/{provider}/BITACORA.md` con:
- Contexto (origen de la API, librería usada)
- Autenticación (método, 2FA, tokens, expiración)
- Endpoints confirmados (tabla)
- Mapping de campos (tabla)
- Hallazgos no obvios (ej: "quantity son cuotapartes, no ARS")
- Lo que NO está disponible
- Plan de iteraciones

---

## Fase 2 — Comité técnico

**Duración estimada:** medio día  
**Output:** lista de gaps identificados y decisiones pendientes

Antes de escribir el DoR, hacer una revisión cruzando el plan contra las siguientes categorías:

### 2.1 — Seguridad

- [ ] ¿Cómo se almacenan las credenciales? (`encrypted_credentials` en plain text es aceptable para dev, no para prod)
- [ ] ¿El secreto es más sensible que usuario+password? (TOTP secret, API private key)
- [ ] ¿El `encrypted_credentials` format es consistente con los otros providers? (`user:pass` split con `:`)

### 2.2 — Dependencias externas

- [ ] ¿La librería nueva instala sin conflictos con `requirements.txt`?
- [ ] ¿Tiene dependencias nativas (cffi, libssl, etc.) que puedan fallar en Railway nixpacks?
- [ ] ¿La librería está activamente mantenida? ¿Cuándo fue el último commit?
- [ ] Verificar: `pip install {librería} --dry-run` en un environment limpio

### 2.3 — Autenticación y auto-sync

- [ ] ¿El mecanismo de auth es automatizable sin intervención del usuario?
- [ ] Si hay 2FA: ¿cookie persistence? ¿TOTP secret? ¿Cada cuánto expira?
- [ ] ¿Qué pasa cuando el token/sesión expira en producción? ¿El scheduler crashea o recupera gracefully?
- [ ] **Explorar antes de asumir:** probar explícitamente el mecanismo propuesto (ej: cookie jar transfer) antes de diseñar la arquitectura

### 2.4 — Mapping de tipos

- [ ] ¿Todos los `instrument_type` del proveedor tienen un mapeo en `asset_type` BuildFuture?
- [ ] ¿Qué pasa si el proveedor devuelve un tipo desconocido? ¿Se skipea silenciosamente o con log?
- [ ] ¿`annual_yield_pct` viene del proveedor o hay que calcularlo/defaultear?
  - Nunca usar `performance_total_pct` del proveedor como `annual_yield_pct` — son conceptos distintos
  - Usar `DEFAULT_YIELDS` por asset_type como fallback

### 2.5 — Consistencia con providers existentes

- [ ] ¿El patrón `ConnectXXXForm` → `POST /integrations/xxx/connect` → `_sync_xxx()` se respeta?
- [ ] ¿El `encrypted_credentials` split con `:` es consistente? (`split(":", n)` donde n depende del provider)
- [ ] ¿`_maybe_sync_xxx` se agrega en `scheduler.py` con el mismo patrón que IOL/PPI?
- [ ] ¿CASH ARS y USD se crean como posiciones `asset_type="CASH"` igual que otros providers?

### 2.6 — Escalabilidad de la UI

Recorrer **todos** los puntos de contacto en el frontend:

| Componente | Pregunta |
|---|---|
| `SyncButton` | ¿El nuevo provider necesita input del usuario para sincronizar? Si sí, no puede ir en el sync masivo. Agregar `auto_sync_enabled` al response de `GET /integrations`. |
| `PortfolioTabs` — `SOURCE_BADGES` | ¿Está el nuevo provider en el dict? Si no → badge sin estilo. |
| `PortfolioTabs` — `SOURCE_LABELS` | ¿Está el nuevo provider? Si no → muestra el código crudo. |
| `IntegrationCard` — `providerMeta` | ¿Está el nuevo provider? Si no → sin label ni color. |
| `InstrumentDetail` | ¿El detalle del instrumento funciona para los `asset_type` que trae el provider? |
| Info tooltips | ¿Mencionan fuentes específicas (IOL, etc.) que ya no aplican? |

### 2.7 — Riesgos operativos

- [ ] ¿La API es oficial o reverse-engineered? Si es no oficial: ¿quién detecta los breaks?
- [ ] ¿Qué pasa si el proveedor cae en producción? ¿El scheduler falla silenciosamente o explota?
- [ ] ¿Hay rate limiting? ¿El scheduler puede quedar bloqueado?
- [ ] ¿El `last_error` en la UI es suficiente como mecanismo de alerta?

---

## Fase 3 — Definition of Ready (DoR)

**Output:** `backend/docs/integraciones/{provider}/DOR.md`  
**Condición:** el branch NO se abre hasta que el DoR esté aprobado

### Estructura obligatoria del DoR

```markdown
# Integración {Provider} — Definition of Ready

## 1. Contexto y alcance de Iter 1
## 2. Exploración — resultados (con tablas de preguntas respondidas)
## 3. Decisiones de producto (con estado: ✅ / ⬜)
## 4. Arquitectura acordada
   ### 4.1 Flujo de credenciales
   ### 4.2 Mapper: campos del proveedor → Position
   ### 4.3 CASH
   ### 4.4 Scheduler
   ### 4.5 Frontend
## 5. Criterios de aceptación técnicos (checklist con [ ])
   ### Backend — {provider}_client.py
   ### Backend — integrations.py
   ### Backend — scheduler.py
   ### Backend — requirements.txt
   ### Tests — test_{provider}_client.py
   ### Frontend
## 6. Definition of Done (DoD)
## 7. Riesgos y mitigaciones
## 8. Orden de implementación (TDD)
## 9. Aprobaciones (con estado: ✅ / ⬜)
```

### Checklist de aprobación antes de abrir branch

- [ ] Todos los bloqueantes técnicos validados (no hay suposiciones sobre la API)
- [ ] Todas las decisiones de producto respondidas por el owner
- [ ] Formato de `encrypted_credentials` definido y documentado
- [ ] `auto_sync_enabled` definido para el SyncButton
- [ ] SOURCE_BADGES, SOURCE_LABELS, providerMeta actualizados (o en el scope del PR)
- [ ] Orden de implementación TDD documentado
- [ ] El DoR aprobado por dev + product owner

---

## Fase 4 — Implementación (TDD obligatorio)

### Orden fijo de implementación

```
1. Tests primero (RED — todos fallan)
   └── backend/tests/test_{provider}_client.py

2. Implementar hasta que los tests pasen (GREEN)
   └── backend/app/services/{provider}_client.py

3. Endpoints del router
   └── backend/app/routers/integrations.py
       POST /integrations/{provider}/connect
       POST /integrations/{provider}/sync
       POST /integrations/{provider}/disconnect

4. Scheduler
   └── backend/app/scheduler.py → _maybe_sync_{provider}()

5. Requirements
   └── backend/requirements.txt → agregar librería

6. Frontend
   └── ConnectXXXForm.tsx (nuevo)
   └── IntegrationCard.tsx (providerMeta + lógica sync)
   └── PortfolioTabs.tsx (SOURCE_BADGES + SOURCE_LABELS)
   └── portfolio/page.tsx + dashboard/page.tsx (filtro auto_sync_enabled)

7. Smoke test local completo
   └── Login → onboarding → sync → /portfolio → /integrations
   
8. Calidad
   └── pytest → 0 failures
   └── ruff check → 0 errores
   └── eslint → 0 errores
   └── tsc --noEmit → 0 errores

9. PR → revisión → merge → deploy explícito
```

### Casos de test obligatorios para cualquier client

```python
# Siempre testear estos casos, independientemente del provider:
test_get_positions_ok                    # caso feliz
test_get_positions_empty                 # portafolio vacío
test_get_positions_price_null_fallback   # precio nulo → fallback o skip
test_get_positions_unknown_type          # tipo desconocido → STOCK + warning
test_annual_yield_not_from_performance   # yield ≠ rendimiento histórico
test_get_cash                            # ARS y USD
test_auth_error_on_bad_credentials       # 401/403 → AuthError
test_timeout_raises_gracefully           # timeout → no crash
```

### Reglas del mapper ({provider}_position → Position)

1. `last_price is None` → usar `previous_price`. Si ambos None → **skip con `logger.warning`**, nunca posición con precio 0.
2. `instrument_type` desconocido → `asset_type = "STOCK"` + `logger.warning`. Nunca skip silencioso.
3. `annual_yield_pct` → siempre desde `DEFAULT_YIELDS` por asset_type. Nunca desde `result_percentage` o `performance_pct` del proveedor (son históricos, no proyectados).
4. `quantity ≤ 0` → skip.
5. Validar la unidad de `quantity` explícitamente antes de deployar (cuotapartes ≠ nominales ≠ piezas).

---

## Fase 5 — Smoke test local

**No deployar sin completar este checklist manualmente.**

### Flujo de onboarding
- [ ] Card del provider aparece en `/integrations`
- [ ] Formulario de connect funciona (happy path)
- [ ] Error de credenciales incorrectas muestra mensaje claro
- [ ] Tras conectar: `is_connected = true` en la card
- [ ] Primer sync ejecuta y posiciones aparecen en `/portfolio`

### Portfolio
- [ ] Posiciones del nuevo provider aparecen con badge correcto (`SOURCE_BADGES`)
- [ ] Subtotal del grupo en Composición es correcto
- [ ] Tab Rendimientos muestra el grupo del nuevo provider
- [ ] Click en una posición abre el `InstrumentDetail` correctamente
- [ ] SyncButton en portfolio: si `auto_sync_enabled` → aparece; si no → no aparece

### Sync
- [ ] Segundo sync no duplica posiciones (dedup funciona)
- [ ] Desconectar borra credenciales y desactiva posiciones
- [ ] `last_synced_at` se actualiza tras cada sync exitoso
- [ ] `last_error` se muestra en la card cuando el sync falla

### Scheduler
- [ ] `_maybe_sync_{provider}` skipea si no está conectado (no crash)
- [ ] Si `auto_sync_enabled = false` → skipea con log, sin error

---

## Estructura de archivos por integración

```
backend/
  app/
    services/
      {provider}_client.py          ← client + dataclass + mapper + AuthError
    routers/
      integrations.py               ← endpoints connect/sync/disconnect (todos acá)
    scheduler.py                    ← _maybe_sync_{provider}()
  tests/
    test_{provider}_client.py       ← TDD, mocks, sin red real
  docs/
    integraciones/
      {provider}/
        BITACORA.md                 ← exploración + hallazgos + plan iters
        DOR.md                      ← definition of ready
        explore_{fecha}.json        ← raw response del primer PoC exitoso
  scripts/
    {provider}_explore.py           ← script de exploración (NO producción)
    {provider}_cookies_poc.py       ← scripts adicionales de exploración
frontend/
  components/
    integrations/
      Connect{Provider}Form.tsx     ← formulario de onboarding
      IntegrationCard.tsx           ← agregar providerMeta + lógica sync
  components/
    portfolio/
      PortfolioTabs.tsx             ← agregar SOURCE_BADGES + SOURCE_LABELS
```

---

## Decisiones de producto requeridas (template)

Para cada integración, el product owner debe responder estas preguntas antes de abrir el branch:

| # | Pregunta estándar |
|---|---|
| D1 | ¿Aceptamos la API si no es oficial? ¿Con qué nivel de riesgo documentado? |
| D2 | ¿El provider aparece en la UI aunque el sync sea manual (sin auto-sync)? |
| D3 | ¿Cómo es el flujo de 2FA/autenticación especial en el onboarding? |
| D4 | ¿Qué pasa si las credenciales expiran en producción? ¿El usuario recibe un aviso? |
| D5 | ¿El provider va en el scheduler automático (Iter 1) o se agrega en una iter posterior? |

---

## Lecciones aprendidas de Cocos Capital (2026-04-02)

| Lección | Detalle |
|---|---|
| **Explorar antes de diseñar** | El mecanismo de "trusted device" de Cocos parecía una solución elegante (cookies) pero falló en el PoC. Habría diseñado la arquitectura incorrecta si no se validaba primero. |
| **Validar unidades contra la UI** | `quantity` en Cocos son cuotapartes, no ARS nominales. Solo se confirmó cruzando contra la UI de Cocos (`4,862,074 × $1,322.91 = $6,432,130`). El número de la API no dice nada por sí solo. |
| **`result_percentage` ≠ `annual_yield_pct`** | El proveedor devuelve rendimiento histórico total, no anual proyectado. Usar el valor directo hubiera roto el freedom calculator. |
| **Dependencias nativas en nixpacks** | La preocupación de cffi/cryptography en Railway era válida pero ya estaba resuelta por `python-jose[cryptography]`. Verificar el stack antes de asumir que es un problema. |
| **PoC interactivo requiere terminal real** | Scripts con `input()` no corren desde Claude Code. Siempre diseñar los scripts de exploración para correrlos el usuario directamente. |
| **El DoR salva iters completas** | El comité técnico identificó 6 gaps de diseño antes de escribir una línea de código. Sin ese paso, todos esos bugs hubieran aparecido en PR o en producción. |
