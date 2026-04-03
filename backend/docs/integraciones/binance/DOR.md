# Integración Binance — Definition of Ready (DoR)

**Fecha:** 2026-04-03  
**Iteración:** Iter 1 — MVP (balances spot + PPC real + historial 30d)  
**Estado:** ✅ APROBADO — listo para abrir branch

---

## 1. Contexto y alcance de Iter 1

Conectar Binance como fuente de posiciones crypto en BuildFuture.  
Scope:
- Auth por API Key + Secret (read-only, sin permisos de trading)
- `auto_sync_enabled = True` — no requiere 2FA en cada sync
- Balances spot desde `GET /api/v3/account`
- Precio actual desde CoinGecko `get_price_usd` — ya en el stack
- Yield real 30d desde CoinGecko `get_yield_30d` — ya en el stack
- **PPC real** desde `GET /api/v3/myTrades` por símbolo
- **Historial 30d** desde `GET /sapi/v1/accountSnapshot` — snapshots diarios reales
- USDT/USDC/stablecoins como posición con precio $1.0
- Posiciones en `/portfolio` con `source = "BINANCE"`
- Card en `/integrations` con formulario simple: API Key + Secret

**Fuera de scope Iter 1:**
- Futuros, margin, opciones
- Earn/Flexible savings (assets `LD*`)
- Múltiples sub-cuentas

---

## 2. Exploración — resultados PoC (2026-04-03)

| Pregunta | Resultado |
|---|---|
| ¿Auth HMAC-SHA256 funciona? | ✅ HTTP 200 confirmado |
| ¿`GET /api/v3/account` balances? | ✅ 6 assets con saldo encontrados |
| ¿`GET /api/v3/myTrades` PPC? | ✅ Precio real de compra disponible por símbolo (ej: USDTARS a $1513 ARS) |
| ¿`GET /sapi/v1/accountSnapshot` historial? | ✅ 30 snapshots diarios, rango Mar 4 → Abr 2 |
| ¿Assets `LD*` (Lending)? | ⚠️ Aparecen en balance spot — filtrar en Iter 1 |
| ¿Asset `ARS` (pesos)? | ⚠️ Aparece en balance — ignorar, sin par USDT |
| ¿`myTrades` para ETHW? | ❌ Par ETHWUSDT inválido — activos exóticos sin par, skip con warning |
| ¿Rate limits? | ✅ Muy por debajo de 1200 weight/min para sync diario |
| ¿python-binance necesario? | ✅ No — httpx directo es suficiente, ya en stack |

**Hallazgos clave del PoC:**
- `LD*` = activos en Flexible Earn — aparecen en spot pero son earn. Filtrar por prefijo `LD`.
- `ARS` = pesos argentinos en cuenta Binance. Sin par USDT. Ignorar.
- `accountSnapshot` devuelve 30 días exactos — historial real sin necesidad de reconstruir.
- `myTrades` requiere el símbolo exacto (`BTCUSDT`, `USDTARS`). Para calcular PPC hay que iterar por asset.
- USDT se compra con ARS via par `USDTARS` — trades disponibles con precio en ARS.

---

## 3. Decisiones de producto ✅ TODAS APROBADAS

| # | Decisión | Resolución |
|---|---|---|
| D1 | ¿Filtrar `LD*` y `ARS`? | ✅ **SÍ** — filtrar silenciosamente |
| D2 | ¿Stablecoins como posición? | ✅ **SÍ** — precio $1.0, yield 0%, asset_type=CRYPTO |
| D3 | ¿Fuente de precios? | ✅ **CoinGecko** — ya en stack en `crypto_prices.py` |
| D4 | ¿API Key read-only? | ✅ **SÍ** — usuario genera key con solo "Enable Reading" |
| D5 | ¿Yield? | ✅ **CoinGecko `get_yield_30d`** — variación real 30d anualizada |
| D6 | ¿Historial? | ✅ **`accountSnapshot`** — 30 snapshots diarios reales disponibles |
| D7 | ¿PPC real? | ✅ **`myTrades`** — precio promedio ponderado de compras por símbolo |

---

## 4. Arquitectura acordada

### 4.1 Flujo de credenciales

```
Primera conexión:
  Usuario genera API Key en Binance:
    Perfil → Gestión de API → Crear API → "Enable Reading" únicamente
  Ingresa en UI: API Key + Secret Key
  Backend valida con GET /api/v3/account → 200 = conectado
  Sync inicial: balances + precios + yield + PPC + historial 30d

Sync diario (auto_sync_enabled = True):
  POST /integrations/binance/sync — firma HMAC por request, sin usuario

encrypted_credentials: "api_key:secret_key"  →  split(":", 1)
```

### 4.2 Firma HMAC-SHA256

```python
def _signed_get(self, endpoint: str, params: dict = {}) -> dict:
    p = {**params, "timestamp": int(time.time() * 1000)}
    query = urllib.parse.urlencode(p)
    sig = hmac.new(self._secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    r = httpx.get(
        f"https://api.binance.com{endpoint}",
        params={**p, "signature": sig},
        headers={"X-MBX-APIKEY": self._api_key},
        timeout=10,
    )
    if r.status_code in (401, 403):
        raise BinanceAuthError("API Key inválida o revocada")
    r.raise_for_status()
    return r.json()
```

### 4.3 Mapper: balances → BinancePosition

```python
_COINGECKO_ID: dict[str, str] = {
    "BTC": "bitcoin",   "ETH": "ethereum",  "BNB": "binancecoin",
    "SOL": "solana",    "ADA": "cardano",   "XRP": "ripple",
    "MATIC": "matic-network", "DOT": "polkadot", "AVAX": "avalanche-2",
    "LINK": "chainlink", "USDT": None, "USDC": None, "BUSD": None,
    "DAI": None, "TUSD": None, "FDUSD": None,
}
_STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}
_SKIP_PREFIXES = ("LD",)   # Flexible Earn
_SKIP_ASSETS   = {"ARS"}   # Monedas fiat

# Por cada balance:
# 1. asset starts with "LD" o in _SKIP_ASSETS → skip silencioso
# 2. quantity = free + locked; if <= 0 → skip
# 3. if stablecoin → price=$1.0, yield=0.0
# 4. if in _COINGECKO_ID → price=get_price_usd(id), yield=get_yield_30d(id)
# 5. else → skip con logger.warning
# 6. ppc_usd = calcular desde myTrades (ver 4.4)
```

### 4.4 PPC real desde myTrades

```python
def _get_ppc_usd(self, asset: str, mep: float) -> float:
    """
    PPC en USD calculado desde myTrades del par {asset}USDT.
    Para USDT comprado con ARS: precio_ars / mep → USD.
    Retorna 0.0 si no hay trades o par inválido.
    """
    # Intentar par directo USDT
    for symbol in [f"{asset}USDT", f"USDT{asset}"]:
        try:
            trades = self._signed_get("/api/v3/myTrades", {"symbol": symbol, "limit": 500})
            if not trades:
                continue
            total_qty = sum(float(t["qty"]) for t in trades if t["isBuyer"])
            total_cost = sum(float(t["qty"]) * float(t["price"]) for t in trades if t["isBuyer"])
            if total_qty > 0:
                return total_cost / total_qty
        except Exception:
            continue

    # USDT comprado con ARS: par USDTARS, convertir precio ARS → USD
    if asset == "USDT":
        try:
            trades = self._signed_get("/api/v3/myTrades", {"symbol": "USDTARS", "limit": 500})
            buys = [t for t in trades if t["isBuyer"]]
            if buys:
                total_qty = sum(float(t["qty"]) for t in buys)
                total_ars = sum(float(t["qty"]) * float(t["price"]) for t in buys)
                avg_ars = total_ars / total_qty  # ARS por USDT
                return avg_ars / mep  # convertir a USD
        except Exception:
            pass

    return 0.0
```

### 4.5 Historial desde accountSnapshot

```python
def get_snapshot_history(self) -> list[dict]:
    """
    Retorna hasta 30 snapshots diarios de balance spot.
    Cada snapshot: {date: date, balances: {asset: qty}}
    Filtra LD* y ARS.
    """
    data = self._signed_get("/sapi/v1/accountSnapshot", {"type": "SPOT", "limit": 30})
    result = []
    for snap in data.get("snapshotVos", []):
        d = date.fromtimestamp(snap["updateTime"] / 1000)
        balances = {}
        for b in snap["data"]["balances"]:
            asset = b["asset"]
            if any(asset.startswith(p) for p in _SKIP_PREFIXES) or asset in _SKIP_ASSETS:
                continue
            qty = float(b["free"]) + float(b["locked"])
            if qty > 0:
                balances[asset] = qty
        if balances:
            result.append({"date": d, "balances": balances})
    return result
```

**Integración con PortfolioSnapshot:** al conectar Binance, el sync inicial llama `get_snapshot_history()` y crea snapshots históricos para los 30 días anteriores, exactamente como hace el reconstructor de IOL.

### 4.6 Scheduler

```python
def _maybe_sync_binance(db: Session) -> None:
    integrations = db.query(Integration).filter(
        Integration.provider == "BINANCE",
        Integration.is_connected == True,
    ).all()
    for integration in integrations:
        try:
            api_key, secret = integration.encrypted_credentials.split(":", 1)
            client = BinanceClient(api_key, secret)
            sync_binance_positions(client, db, integration.user_id)
        except BinanceAuthError as e:
            integration.last_error = str(e)
            integration.is_connected = False
            db.commit()
        except Exception as e:
            integration.last_error = str(e)
            db.commit()
```

### 4.7 Frontend — cómo reacciona la UI

**`/integrations`:**
- Card "Binance" badge amarillo
- Formulario 1 paso: API Key + Secret Key
- Tooltip: "Generá tu API Key en Binance → Perfil → Gestión de API → Crear API → seleccioná solo 'Enable Reading'"
- Badge "⚡ Auto-sync habilitado" siempre (no requiere 2FA)
- Post-conexión: checkmark verde + fecha último sync

**`/portfolio`:**
- Posiciones con badge `BINANCE` amarillo (igual a `IOL` azul y `COCOS` naranja)
- USDT/stablecoins: precio $1.0, yield 0%
- Ganancia neta: visible porque tenemos PPC real desde myTrades
- Total portfolio: suma automática del valor crypto

**Freedom Bar:**
- Yield 30d real de CoinGecko: sube si crypto subió, baja si bajó
- Refleja la volatilidad real — comportamiento correcto

**Historial (gráfico):**
- Al conectar: carga automáticamente 30 días de historia desde `accountSnapshot`
- Sin gap — el gráfico arranca desde 30 días atrás con valores reales de Binance

---

## 5. Criterios de aceptación técnicos

### Backend — `binance_client.py`
- [ ] `BinanceClient(api_key, secret)` + `BinanceAuthError`
- [ ] `_signed_get(endpoint, params)` con firma HMAC-SHA256
- [ ] `validate()` → GET /api/v3/account → bool
- [ ] `get_positions()` → lista de `BinancePosition`
- [ ] `BinancePosition`: ticker, asset_type="CRYPTO", quantity, current_price_usd, avg_purchase_price_usd, ppc_ars=0, annual_yield_pct, current_value_ars
- [ ] `_get_ppc_usd(asset, mep)` → PPC en USD desde myTrades
- [ ] `get_snapshot_history()` → lista de snapshots diarios
- [ ] Filtro `LD*` y `ARS` silencioso
- [ ] Stablecoins → price=$1.0, yield=0.0
- [ ] Asset desconocido → skip con logger.warning
- [ ] `BinanceAuthError` en 401/403
- [ ] Timeout 10s en todas las calls

### Backend — `integrations.py`
- [ ] `POST /integrations/binance/connect` → valida + primer sync + historial 30d
- [ ] `POST /integrations/binance/sync` → re-sync posiciones
- [ ] `POST /integrations/binance/disconnect` → limpia, desactiva posiciones source="BINANCE"
- [ ] `auto_sync_enabled = True` en GET /integrations response
- [ ] provider="BINANCE", provider_type="EXCHANGE"

### Backend — `scheduler.py`
- [ ] `_maybe_sync_binance(db)` en `_daily_close_job`
- [ ] API key revocada → `last_error`, `is_connected=False`, no crash

### Tests — `tests/test_binance_client.py` (TDD — escribir ANTES)
- [ ] `test_get_positions_usdt_ok` — USDT con saldo → BinancePosition price=1.0
- [ ] `test_ld_asset_filtered` — LDBNB → excluido silenciosamente
- [ ] `test_ars_asset_filtered` — ARS → excluido silenciosamente
- [ ] `test_zero_balance_skipped` — free=0, locked=0 → excluido
- [ ] `test_unknown_asset_warning` — asset no en _COINGECKO_ID → skip + warning
- [ ] `test_auth_error_on_401` → BinanceAuthError
- [ ] `test_hmac_signature_in_request` — signature y X-MBX-APIKEY presentes
- [ ] `test_ppc_from_trades` — myTrades con buys → PPC calculado correctamente
- [ ] `test_snapshot_history_filters_ld` — snapshots sin assets LD*

### Frontend
- [ ] `ConnectBinanceForm.tsx` — 1 paso, API Key + Secret, tooltip instrucciones
- [ ] Badge "⚡ Auto-sync habilitado" siempre
- [ ] `providerMeta["BINANCE"]` en IntegrationCard.tsx — label, description, color amarillo
- [ ] `SOURCE_BADGES["BINANCE"]` en portfolio — badge amarillo

---

## 6. Definition of Done (DoD)

- [ ] Tests: `pytest backend/tests/test_binance_client.py -v` → 0 failures
- [ ] `ruff check backend/` → 0 errores
- [ ] `eslint` frontend → 0 errores
- [ ] `tsc --noEmit` → 0 errores
- [ ] Smoke test local:
  - Conectar con API Key real → posiciones en GET /portfolio con source="BINANCE"
  - Precios USD correctos (CoinGecko)
  - PPC real visible (ganancia neta calculada)
  - Historial 30d cargado automáticamente al conectar
  - Freedom bar actualizada con crypto
- [ ] Segunda ejecución de sync sin reconectar
- [ ] BITACORA.md actualizada
- [ ] Sin console.log ni prints de debug
- [ ] Branch: `feature/binance-iter1` → PR → revisión → merge → deploy explícito

---

## 7. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Usuario activa permisos de trading en la API Key | Media | Alto | Tooltip con instrucción explícita "solo Enable Reading" |
| CoinGecko rate limit (15 req/min free) | Media | Medio | Sleep 0.2s entre calls; sync diario no es intensivo |
| Yield 30d negativo en freedom bar | Alta | Bajo | Comportamiento correcto — refleja volatilidad real |
| myTrades sin par USDT para asset exótico | Media | Bajo | Fallback ppc_usd=0, no bloquea sync |
| accountSnapshot solo 30 días | Alta | Bajo | Documentado como limitación; historial crece día a día desde conexión |
| API Key revocada por usuario | Media | Bajo | `is_connected=False` + `last_error` descriptivo en UI |

---

## 8. Orden de implementación (TDD)

```
1. tests/test_binance_client.py  (RED — todos fallan)
2. binance_client.py             (GREEN — tests pasan)
3. integrations.py — endpoints connect/sync/disconnect
4. scheduler.py — _maybe_sync_binance
5. ConnectBinanceForm.tsx + providerMeta + SOURCE_BADGES
6. Smoke test local completo
7. ruff + eslint + tsc → 0 errores
8. PR → merge → deploy explícito
```

---

## 9. Aprobaciones

| Ítem | Owner | Estado |
|---|---|---|
| D1: filtrar LD* y ARS | Marcos | ✅ aprobado |
| D2: stablecoins como posición | Marcos | ✅ aprobado |
| D3: CoinGecko para precios | Marcos | ✅ aprobado |
| D4: API Key read-only | Marcos | ✅ aprobado |
| D5: yield real CoinGecko 30d | Marcos | ✅ aprobado |
| D6: historial desde accountSnapshot | Marcos | ✅ aprobado |
| D7: PPC real desde myTrades | Marcos | ✅ aprobado |
| Auth HMAC-SHA256 confirmada con cuenta real | Dev | ✅ confirmado |
| accountSnapshot 30d validado | Dev | ✅ confirmado |
| myTrades con PPC real validado | Dev | ✅ confirmado |
| LD* y ARS identificados y filtrados | Dev | ✅ confirmado |
| httpx directo suficiente (sin python-binance) | Dev | ✅ confirmado |
| Este documento aprobado | Marcos + Dev | ✅ **APROBADO** |

**Branch habilitado: `feature/binance-iter1`**
