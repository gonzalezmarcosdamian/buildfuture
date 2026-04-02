# Integración Cocos Capital — Bitácora

## Estado actual: PoC completado, listo para Iter 1

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
| `annual_yield_pct` | No disponible directo | ⚠️ calcular de result_percentage |
| `snapshot_date` | `date.today()` | ✅ |
| CASH ARS disponible | `buying_power.CI.ars` | ✅ |
| CASH USD disponible | `buying_power.CI.usd` | ✅ |

### Hallazgo clave sobre `quantity`
- `quantity` = número de **cuotapartes** (NO ARS nominales)
- `value_ars = quantity × last_price`
- Validado contra la UI: 4,862,074 cuotapartes × $1,322.91 = $6,432,130 ARS ✅

### Lo que NO se puede hacer todavía

1. **Auto-sync en background** — el 2FA interactivo requiere intervención manual cada vez.
   El scheduler no puede sincronizar Cocos sin el TOTP secret BASE32.

2. **CEDEARs, BONDs, LETRAs** — solo se confirmó con FCIs (la cuenta del PoC solo tiene FCIs).
   No sabemos si `historic_perf` trae otros `instrument_type` ni cómo cambia la estructura.

3. **Historial de operaciones** — `api/v1/transfers` da 404. Sin esto no podemos reconstruir
   el `purchase_fx_rate` real ni el historial de compras.

4. **VCP oficial CNV** — Cocos reporta a CNV pero no expone el endpoint. El `average_price`
   del `historic_perf` es el VCP interno de Cocos (coincide con la UI).

---

## Hallazgo 2026-04-02 — Trusted device (sesión persistente)

Cocos Capital implementa "dispositivo de confianza": después del primer login con 2FA,
el dispositivo queda marcado como confiable y no vuelve a pedir 2FA por un período.
Internamente se implementa con cookies de sesión (`cloudscraper.Session`).

**Implicación:** Si persistimos las cookies de la sesión de pyCocos después del primer login,
los syncs siguientes pueden autenticarse sin 2FA restaurando el cookie jar.

**Por confirmar:** ¿Cuánto dura el trusted device? Script: `scripts/cocos_cookies_poc.py`

Este hallazgo elimina la necesidad del TOTP secret BASE32 y simplifica Iter 2.

---

## Plan de iteraciones (revisado)

### Iter 1 — MVP FCIs + sesión persistente
- Formulario de onboarding multi-paso: email/password → código 2FA → conectado
- Cookies de sesión persistidas en `encrypted_credentials`
- Posiciones FCI con VCP desde `average_price`
- CASH ARS/USD desde `buying_power`
- Auto-sync via cookies (si no expiraron) — manual si expiraron

### Iter 2 — Scheduler + multi asset_type
- Confirmar duración del trusted device
- `_maybe_sync_cocos` en scheduler
- CEDEARs/BONDs — requiere cuenta con esos instrumentos para validar mapper

### Iter 3 — Historial de operaciones
- Explorar `account_movements` con `date_from`/`date_to`
- Reconstruir `purchase_fx_rate` real por operación

---

## Archivos de referencia

- `DOR.md` — Definition of Ready completo (leer antes de abrir branch)
- `explore_2026-04-02.json` — respuesta completa de todos los endpoints probados **(gitignored — datos personales)**
- `raw_response_2026-04-02.json` — respuesta del primer PoC exitoso **(gitignored — datos personales)**
- `backend/scripts/cocos_explore.py` — script de exploración de endpoints
- `backend/scripts/cocos_manual_sync.py` — script de sync manual de prueba
- `backend/scripts/cocos_cookies_poc.py` — exploración de persistencia de cookies
- `backend/scripts/cocos_creds.py` — credenciales temporales **(gitignored — nunca commitear)**
- `backend/scripts/cocos_session.json` — cookies de sesión **(gitignored — JWT tokens reales)**

---

## Decisiones de producto pendientes

- [ ] ¿Aceptamos API no oficial con riesgo de breakage sin aviso?
- [ ] ¿Iter 1 muestra Cocos en la UI aunque no tenga auto-sync? (requiere sync manual)
- [ ] ¿Cómo manejamos el 2FA en el onboarding de Cocos?
