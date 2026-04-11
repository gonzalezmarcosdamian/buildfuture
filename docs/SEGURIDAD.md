# Seguridad — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

### Credenciales de brokers

Las credenciales de IOL, Cocos y PPI (usuario + contraseña) se almacenan encriptadas en la tabla `integrations`. Se usa encriptación en reposo con AES-256.

| Broker | Tipo de acceso | Scope | Riesgo |
|--------|---------------|-------|--------|
| IOL | Usuario + contraseña | Acceso completo (trading, retiros) | ALTO |
| Cocos | Usuario + contraseña | Acceso completo (trading, retiros) | ALTO |
| Binance | API Key + Secret | Granular (solo "Enable Reading") | BAJO |
| PPI | API Key + Secret | Lectura (verificar) | MEDIO |

### Binance — modelo de seguridad correcto

Binance sí implementa scopes granulares por API Key. El usuario debe crear su API Key con únicamente "Enable Reading" activado. Con ese scope, los endpoints de trading y withdrawal son inaccesibles incluso si el token es comprometido.

**Endpoints usados (solo GET firmados):**
- `GET /api/v3/account` — balances spot
- `GET /api/v3/myTrades` — trades históricos
- `GET /sapi/v1/accountSnapshot` — snapshots diarios

**Nunca agregar:** `POST /api/v3/order` (trading), `POST /wapi/v3/withdraw.html` (retiros).

El test `tests/test_readonly_audit.py` verifica este contrato automáticamente.

---

## Riesgo P0 — IOL/Cocos sin scopes de solo lectura

IOL y Cocos no ofrecen API Keys con scopes granulares. El acceso es user+password con permisos completos (trading, retiros).

**Riesgos:**
- Si las credenciales se filtran → acceso total a la cuenta del usuario
- Sin 2FA en el flujo de acceso de BuildFuture → vector de ataque más amplio

**Mitigaciones actuales:**
- Encriptación AES-256 en reposo para `encrypted_credentials`
- El cliente no llama endpoints POST/DELETE de los brokers (verificar audit)
- Aviso en onboarding: "BuildFuture nunca opera en tu nombre"

**Pendiente:**
- [ ] Verificar que `encrypted_credentials` usa AES-256 + documentar key management
- [ ] Auditar que ningún cliente de integración llama endpoints POST/DELETE de broker
- [ ] Investigar si IOL ofrece algún mecanismo de API Key con permisos limitados
- [ ] Actualizar ToS con modelo de acceso y garantías

---

## Admin endpoints — protección

Todos los endpoints bajo `/admin/` requieren header `X-Admin-Key`.

```
Header: X-Admin-Key: 8URlXkc8Xmz4p2oCBGG2mYklSxAmcqSk2AzgzbfuY4A
```

Estos endpoints NO están expuestos al frontend. Solo se usan desde CLI o scripts de soporte.

**Riesgo:** la admin key está hardcodeada en documentación interna. Rotar si se sospecha filtración.

---

## Autenticación de usuarios

BuildFuture usa Supabase Auth (JWT). El flujo de auth es:

1. Usuario se registra/login → Supabase emite JWT
2. Frontend adjunta JWT en cada request al backend
3. Backend valida JWT via `get_current_user()` — extrae `user_id`
4. Toda operación de DB se filtra por `user_id` — los datos son user-scoped

**Reset de contraseña:** Supabase usa PKCE. El link del email contiene `?code=...` que se intercambia en `/auth/callback`. Sin esta route, el reset no funciona.

---

## Reglas de código — seguridad

- Nunca loguear credenciales (API keys, passwords, tokens)
- Todo endpoint que lee/escribe datos de usuario debe pasar por `get_current_user()`
- Los endpoints admin (`/admin/`) deben verificar `X-Admin-Key` antes de cualquier operación
- `db.commit()` dentro de `try` siempre necesita `db.rollback()` en el `except`
- No usar `eval()`, `exec()`, o inputs de usuario directos en queries SQL

---

## Cambios recientes

| Fecha | Cambio |
|-------|--------|
| 2026-04-11 | Binance: cliente solo READ — `_signed_get` solo usa GET firmado HMAC-SHA256 |
