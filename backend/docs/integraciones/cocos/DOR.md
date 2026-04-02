# Integración Cocos Capital — Definition of Ready (DoR)

**Fecha:** 2026-04-02  
**Iteración:** Iter 1 — MVP (sync manual + posiciones FCI + CASH)  
**Estado:** ✅ APROBADO — listo para abrir branch

---

## 1. Contexto y alcance de Iter 1

Conectar Cocos Capital como fuente de posiciones en BuildFuture.  
Scope mínimo:
- Auth con email + password + código 2FA del momento (requerido para conectar)
- TOTP secret BASE32 **opcional** — si se provee, habilita auto-sync via scheduler
- Sin TOTP secret: sync manual, el scheduler skipea Cocos silenciosamente
- El usuario puede agregar el TOTP secret después sin reconectar todo
- Posiciones desde `historic_perf` con VCP real (`average_price`)
- Cash desde `buying_power.CI`
- Posiciones visibles en `/portfolio` con `source = "COCOS"`
- Card en `/integrations` con formulario multi-paso (email+pass → código 2FA + TOTP opcional → conectado)

**Fuera de scope Iter 1:**
- CEDEARs / BONDs / LETRAs (solo FCI confirmado)
- Historial de operaciones (`transfers`)
- Crypto de Cocos

---

## 2. Exploración — resultados

| Pregunta | Resultado |
|---|---|
| ¿pycocos instala sin conflictos? | ✅ OK — deps puras, cffi/cryptography ya en stack via python-jose |
| ¿Railway (nixpacks) soporta pycocos? | ✅ OK — nixpacks es Ubuntu, no Alpine; sin binarios nuevos |
| ¿Cookie jar transfer reemplaza el 2FA? | ❌ NO — Cocos usa device fingerprint (cookie + user-agent + IP); no replicable |
| ¿`account_movements` funciona? | ⬜ Pendiente Iter 4 — probar con date_from/date_to |
| ¿`historic_perf` trae CEDEARs/BONDs? | ⬜ Pendiente Iter 2 — requiere cuenta con esos instrumentos |

**Conclusión sobre auto-sync:** El mecanismo de trusted device de Cocos no es reproducible
transfiriendo cookies. El path viable es TOTP secret BASE32 (pyotp genera el código automáticamente).
El TOTP secret es **opcional** en Iter 1 — si no se tiene, el sync es manual.

---

## 3. Decisiones de producto

| # | Decisión | Resolución |
|---|---|---|
| D1 | ¿Aceptamos API no oficial con riesgo de breakage? | ✅ Sí, con riesgo documentado |
| D2 | ¿Iter 1 en UI con sync manual? | ✅ Sí |
| D3 | ¿Flujo 2FA + TOTP secret opcional combinados? | ✅ Sí — manual por defecto, auto-sync si el usuario provee el secret |

---

## 4. Arquitectura acordada

### 4.1 Flujo de credenciales y sesión

```
Primera conexión (onboarding):
  Paso 1: usuario ingresa email + password + código 2FA del momento + TOTP secret (opcional)
  Backend: Cocos(email, password, topt_secret_key=totp_secret or None)
           Si totp_secret está vacío → pyCocos usa el código 2FA del request body
           Si totp_secret está presente → pyotp genera el código automáticamente
  → is_connected = True, sync inicial del portafolio

Sync manual (usuario lo dispara desde UI):
  Frontend muestra modal "Ingresá el código de Google Authenticator" si no hay TOTP secret
  POST /integrations/cocos/sync body: { "code": "123456" }  ← solo si sin TOTP
  POST /integrations/cocos/sync sin body si hay TOTP secret

Scheduler automático:
  Si TOTP secret presente → pyotp.TOTP(secret).now() genera el código → sync sin usuario
  Si TOTP secret ausente → logger.info("COCOS sin TOTP secret — skip auto-sync") → skip
```

**Formato `encrypted_credentials`:**
```
email:password:BASE32SECRET    ← con TOTP secret
email:password:               ← sin TOTP secret (sync manual)
```
Split con `split(":", 2)` — igual que PPI.

**Agregar TOTP secret después (sin reconectar):**  
`POST /integrations/cocos/update-totp` body: `{ "totp_secret": "BASE32..." }`  
→ actualiza el tercer campo de `encrypted_credentials`, habilita auto-sync.

### 4.2 Mapper: `historic_perf` → `Position`

```python
# annual_yield_pct: usar DEFAULT_YIELDS por asset_type (NO result_percentage)
# result_percentage = rendimiento histórico total ≠ yield anual proyectado
# Si last es None (mercado cerrado): usar previous_price. Si ambos None: skip con WARNING

DEFAULT_YIELDS_COCOS = {
    "FCI":    Decimal("0.08"),
    "CEDEAR": Decimal("0.10"),
    "BOND":   Decimal("0.09"),
    "default": Decimal("0.08"),
}

# instrument_type mapping (solo FCI confirmado):
INSTRUMENT_TYPE_MAP = {
    "FCI": "FCI",
    # Agregar cuando se confirme con cuenta que tenga otros instrumentos:
    # "CEDEAR": "CEDEAR",
    # "BO": "BOND",
    # "ON": "ON",
}
# Fallback: "STOCK" con log WARNING — nunca silenciar
```

### 4.3 CASH como posición

Igual que IOL/PPI: crear una `Position` con `ticker="ARS"` y otra con `ticker="USD"` desde `buying_power.CI`.

### 4.4 Scheduler

`_maybe_sync_cocos(db)` en `scheduler.py` — mismo patrón que `_maybe_sync_iol`:
```python
# Solo si is_connected == True
# Si cookies expiran → last_error descriptivo, NO crash
# NO está en _DEFAULT_INTEGRATIONS (Cocos es opt-in, no por defecto)
```

### 4.5 Frontend

**`providerMeta` en `IntegrationCard.tsx`:**
```typescript
COCOS: {
  label: "Cocos Capital",
  description: "FCI, CEDEARs (read-only)",
  color: "text-orange-400",
}
```

**`ConnectCocosForm.tsx`** — formulario multi-paso:
- Paso 1: email + password → "Siguiente"
- Paso 2:
  - Campo código 2FA (6 dígitos) — requerido — tooltip: "Código actual de Google Authenticator"
  - Campo TOTP secret BASE32 — opcional — tooltip: "Lo obtenés reescaneando el QR en Cocos > Seguridad > Autenticación en 2 pasos. Si no lo tenés ahora, podés dejarlo vacío y agregar después."
  - Badge: "⚡ Auto-sync habilitado" (si TOTP lleno) / "Sync manual" (si vacío)
  → "Conectar"
- Paso 3: éxito → `onSuccess()`

**`POST /integrations/cocos/update-totp`** — para agregar el secret sin reconectar:
- IntegrationCard muestra botón "Habilitar auto-sync" cuando conectado sin TOTP secret

---

## 5. Criterios de aceptación técnicos (checklist)

### Backend — `cocos_client.py`
- [ ] Clase `CocosClient` con `CocosAuthError`, `CocosPosition` (dataclass)
- [ ] `CocosClient.login(email, password)` → inicia auth, retorna si necesita 2FA
- [ ] `CocosClient.verify_2fa(code)` → completa auth, retorna cookies serializadas
- [ ] `CocosClient.restore_session(cookies_json)` → restaura session sin 2FA
- [ ] `CocosClient.get_positions()` → lista de `CocosPosition` desde `historic_perf`
- [ ] `CocosClient.get_cash()` → dict con `ars` y `usd` desde `buying_power`
- [ ] `last is None` → usa `previous_price`, si ambos `None` → skip con `logger.warning`
- [ ] `instrument_type` desconocido → `asset_type = "STOCK"` con `logger.warning`
- [ ] Timeout en todas las calls (20s para portfolio, 10s para buying_power)
- [ ] `CocosAuthError` en 401/403 con mensaje descriptivo

### Backend — `integrations.py`
- [ ] `POST /integrations/cocos/connect` (body: `email`, `password`) → inicia login, retorna `requires_2fa: bool`
- [ ] `POST /integrations/cocos/verify` (body: `email`, `password`, `code`) → completa login, primer sync, guarda cookies
- [ ] `POST /integrations/cocos/sync` → usa cookies guardadas, re-autentica si expiraron con error claro
- [ ] `POST /integrations/cocos/disconnect` → limpia credentials, desactiva posiciones `source="COCOS"`
- [ ] Integration record creado con `provider="COCOS"`, `provider_type="ALYC"`

### Backend — `scheduler.py`
- [ ] `_maybe_sync_cocos(db)` agregado al `_daily_close_job`
- [ ] Si cookies expiradas: `last_error` descriptivo, no crash, no intentar re-login con password

### Backend — `requirements.txt`
- [ ] `pycocos` agregado
- [ ] Verificado que instala en el entorno local sin errores
- [ ] **Verificado en Railway** (cloudscraper tiene dependencias nativas — `cffi`, `cryptography`)

### Tests — `tests/test_cocos_client.py` (TDD: escribir ANTES del código)
- [ ] `test_get_positions_fci_ok` — FCI con `last` válido → `CocosPosition` correcta
- [ ] `test_get_positions_last_none_uses_previous` — `last: null`, `previous_price` válido → no skip
- [ ] `test_get_positions_both_prices_none_skips` — ambos `null` → posición excluida, warning logueado
- [ ] `test_get_positions_unknown_type_defaults_stock` — tipo desconocido → `asset_type="STOCK"`
- [ ] `test_annual_yield_uses_default_not_result_pct` — `annual_yield_pct` viene de `DEFAULT_YIELDS_COCOS`, no de `result_percentage`
- [ ] `test_get_cash` — `buying_power.CI` → dict `{ars: X, usd: Y}`
- [ ] `test_auth_error_on_403` — login devuelve 403 → `CocosAuthError`
- [ ] `test_restore_session_skips_2fa` — con cookies válidas → no llama a verify

### Frontend — `ConnectCocosForm.tsx`
- [ ] Paso 1: email + password
- [ ] Paso 2: campo código 2FA (solo si backend retorna `requires_2fa: true`)
- [ ] Tooltip en paso 2: "Código de 6 dígitos de tu app autenticadora (Google Authenticator)"
- [ ] Estados: loading, error, éxito
- [ ] `onSuccess()` al conectar

### Frontend — `IntegrationCard.tsx`
- [ ] `providerMeta["COCOS"]` con label, description, color
- [ ] Renderiza `<ConnectCocosForm>` cuando `provider === "COCOS"` y no conectado

---

## 6. Definition of Done (DoD)

- [ ] Tests pasan: `pytest backend/tests/test_cocos_client.py -v` → 0 failures
- [ ] `ruff check backend/` → 0 errores
- [ ] `eslint` frontend → 0 errores
- [ ] `tsc --noEmit` → 0 errores
- [ ] Sync funciona **localmente** contra DB local:
  - Login con email + password + código 2FA
  - Posiciones aparecen en `GET /portfolio` con `source="COCOS"`
  - Cash ARS/USD aparece en posiciones
  - Card en `/integrations` muestra `is_connected: true` y fecha de último sync
- [ ] Segunda ejecución de sync (sin 2FA) funciona con cookies guardadas
- [ ] BITACORA.md actualizada con resultado de la exploración de cookies
- [ ] Sin console.log ni prints de debug en el código
- [ ] Branch: `feature/cocos-iter1` → PR → revisión → merge → deploy explícito

---

## 7. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Cocos cambia endpoints sin aviso | Media | Alto | `last_error` visible en UI; sync manual siempre disponible como fallback |
| `pycocos` falla en Railway (dependencias nativas) | Media | **BLOQUEANTE** | Verificar con `pip install pycocos` en un container slim antes de abrir branch |
| Cookies expiran antes de lo esperado | Media | Medio | `last_error` descriptivo; usuario re-conecta desde UI sin perder posiciones |
| `instrument_type` desconocido silencia posiciones | Baja | Alto | Fallback a `"STOCK"` con log WARNING; nunca skip silencioso |
| Race condition duplicados en sync | Baja | Medio | Ya existe `_dedup_positions` en startup; misma clave `(user_id, ticker, "COCOS")` |
| Cloudflare detecta pycocos y bloquea | Baja | Alto | Fallback a sync manual; monitorear `last_error` en Railway logs |

---

## 8. Orden de implementación (TDD)

```
1. Script de PoC cookies (cocos_cookies_poc.py) — exploración, no va a producción
2. Responder preguntas de exploración → actualizar BITACORA.md
3. Obtener aprobación de decisiones D1, D2, D3
4. Abrir branch: feature/cocos-iter1
5. Escribir tests/test_cocos_client.py (RED — todos fallan)
6. Implementar cocos_client.py hasta que tests pasen (GREEN)
7. Agregar endpoints en integrations.py
8. Agregar _maybe_sync_cocos en scheduler.py
9. Agregar pycocos a requirements.txt — verificar Railway
10. Frontend: ConnectCocosForm.tsx + actualizar IntegrationCard.tsx
11. Smoke test local completo (flujo onboarding → sync → portfolio)
12. ruff + eslint + tsc → 0 errores
13. PR → merge → deploy explícito
```

---

## 9. Aprobaciones

| Ítem | Owner | Estado |
|---|---|---|
| pycocos instala sin conflictos (local + Railway nixpacks) | Dev | ✅ confirmado |
| Cookies no reemplazan 2FA — TOTP secret es el path | Dev | ✅ confirmado |
| D1: API no oficial aceptada | Marcos | ✅ aprobado |
| D2: Iter 1 en UI con sync manual | Marcos | ✅ aprobado |
| D3: TOTP secret opcional (manual por defecto, auto-sync si disponible) | Marcos | ✅ aprobado |
| Este documento aprobado | Marcos + Dev | ✅ **APROBADO** |

**Branch habilitado: `feature/cocos-iter1`**
