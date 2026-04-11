# Integraciones de brokers — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

| Broker | Estado | Auto-sync | Histórico |
|--------|--------|-----------|-----------|
| **IOL** | ✅ Prod | ✅ Sí | 730 días (operaciones) |
| **Cocos** | ✅ Prod | ✅ Sí | Solo desde primer sync |
| **Binance** | ✅ Prod | ✅ Sí | 30 días (accountSnapshot API) |
| **PPI** | ✅ Prod (layout) | ❌ No (2FA) | Sin histórico |

---

## Comportamiento esperado (invariantes)

1. `auto_sync_enabled` es campo obligatorio en `GET /integrations` para todos los providers. `True` = puede syncronizar sin intervención del usuario. `False` = excluye del SyncButton global.
2. `price is None` → fallback a `previous_price`. Si ambos None → skip con WARNING, nunca precio 0.
3. Tipo desconocido → `STOCK` + WARNING, nunca skip silencioso.
4. `annual_yield_pct` siempre desde `DEFAULT_YIELDS` en el sync; se enriquece luego con `yield_updater.py`.
5. El patrón **deactivate-all → INSERT-new** en cada sync usa `_get_enrichment()` para preservar campos Platform-owned (`annual_yield_pct`, `external_id`, `fci_categoria`).

---

## Playbook para nuevas integraciones (5 fases)

### Fase 0 — Viabilidad
PoC con script en `scripts/{provider}_explore.py`. Si no se logra auth+200 en 2 días → escalar. No continuar sin PoC exitoso.

### Fase 1 — Exploración profunda
Mapear endpoints, validar campos contra UI del proveedor, documentar unidades (cuotapartes ≠ nominales). Output: entrada en BITACORA.md.

### Fase 2 — Comité técnico
Revisar: seguridad (encrypted_credentials), dependencias Railway, mecanismo auto-sync, mapping de tipos, UI (SyncButton, SOURCE_BADGES, providerMeta), riesgos operativos.

### Fase 3 — DoR
`DOR.md` con checklist de aprobaciones. La rama NO se abre hasta DoR aprobado.

### Fase 4 — TDD
Tests (RED) → implementar (GREEN) → endpoints → scheduler → frontend → smoke test local → ruff+eslint+tsc → PR.

**Lección Cocos:** sin exploración previa se diseña arquitectura incorrecta (cookie persistence falló en PoC), se usan métricas incorrectas (`result_percentage` ≠ `annual_yield_pct`), se rompe la UI (SOURCE_BADGES sin entry).

---

## Checklist al agregar una nueva ALYC

**Backend:**
- [ ] `_sync_xxx(client, db, user_id)` en `integrations.py`
- [ ] `_get_enrichment(db, user_id, "SOURCE")` llamado antes del deactivate-all
- [ ] `auto_sync_enabled` correcto en response de `GET /integrations`
- [ ] `_DEFAULT_INTEGRATIONS` en `main.py` y `integrations.py` (para lazy creation + backfill startup)
- [ ] `SOURCE_BADGES` en frontend con color/label
- [ ] Scheduler: agregar al job de sync global si `auto_sync_enabled=True`

**Frontend:**
- [ ] `providerMeta` con nombre, logo, descripción
- [ ] SyncButton incluye al nuevo provider si `auto_sync_enabled`
- [ ] `InstrumentDetail.tsx`: branch o fallback para tipos específicos del provider

---

## IOL — Hallazgos y bugs documentados

### Mapeo de asset_type

IOL no es confiable para clasificar asset_type por string. Usar `_TICKER_TYPE_OVERRIDES` en `iol_client.py`:

```python
_TICKER_TYPE_OVERRIDES = {
    "IOLCAMA": "FCI", "IOLCAM": "FCI", "IOLMMA": "FCI", "IOLMM": "FCI",
    "NDT25": "BOND", "NDT26": "BOND", "NDT27": "BOND",
    # + agregar aquí cuando aparezcan nuevos casos
}
```

### Bugs resueltos (referencia)

**Bug: `cantidad` vs `cantidadOperada`**
IOL devuelve `cantidad` en ARS para órdenes "por monto" (CEDEAR). La cantidad real en unidades siempre está en `cantidadOperada`. Usar `cantidadOperada` o el historial queda inflado 100-1000x. Fix en `_parse_operations_v2`.

**Bug: ppc LETRA/BOND/ON es per 100 VN**
IOL cotiza `ppc_ars` en ARS por cada 100 nominales. Siempre dividir `/100`:
```python
price_per_vn_ars = (ppc_ars / 100.0) * ((1 + daily_rate) ** days)
price_usd = price_per_vn_ars / mep
```
Aplica a `("LETRA", "BOND", "ON")`.

**Bug: acento en "suscripción"**
IOL devuelve `tipo = "suscripción fci"` con ó acentuada. Usar `"suscripci" in tipo` (prefijo sin acento) para que capture ambas variantes.

**Bug: Yahoo Finance devuelve precio NYSE para CEDEARs**
`yfinance` da precio NYSE (AMZN=$210 USD) pero el CEDEAR vale ARS/MEP ($1.52 USD). Fix en `historical_reconstructor.py`: usar `seriehistorica` de IOL primero; Yahoo como fallback con corrección por `equiv = round(yahoo_price / current_price_usd)`.

**Bug: evento registraba qty PRE-compra**
Timeline guardaba `(fecha_compra, 0)` en vez de `(fecha_compra, qty_comprado)`. Fix: registrar `current_qty` antes del undo, no el estado después.

**Bug: tickers "unreliable" eliminaban historial reciente válido**
Al detectar venta invisible, marcar `stop_older` (parar de procesar ops más antiguas) pero conservar eventos ya registrados. No descartar el ticker completo.

### Algoritmo backwards-anchored (historical_reconstructor.py)

1. Empezar desde posiciones actuales (estado conocido y correcto).
2. Ir hacia atrás por cada operación `terminada`:
   - `compra`/`suscripci*`: restar qty. Si va negativo → ventas invisibles → `stop_older` para ese ticker.
   - `venta`/`rescate`: sumar qty.
   - Registrar `(fecha, current_qty)` = qty EOD (POST-operación).
3. Resultado: timeline verificable por fecha.

### Convención de precios LECAP

IOL reporta dos precios distintos para LECAPs:
- **Portfolio** `/api/v2/portafolio/argentina`: `valorizado/cantidad` = precio técnico acumulado. Puede superar 100 per 100 VN.
- **Cotización** `/api/v2/Cotizacion/Titulos/{mercado}/{ticker}`: `ultimoPrecio` en VN=1000, precio de descuento.

Si `price_per_100 >= 100` → retornar DEFAULT_TNA (0.68) en lugar de TIR negativa.

### Admin endpoints de soporte

URL base: `https://api-production-7ddd6.up.railway.app/admin/`
Header: `X-Admin-Key: 8URlXkc8Xmz4p2oCBGG2mYklSxAmcqSk2AzgzbfuY4A`

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/support/repair-user?user_id=` | POST | Flujo unificado: purge + IOL + Binance + backfill + hoy |
| `/support/snapshot-health?user_id=` | GET | Detecta inflación (flag si max > 5x avg) |
| `/support/backfill-non-iol?user_id=` | POST | Solo backfill Cocos/Manual |
| `/support/force-snapshot-today?user_id=` | POST | Solo snapshot de hoy |
| `/snapshots/info` | GET | Resumen snapshots por usuario |
| `/snapshots/values?user_id=&limit=` | GET | Ver valores USD |
| `/positions/inspect?user_id=&source=` | GET | Posiciones activas con todos los campos |
| `/positions/dupes?user_id=` | GET | Detectar posiciones duplicadas |
| `/positions/dedup?user_id=` | DELETE | Fix duplicados |
| `/reconstruct/dry-run?user_id=&target_date=` | GET | Simular reconstrucción sin escribir en DB |
| `/yields/run` | POST | Disparar yield_updater manualmente |
| `/cache/mep-info` | GET | Info caché MEP |
| `/cache/price-info?ticker=` | GET | Info caché Yahoo Finance |
| `/cache/price-source-purge?source=YAHOO&ticker=` | DELETE | Purge price_history por fuente |

---

## Bugs conocidos / deuda técnica

| # | Bug | Severidad | Archivo |
|---|-----|-----------|---------|
| 1 | IOL FCIs (IOLCAMA, IOLMMA) no en ArgentinaDatos con ese nombre → promedio categoría, no yield exacto | P2 | yield_updater.py |
| 2 | ONs argentinas sin calibrar en `_BOND_YTM` → usan DEFAULT 9% | P2 | yield_updater.py |
| 3 | Cocos API: solo estado actual, sin historial de operaciones | Arquitectural | — |
| 4 | `_sync_cocos` no crea `PositionSnapshot` al sincronizar | P1 | integrations.py:1785 |
| 5 | `_sync_binance` no crea `PositionSnapshot` por ticker | P2 | integrations.py:1996 |

---

## Cambios recientes

| Fecha | Cambio |
|-------|--------|
| 2026-04-11 | Binance: +35 tokens en `_COINGECKO_ID` (ETHW, SHIB, ARB, OP, INJ, SUI...) |
| 2026-04-11 | `repair-user` unificado: incluye Binance history + backfill non-IOL en un solo endpoint |
| 2026-04-03 | PR #29: fix ppc per-100VN para BOND/ON; fix Yahoo CEDEAR con equiv ratio |
| 2026-04-02 | PR #17: `_get_enrichment()` preserva campos Platform-owned en cada sync |

---

## Decisiones de diseño

**Por qué deactivate-all → INSERT-new:** IOL/Cocos no tienen delta API. La única forma de saber qué sigue activo es traer el estado completo y reemplazar. El costo es que se pierden campos enriquecidos → resuelto con `_get_enrichment()`.

**Por qué no guardar cookie de Cocos:** el PoC demostró que las cookies de Cocos expiran y la renovación requiere 2FA. Se resolvió con sesión efímera por sync.

**Por qué `annual_yield_pct` no viene del proveedor:** los valores de `result_percentage` de Cocos son retornos históricos del período, no yields anualizados. Usar `DEFAULT_YIELDS` en el sync y enriquecer con `yield_updater` es más consistente entre fuentes.
