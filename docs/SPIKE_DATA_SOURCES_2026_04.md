# SPIKE — Fuentes de Datos Externas BuildFuture
**Fecha:** 2026-04-13 | **Autor:** Claude (SM + analista financiero)
**Objetivo:** Mapeo completo de proveedores de datos disponibles, POC realizado, casos de uso e integración recomendada.

---

## Resumen ejecutivo

| Proveedor | Auth | Estado | Usos actuales | Nuevos usos |
|-----------|------|--------|---------------|-------------|
| BYMA Open Data | ❌ Ninguna | ✅ Activo | Letras, CEDEARs, STOCKs, Bonos, ONs | FCI precios intraday |
| ArgentinaDatos | ❌ Ninguna | ✅ Activo (parcial) | FCI mercadoDinero VCP, UVA | Renta fija/variable/mixta VCP, Plazo fijo TNA, Depósitos 30d |
| dolarapi.com | ❌ Ninguna | ✅ Activo | MEP live (usado en mep.py) | Blue, CCL, mayorista |
| bluelytics.com.ar | ❌ Ninguna | ✅ Activo | MEP histórico (MepHistory) | — |
| CoinGecko (free tier) | ❌ Ninguna | ✅ Nuevo POC | — | Precios CRYPTO USD + histórico 30d + search |
| Binance (public) | ❌ Ninguna | ✅ Nuevo POC | scripts/binance_explore.py | Precios CRYPTO/USDT tiempo real, 24h stats |
| BCRA (oficial) | ❌ Ninguna | ✅ Parcial | — | Cotizaciones multilateral, tipo de cambio oficial |
| IOL API | ✅ OAuth2 | ✅ Activo | Portafolio, precios, FCI | cauciones, historial operaciones |
| Cocos API | ✅ Token | ✅ Activo | Portafolio | — |
| PPI API | ✅ OAuth | ✅ Activo | Portafolio | — |
| ArgentinaDatos Plazo Fijo | ❌ Ninguna | ✅ Nuevo POC | — | TNA por banco para PLAZO_FIJO asset_type |
| ROFEX/MatbaRofex | ❌ Ninguna | ❌ No accesible | devaluation.py (intento) | Futuros ARS/USD devaluación implícita |
| Ambito Financiero | ❌ Ninguna | ❌ 403 Forbidden | — | Bloqueado |
| IAMC | ❌ Ninguna | ❌ SSL error | — | Requiere bypass SSL |

---

## 1. BYMA Open Data — ✅ Ya integrado

**URL base:** `https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free`
**Auth:** Sin autenticación. Headers de origin BYMA requeridos.
**Método:** POST `/get-market-data` con panel como clave booleana en body.
**Delay:** ~20 minutos (mercado real).

### Panels disponibles y campos clave

| Panel | Uso actual | Items típicos | Campos clave |
|-------|-----------|---------------|--------------|
| `btnLetras` | ✅ TEA LECAPs | ~20 letras | `symbol`, `vwap`, `tradeVolume`, `previousSettlementPrice` |
| `btnCedears` | ✅ Precio CEDEARs | ~100 CEDEARs | `symbol`, `vwap`, `previousClosingPrice`, `tradingHighPrice`, `tradingLowPrice` |
| `btnLideres` | ✅ STOCKs Merval | ~24 acciones | idem CEDEARs |
| `btnTitPublicos` | ✅ TIR bonos (null actualmente) | ~60 bonos | `symbol`, `vwap`, `impliedYield` (null) |
| `btnObligNegociables` | ✅ TIR ONs (null actualmente) | ~200 ONs | `symbol`, `vwap`, `impliedYield` (null) |
| `btnGeneral` | ❌ Sin uso | Todo el mercado | idem |

### Fichatécnica (por ticker)
**URL:** POST `/bnown/fichatecnica/especies/general` body: `{"symbol": "S31G6"}`
**Datos:** `fechaEmision`, `fechaVencimiento`, `interes` (TEM contractual), `denominacion`
**Uso:** Calcular TEA de LECAPs desde TEM + precio BYMA.
**Cache recomendado:** 1 hora (datos estáticos del instrumento).

### Limitaciones conocidas
- `impliedYield` en btnTitPublicos y btnObligNegociables viene `null` siempre → no sirve para TIR directa
- btnGeneral incluye todo pero es ruidoso; usar paneles específicos
- IP de Railway bloqueada intermitentemente → connect_timeout implementado

### Nuevos usos potenciales
- `btnGeneral` con filtro por tipo → mapear todos los instrumentos del mercado (discovery)
- Cuando BYMA exponga `impliedYield` para ONs → reemplazar tabla fallback `_ON_USD_TIR_TABLE`

---

## 2. ArgentinaDatos — ✅ Activo (parcial)

**URL base:** `https://api.argentinadatos.com`
**Auth:** Sin autenticación. CORS libre.
**Rate limit:** Sin documentar; comportamiento razonable en uso actual.

### Endpoints confirmados (POC 2026-04-13)

| Endpoint | Status | Datos | Uso actual |
|----------|--------|-------|-----------|
| `/v1/finanzas/fci/mercadoDinero/ultimo` | ✅ 200 | n=382 FCIs money market, VCP+CCP | ✅ fci_prices.py — TEA FCIs dinero |
| `/v1/finanzas/fci/rentaFija/ultimo` | ✅ 200 | n=1958 FCIs renta fija, VCP | ❌ No usado — potencial FCI renta fija |
| `/v1/finanzas/fci/rentaVariable/ultimo` | ✅ 200 | n=305 FCIs renta variable | ❌ No usado |
| `/v1/finanzas/fci/rentaMixta/ultimo` | ✅ 200 | n=974 FCIs mixtos | ❌ No usado |
| `/v1/finanzas/indices/uva` | ✅ 200 | n=3666 puntos, `{fecha, valor}` diario hasta hoy | ✅ byma_client.py — ratio CER letras X-prefix |
| `/v1/cotizaciones/dolares` | ✅ 200 | n=29207, histórico completo todas las casas | ✅ usado en MepHistory (bluelytics es el activo) |
| `/v1/cotizaciones/dolares/oficial` | ✅ 200 | histórico oficial compra/venta | ❌ Alternativa a dolarapi |
| `/v1/cotizaciones/dolares/blue` | ✅ 200 | histórico blue | ❌ Sin uso actual |
| `/v1/finanzas/tasas/plazoFijo` | ✅ 200 | n=30, por banco: TNA clientes/no clientes | ❌ Sin uso — nuevo: PLAZO_FIJO asset_type |
| `/v1/finanzas/tasas/depositos30Dias` | ✅ 200 | n=6434, serie histórica BCRA tasa depósitos 30d | ❌ Sin uso — contexto macro |

### Endpoints NO funcionales (404)
- `/v1/finanzas/bonos` — 404, bloqueado
- `/v1/finanzas/acciones` — 404, bloqueado
- `/v1/finanzas/inflacion` — 404, bloqueado
- `/v1/finanzas/indices/uvalore` — 404 (correcto: `/v1/finanzas/indices/uva`)
- `/v1/finanzas/tasas/badlar` — 404

### Nuevos usos identificados
1. **FCI renta fija VCP** → yield actual de FCIs como "FondoSur Renta Fija" directamente por nombre
2. **Plazo fijo TNA por banco** → si BuildFuture incorpora PLAZO_FIJO como asset_type, `tnaClientes` por entidad
3. **Depósitos 30d** → proxy de tasa corta libre de riesgo ARS (para context macro en recomendaciones)

---

## 3. dolarapi.com — ✅ En uso (MEP live)

**URL:** `https://dolarapi.com/v1/dolares`
**Auth:** Sin autenticación.

### Tipos de cambio disponibles (POC 2026-04-13)

| Casa | Compra | Venta | Updated |
|------|--------|-------|---------|
| oficial | 1335 | 1385 | 17:00 |
| blue | 1385 | 1400 | 21:00 |
| bolsa (MEP) | 1398.2 | 1409.7 | 21:00 |
| contadoconliqui (CCL) | 1463.4 | 1466.9 | 21:00 |
| mayorista | 1345 | 1354 | 15:51 |
| cripto | 1466.1 | 1466.3 | 21:00 |
| tarjeta | 1735.5 | 1800.5 | 17:00 |

**Uso actual:** MEP spot en `services/mep.py` → `get_mep()`.
**Spread MEP:** compra/venta promedio ~= 1404. MEP oficial (~1400) vs CCL (~1465) = 4.6% gap.
**Nuevo uso:** Exponer spread MEP/CCL como señal de presión cambiaria en dashboard.

---

## 4. bluelytics.com.ar — ✅ En uso (histórico MEP)

**URL:** `https://api.bluelytics.com.ar/v2/latest`
**Auth:** Sin autenticación.
**Uso actual:** MepHistory en historical_prices.py para trend 60 días (devaluation.py fuente 3).

---

## 5. CoinGecko (free tier) — ✅ Nuevo POC

**URL base:** `https://api.coingecko.com/api/v3`
**Auth:** Sin autenticación para free tier (rate limited: ~30 req/min).
**Delay:** Tiempo real.

### Endpoints útiles (confirmados)

| Endpoint | Datos | Caso de uso |
|----------|-------|-------------|
| `/simple/price?ids=bitcoin,ethereum&vs_currencies=usd` | Precio spot múltiples cryptos | Precio CRYPTO en USD para posiciones manuales |
| `/coins/markets?vs_currency=usd&ids=...` | Precio + 24h change + market_cap + rank | InstrumentDetail CRYPTO con market data |
| `/search?query=bitcoin` | id, name, symbol, rank, thumb, large (logo URL) | Search bar CRYPTO en AddManualPosition |
| `/coins/{id}/market_chart?vs_currency=usd&days=30` | Precio histórico 30d OHLC | Gráfico evolución CRYPTO en InstrumentDetail |

### Sample response /coins/markets
```json
{
  "symbol": "BTC", "current_price": 74245,
  "price_change_percentage_24h": 4.8,
  "market_cap": 1485736625572, "market_cap_rank": 1
}
```

### Limitaciones
- Free tier: ~30 req/min, sin API key. Con API key demo (gratis): 30 req/min mismo.
- No hay precios ARS directos → convertir via MEP
- Sin ticker BYMA para CEDEARs (BTC/USDT no es BBTCUSDT)

### Plan de integración
- `services/coingecko_client.py` — `search_crypto(query)`, `get_crypto_price_usd(id)`, `get_crypto_market_data(id)`
- Usar en `yield_updater.py` para CRYPTO positions (precio actualizado diario)
- Usar en `AddManualPosition.tsx` para search bar CRYPTO

---

## 6. Binance API pública — ✅ Nuevo POC

**URL base:** `https://api.binance.com/api/v3`
**Auth:** Sin autenticación para datos públicos de mercado.
**Delay:** Tiempo real.

### Endpoints útiles (confirmados)

| Endpoint | Datos | Caso de uso |
|----------|-------|-------------|
| `/ticker/price?symbol=BTCUSDT` | Precio spot | Alternativa a CoinGecko para CRYPTO |
| `/ticker/24hr?symbol=ETHUSDT` | priceChange, lastPrice, volume, high, low | Stats 24h CRYPTO para InstrumentDetail |

### Sample response /ticker/24hr
```json
{
  "priceChange": "148.49", "lastPrice": "2344.70",
  "volume": "356535.90", "highPrice": "2400", "lowPrice": "2180"
}
```

### Ventajas vs CoinGecko
- Sin rate limiting estricto (uso razonable)
- Pares con USDT, USDC, BTC — flexible
- Ideal para pares: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, ADAUSDT

### Limitaciones
- Multi-ticker: `/ticker/price?symbols=["BTCUSDT","ETHUSDT"]` — requiere formato JSON en query param (distinto a lo esperado)
- Solo cripto en pares crypto/crypto — no stocks
- `binance_explore.py` ya existe en scripts/ (referencia para implementación)

---

## 7. BCRA oficial — ✅ Parcial

**URL base:** `https://api.bcra.gob.ar`
**Auth:** Sin autenticación.

### Endpoints confirmados

| Endpoint | Datos | Status |
|----------|-------|--------|
| `/estadisticascambiarias/v1.0/Cotizaciones` | 39 monedas cotización oficial hoy | ✅ 200 |
| `/cheques/v1.0/entidades` | 59 entidades bancarias | ✅ 200 |

### Limitaciones
- `/estadisticas/v2.0/Maestros/Variables` → 404 (versión incorrecta o deprecada)
- `/estadisticascambiarias/v1.0/Cotizaciones/{fecha}` → 400 (solo fecha actual)
- Requiere bypass SSL verify=False

### Uso potencial
- `tipoCotizacion` por moneda (USD, EUR, BRL, etc.) para conversiones multilaterales
- Pendiente: encontrar endpoint correcto para tasas BCRA (política monetaria, BADLAR)

---

## 8. IOL API — ✅ En uso (autenticado)

**Auth:** OAuth2, usuario/contraseña almacenados cifrados en Supabase.
**Endpoints usados:**
- `/api/v2/portafolio/{mercado}` — posiciones
- `/api/v2/Titulos/{mercado}/{simbolo}/cotizacion` — precio por ticker
- `/api/v2/Cuenta/saldo` — saldo de cuenta
- FCIs: listado y cuotapartes

**Endpoints no explorados (potenciales):**
- `/api/v2/Cotizacion/opciones/cauciones` — tasa de caución actual (fix BUG CAUCION)
- `/api/v2/operaciones` — historial de operaciones → para racha de inversión más precisa

---

## 9. ROFEX/MatbaRofex — ❌ No accesible

**Intentado:** `https://api.matbarofex.com.ar/v1/derivatives/futures` → 404
**Alternativa:** Scraping del front de ROFEX (requiere Selenium/Playwright — no viable en Railway)
**Estado:** Bloqueado hasta que expongan API pública documentada.
**Fallback activo:** Paridad LECAP/ON en devaluation.py (fuente 2, funcionando).

---

## Nuevos proveedores identificados (no probados aún)

| Proveedor | URL | Datos | Auth | Relevancia |
|-----------|-----|-------|------|-----------|
| **Pricempire** | pricempire.com/api | Precios globales | API key free | Baja — fuera de Argentina |
| **Alpha Vantage** | alphavantage.co | US stocks, FX, crypto | API key free | Media — ETFs USA |
| **Yahoo Finance (unofficial)** | query1.finance.yahoo.com | Stocks globales | Sin auth | Alta — precios ETFs en USD |
| **Open Exchange Rates** | openexchangerates.org | FX rates | API key free tier | Baja — ya tenemos dolarapi |
| **Infobae/Cronista** | — | Noticias financieras | Scraping | Baja |
| **CNV XBRL** | cnv.gob.ar | Estados contables | Sin auth | Media — datos empresa para bonos |

### Yahoo Finance (sin auth) — prioritario para ETFs
```
GET https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1d
```
Devuelve precio, volumen, OHLC para cualquier ticker USA. Sin auth.
→ Útil para InstrumentDetail ETF (SPY, QQQ, VWO, etc.)

---

## Plan de integración recomendado (priorizado)

### P1 — Alta prioridad (próximo sprint)
1. **CoinGecko** → `coingecko_client.py` para CRYPTO search + precio USD + market data
2. **ArgentinaDatos FCI renta fija/mixta VCP** → ampliar `fci_prices.py` para calcular TEA de FCIs no money market
3. **IOL cauciones** → fix BUG CAUCION con tasa real desde `/api/v2/Cotizacion/opciones/cauciones`
4. **ArgentinaDatos plazo fijo TNA** → preparar para asset_type PLAZO_FIJO

### P2 — Media prioridad
5. **Binance public** → alternativa/complemento a CoinGecko para stats 24h CRYPTO
6. **Yahoo Finance** → precios ETF USA para InstrumentDetail (SPY, QQQ, VWO)
7. **BCRA Cotizaciones** → tipo de cambio oficial para conversiones multilaterales

### P3 — Baja / deuda técnica
8. **ArgentinaDatos depósitos 30d** → contexto macro en recomendaciones (tasa libre de riesgo ARS)
9. **ROFEX** → monitorear hasta que expongan API pública

---

## Inventario de servicios actuales en codebase

| Archivo | Fuente | Función |
|---------|--------|---------|
| `services/byma_client.py` | BYMA | get_lecap_tna, get_cedear_price_ars/market_data, get_stock_price_ars/market_data, get_bond_tir, get_on_tir |
| `services/fci_prices.py` | ArgentinaDatos | get_lecap_market_tna, get_cocos_vcp, get_uva_ratio_for_cer |
| `services/mep.py` | dolarapi.com | get_mep (MEP spot) |
| `services/historical_prices.py` | bluelytics | MepHistory (MEP histórico) |
| `services/devaluation.py` | BYMA + ArgentinaDatos | get_expected_devaluation (jerarquía 4 fuentes) |
| `services/iol_client.py` | IOL API | portafolio, precios, sync |
| `services/cocos_client.py` | Cocos API | portafolio Cocos |
| `services/ppi_client.py` | PPI API | portafolio PPI |
| `scripts/binance_explore.py` | Binance | exploración (no en prod) |
