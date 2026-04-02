# Integración Cocos Capital — Bitácora

## Estado actual: Iter 1 IMPLEMENTADA — pendiente smoke test local

---

## 2026-04-02 — Exploración y PoC

### Contexto
Cocos Capital no tiene API pública oficial. La API fue descubierta mediante reverse engineering
por la comunidad argentina. Se usó la librería `pycocos` (pip install pycocos) que maneja
Cloudflare bypass con `cloudscraper` internamente.

### Autenticación
- **Método:** email + password + 2FA (TOTP o SMS/mail)
- **Problema:** `cocos-capital-client` (la librería async) falla en el login — devuelve 403 FORBIDDEN
- **Solución:** `pycocos` funciona. Hace el login en 2 pasos:
  1. `POST auth/v1/token` con email + password
  2. `POST auth/v1/factors/{id}/verify` con código 2FA
- **2FA interactivo:** Si no se provee `topt_secret_key`, pyCocos hace `input("Insert 2FA Code:")` automáticamente
- **Bloqueador para auto-sync:** El 2FA interactivo no es automatizable sin el TOTP secret BASE32
  (no el código de 6 dígitos — el secret original que se muestra en el QR al configurar 2FA)

### Endpoints relevantes confirmados

| Endpoint | Status | Descripción |
|----------|--------|-------------|
| `api/v1/users/me` | ✅ 200 | Datos del usuario, cuenta, tier |
| `api/v1/wallet/performance/daily` | ✅ 200 | Posiciones con precio actual y rendimiento del día |
| `api/v1/wallet/performance/historic` | ✅ 200 | **Posiciones con `average_price` (VCP/costo promedio)** |
| `api/v2/orders/buying-power` | ✅ 200 | Saldo disponible por plazo (CI/24hs/48hs) en ARS/USD |
| `api/v1/wallet/portfolio` | ❌ 404 | Endpoint muerto en pyCocos |
| `api/v2/wallet/portfolio` | ❌ 404 | No existe |
| `api/v1/transfers` | ❌ 404 | Movimientos — no disponible |
| `api/v1/wallet/holdings` | ❌ 404 | No existe |

### Campos disponibles para BuildFuture

**De `historic_perf` (`api/v1/wallet/performance/historic`):**
```json
{
  "instrument_code": "COCOSPPA",
  "instrument_short_name": "Cocos Pesos Plus",
  "instrument_type": "FCI",
  "short_ticker": "COCOSPPA",
  "quantity": 4862074.52553576,
  "last": 1320.813,
  "result": 418010.24,
  "average_price": 1234.839,
  "result_percentage": 0.06962,
  "id_security": 140681840
}
```

**De `buying_power` (`api/v2/orders/buying-power`):**
```json
{
  "CI":   { "ars": 0.33, "usd": 0, "ext": 0 },
  "24hs": { "ars": 0.33, "usd": 0, "ext": 0 }
}
```

### Mapping confirmado: campos BuildFuture vs Cocos

| Campo BuildFuture | Fuente Cocos | Disponible |
|---|---|---|
| `ticker` | `short_ticker` | ✅ |
| `description` | `instrument_short_name` | ✅ |
| `asset_type` | `instrument_type` (FCI directo) | ✅ solo FCI confirmado |
| `source` | hardcoded `"COCOS"` | ✅ |
| `quantity` | `quantity` (cuotapartes) | ✅ |
| `current_price_usd` | `(last ?? previous_price) / MEP` | ✅ |
| `current_value_ars` | `quantity × last` | ✅ |
| `current_value_usd` | `value_ars / MEP` | ✅ |
| `ppc_ars` | `average_price` de historic_perf | ✅ **confirmado** |
| `avg_purchase_price_usd` | `average_price / MEP` | ✅ estimado |
| `purchase_fx_rate` | No disponible | ⚠️ usar MEP actual como fallback |
| `annual_yield_pct` | No disponible directo | ⚠️ `DEFAULT_YIELDS` por asset_type |
| `snapshot_date` | `date.today()` | ✅ |
| CASH ARS disponible | `buying_power.CI.ars` | ✅ |
| CASH USD disponible | `buying_power.CI.usd` | ✅ |

### Hallazgo clave sobre `quantity`
- `quantity` = número de **cuotapartes** (NO ARS nominales)
- `value_ars = quantity × last_price`
- Validado contra la UI: 4,862,074 cuotapartes × $1,322.91 = $6,432,130 ARS ✅

### Lo que NO se puede hacer todavía

1. **CEDEARs, BONDs, LETRAs** — solo se confirmó con FCIs (la cuenta del PoC solo tiene FCIs).
   `instrument_type` desconocido → fallback a `STOCK` + WARNING en logs.

2. **Historial de operaciones** — `api/v1/transfers` da 404. Sin esto no podemos reconstruir
   el `purchase_fx_rate` real ni el historial de compras.

3. **VCP oficial CNV** — `average_price` del `historic_perf` es el VCP interno de Cocos (coincide con la UI).

---

## 2026-04-02 — Hallazgo: Trusted device (cookies) — DESCARTADO

Cocos implementa "dispositivo de confianza" con cookies de sesión (`cloudscraper.Session`).
Hipótesis: persistir el cookie jar permitiría sincronizar sin 2FA.

**Resultado del PoC (`scripts/cocos_cookies_poc.py`):** ❌ **FALLA**

Cocos usa fingerprinting de IP + user-agent + cookie. El cookie jar no es transferible entre
sesiones distintas ni entre reinicios del servidor. El trusted device queda ligado a la
sesión de cloudscraper de esa ejecución, no al jar en sí.

**Decisión:** Descartar el enfoque de cookies. La solución para auto-sync es el **TOTP secret BASE32**
almacenado como campo opcional en `encrypted_credentials[2]`.

---

## 2026-04-02 — Decisiones de producto (TODAS RESUELTAS)

| Decisión | Resolución |
|---|---|
| ¿Aceptamos API no oficial? | ✅ Sí, con riesgo documentado en DOR. pycocos tiene maintainer activo. |
| ¿Iter 1 muestra Cocos sin auto-sync? | ✅ Sí, con sync manual via modal (código 2FA) |
| ¿Cómo manejamos el 2FA? | ✅ Código manual (campo obligatorio) + TOTP secret (opcional, habilita auto-sync) |
| ¿Auto-sync sin TOTP secret? | ✅ Sistema funciona sin él — scheduler skipea silenciosamente, usuario hace sync manual |
| ¿Cómo escala el SyncButton global? | ✅ Campo `auto_sync_enabled` en GET /integrations — filtra Cocos sin TOTP del sync global |

---

## 2026-04-02 — Implementación Iter 1 (COMPLETA)

### Qué se implementó

**Backend**
- `cocos_client.py` — `CocosClient` con `authenticate()`, `get_positions()`, `get_cash()`, `_get_mep()`
- `tests/test_cocos_client.py` — 24 tests, todos GREEN en 0.17s (TDD red→green)
- `routers/integrations.py` — endpoints `connect`, `sync`, `disconnect`, `update-totp` + campo `auto_sync_enabled` en GET /integrations
- `scheduler.py` — `_maybe_sync_cocos()` en el job diario 17:30 ART
- `requirements.txt` — `pycocos>=0.2.0`

**Frontend**
- `ConnectCocosForm.tsx` — formulario multi-paso en dos etapas (credentials → 2FA + TOTP opcional)
- `CocosSyncModal` — modal de sync manual con código 2FA de 6 dígitos (exportado desde ConnectCocosForm)
- `IntegrationCard.tsx` — COCOS en providerMeta (naranja), badge auto-sync/manual, botón "Sync manual"
- `PortfolioTabs.tsx` — COCOS en SOURCE_BADGES (naranja) y SOURCE_LABELS
- `portfolio/page.tsx` + `dashboard/page.tsx` — SyncButton filtra por `auto_sync_enabled`
- `settings/page.tsx` — type annotation actualizado

**Rama:** `feature/cocos-iter1` (backend + frontend). No mergeado a main/master.

### Arquitectura de credenciales

```
encrypted_credentials = "email:password:totp_secret"
                         split(":", 2)  →  parts[0], parts[1], parts[2]

totp_secret vacío → auto_sync_enabled = false
totp_secret presente → auto_sync_enabled = true
```

---

## UX completa — casos de uso documentados

### Conexión inicial (Settings → Integraciones)

El usuario ve la tarjeta Cocos (naranja, ícono X = no conectado) con el botón
"Conectar Cocos Capital".

**Paso 1 — Credenciales:**
Formulario inline con indicador de pasos `① Credenciales → ② Verificar 2FA`.
Ingresa email y password. "Siguiente" avanza sin request al backend.

**Paso 2 — 2FA + TOTP opcional:**
- Campo obligatorio: código 6 dígitos de Google Authenticator (monospace, numérico)
- Sección colapsable "Auto-sync" con campo BASE32 secret (opcional)
  - Badge amarillo ⚡ "habilitado" si hay secret; slate ⚡ "manual" si no

Al confirmar: `POST /integrations/cocos/connect { email, password, code, totp_secret }`.
Backend: autentica via pycocos, primer sync de posiciones, guarda credenciales.
La tarjeta cierra y muestra checkmark verde.

---

### Dos mundos después de conectar

**Con TOTP secret — auto-sync habilitado**
```
Badge:    ⚡ auto-sync  (amarillo)
Botón:    "Sync"  (azul, igual que IOL/PPI)
SyncButton global:  ✅ incluye Cocos
Scheduler 17:30:    ✅ sincroniza automáticamente
```

**Sin TOTP secret — manual**
```
Badge:    ⚡ manual  (gris)
Botón:    "Sync manual"  (naranja)
  → abre CocosSyncModal: input grande de 6 dígitos → POST /cocos/sync { code }
SyncButton global:  ❌ excluye Cocos
Scheduler 17:30:    ❌ skipea silenciosamente (sin error, solo log)
```

---

### Upgrade a auto-sync (sin reconectar)

Si el usuario consigue el BASE32 secret después de conectar:
`POST /integrations/cocos/update-totp { totp_secret }`.
El backend valida con `pyotp.TOTP(secret).now()`, actualiza el campo preservando
email y password. El badge pasa de gris a amarillo sin desconectar ni reingresa credenciales.

---

### Lo que aparece en el portafolio

Las posiciones tienen `source = "COCOS"`. En la vista de composición:
- Grupo encabezado naranja "Cocos Capital"
- Tickers de cash: `CASH_COCOS` (ARS disponible), `CASH_COCOS_USD` (USD disponible)
- FCI: precio en USD calculado via MEP de dolarapi.com
- `annual_yield_pct` viene de `DEFAULT_YIELDS` (no del `result_percentage` de Cocos)

En la vista de rendimientos: mismo tratamiento que IOL/PPI — barra de performance + P&L.

---

### Sync diario automático (scheduler 17:30 ART, L-V)

```
1. Backup DB
2. Sync IOL   (si conectado)
3. Sync PPI   (si conectado)
4. Sync Cocos (si conectado Y tiene totp_secret)
5. Refresh precios manuales (crypto/FCI/ETF)
6. Snapshot portafolio total
```

Si Cocos no tiene TOTP secret: `logger.info("skip auto-sync")` — no cuenta como error,
no setea `last_error`.

---

### Casos de error

| Situación | Respuesta |
|---|---|
| Credenciales incorrectas | Error en paso 2 del form |
| Código 2FA expirado/incorrecto | Error en paso 2 |
| TOTP secret BASE32 inválido | 400 en update-totp |
| Sync manual con código vencido | Error en CocosSyncModal |
| Sync automático falla | `last_error` visible en tarjeta; próximo ciclo reintenta |
| pycocos no instalado | Error explícito "pip install pycocos" |
| `last = None` y `previous_price = None` | Skip de esa posición + WARNING en logs |
| `instrument_type` desconocido | `asset_type = STOCK` + WARNING en logs |

---

### Desconexión

Botón "Desconectar" → modal de confirmación.
`POST /integrations/cocos/disconnect`:
- `encrypted_credentials = ""`
- `is_connected = False`
- Todas las posiciones COCOS: `is_active = False`
La tarjeta vuelve al estado inicial con botón "Conectar".

---

## Plan de iteraciones

### Iter 1 — COMPLETA ✅
MVP: FCIs + CASH + 2FA manual con TOTP opcional para auto-sync.

### Iter 2 — Pendiente
- CEDEARs/BONDs — requiere cuenta con esos instrumentos para validar mapper
- Ampliar `_INSTRUMENT_TYPE_MAP` en `cocos_client.py`
- Confirmar estructura de `historic_perf` para otros `instrument_type`

### Iter 3 — Pendiente
- Historial de operaciones (`account_movements` con date range)
- Reconstruir `purchase_fx_rate` real por operación
- Hoy se usa MEP actual como fallback para todas las compras históricas

---

## Archivos de referencia

- `DOR.md` — Definition of Ready completo (aprobado)
- `explore_2026-04-02.json` — respuesta completa de endpoints **(gitignored — datos personales)**
- `raw_response_2026-04-02.json` — respuesta del primer PoC **(gitignored — datos personales)**
- `backend/scripts/cocos_explore.py` — script de exploración de endpoints
- `backend/scripts/cocos_manual_sync.py` — script de sync manual de prueba
- `backend/scripts/cocos_cookies_poc.py` — PoC cookies (resultado: DESCARTADO)
- `backend/scripts/cocos_creds.py` — credenciales temporales **(gitignored — nunca commitear)**
- `backend/scripts/cocos_session.json` — cookies **(gitignored — JWT tokens reales)**
