# SPIKE — Fuentes de Datos Externas BuildFuture
**Fecha:** 2026-04-13 (actualizado 2026-04-14) | **Autor:** Claude (SM + analista financiero)
**Objetivo:** Mapeo completo de proveedores de datos disponibles, POC realizado, casos de uso e integración recomendada.

---

## Resumen ejecutivo

| Proveedor | Auth | Estado | Usos actuales | Nuevos usos confirmados por POC |
|-----------|------|--------|---------------|---------------------------------|
| BYMA Open Data | ❌ Ninguna | ✅ Activo | Letras, CEDEARs, STOCKs, Bonos, ONs | — |
| ArgentinaDatos | ❌ Ninguna | ✅ Activo (parcial) | FCI dinero, UVA, plazo fijo | FCI renta fija/mixta VCP |
| dolarapi.com | ❌ Ninguna | ✅ Activo | MEP live | Blue, CCL, spread MEP/CCL |
| bluelytics.com.ar | ❌ Ninguna | ✅ Activo | MEP histórico | — |
| **data912.com** | ❌ Ninguna | ✅ **Nuevo POC** | — | Precio bonos/ONs/CEDEARs/STOCKs live + OHLC histórico |
| CoinGecko (free) | ❌ Ninguna | ✅ Nuevo POC | — | Precio CRYPTO USD + market data + search |
| Binance (public) | ❌ Ninguna | ✅ Nuevo POC | scripts/binance_explore.py | Precio CRYPTO/USDT tiempo real, 24h stats |
| **Yahoo Finance** | ❌ Ninguna | ✅ **Nuevo POC** | — | Precio ETF/stock USA + OHLC 1y + search |
| BCRA (oficial) | ❌ Ninguna | ✅ Parcial | — | 39 monedas cambio oficial |
| IOL API | ✅ OAuth2 | ✅ Activo | Portafolio, precios, FCI | cauciones, historial operaciones |
| Cocos API | ✅ Token | ✅ Activo | Portafolio | — |
| PPI API | ✅ OAuth | ✅ Activo | Portafolio | — |
| Alpha Vantage | ✅ API key | ⚠️ Demo bloqueado | — | Requiere API key gratuita (registro) |
| ROFEX/MatbaRofex | ❌ Ninguna | ❌ No accesible | devaluation.py (intento) | Futuros devaluación implícita |
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
| `btnTitPublicos` | ✅ TIR bonos (null) | ~60 bonos | `symbol`, `vwap`, `impliedYield` (null siempre) |
| `btnObligNegociables` | ✅ TIR ONs (null) | ~200 ONs | `symbol`, `vwap`, `impliedYield` (null siempre) |
| `btnGeneral` | ❌ Sin uso | Todo el mercado | idem |

### Fichatécnica (por ticker)
**URL:** POST `/bnown/fichatecnica/especies/general` body: `{"symbol": "S31G6"}`
**Datos:** `fechaEmision`, `fechaVencimiento`, `interes` (TEM contractual), `denominacion`
**Bug conocido:** `fechaEmision` a veces devuelve año corrupto (`"0206-02-27"` en lugar de `"2026-02-27"`). Fix en `_parse_date()` con guard año < 2000.

### Limitaciones
- `impliedYield` en btnTitPublicos y btnObligNegociables viene `null` → usar data912 o tabla fallback para YTM
- IP de Railway bloqueada intermitentemente → `httpx.Timeout(connect=5.0, read=10.0)` mitigado

---

## 2. ArgentinaDatos — ✅ Activo (parcial)

**URL base:** `https://api.argentinadatos.com`
**Auth:** Sin autenticación. CORS libre.

### Endpoints confirmados

| Endpoint | Status | Datos | Uso actual |
|----------|--------|-------|-----------|
| `/v1/finanzas/fci/mercadoDinero/ultimo` | ✅ | n=382 FCIs money market, VCP+CCP | ✅ fci_prices.py |
| `/v1/finanzas/fci/rentaFija/ultimo` | ✅ | n=1958 FCIs renta fija, VCP | ❌ Pendiente integrar |
| `/v1/finanzas/fci/rentaVariable/ultimo` | ✅ | n=305 FCIs renta variable | ❌ Pendiente |
| `/v1/finanzas/fci/rentaMixta/ultimo` | ✅ | n=974 FCIs mixtos | ❌ Pendiente |
| `/v1/finanzas/indices/uva` | ✅ | n=3666 puntos diarios | ✅ byma_client.py (CER) |
| `/v1/cotizaciones/dolares` | ✅ | n=29207, hist completo | ✅ MepHistory |
| `/v1/finanzas/tasas/plazoFijo` | ✅ | n=30, TNA por banco | ❌ Nuevo: PLAZO_FIJO |
| `/v1/finanzas/tasas/depositos30Dias` | ✅ | n=6434, serie hist BCRA | ❌ Contexto macro |

### Endpoints NO funcionales (404)
- `/v1/finanzas/bonos`, `/v1/finanzas/acciones`, `/v1/finanzas/inflacion`, `/v1/finanzas/tasas/badlar`

---

## 3. dolarapi.com — ✅ En uso (MEP live)

**URL:** `https://dolarapi.com/v1/dolares`
**Auth:** Sin autenticación.

### Tipos de cambio disponibles

| Casa | Compra | Venta | Actualización |
|------|--------|-------|---------------|
| oficial | 1335 | 1385 | 17:00 |
| blue | 1385 | 1400 | 21:00 |
| bolsa (MEP) | 1398.2 | 1409.7 | 21:00 |
| contadoconliqui (CCL) | 1463.4 | 1466.9 | 21:00 |
| mayorista | 1345 | 1354 | 15:51 |
| cripto | 1466.1 | 1466.3 | 21:00 |
| tarjeta | 1735.5 | 1800.5 | 17:00 |

**Uso actual:** `services/mep.py` → `get_mep()` usa el MEP (bolsa).
**Nuevo uso potencial:** Spread MEP/CCL como señal macro en dashboard; blue para referencia.

---

## 4. bluelytics.com.ar — ✅ En uso (histórico MEP)

**URL:** `https://api.bluelytics.com.ar/v2/latest`
**Auth:** Sin autenticación.
**Uso actual:** `MepHistory` en `historical_prices.py` para trend 60 días (devaluation.py fuente 3).

---

## 5. data912.com — ✅ POC completado (2026-04-14)

**URL base:** `https://data912.com`
**Auth:** Sin autenticación. CORS libre.
**Docs:** `https://data912.com` (Swagger UI) · `https://data912.com/openapi.json`
**Rate limit:** Sin documentar. Sin API key requerida.
**Delay:** Tiempo real (datos de BYMA procesados por data912).
**Autor:** Milton Casco — proyecto open data argentino.

### Endpoints disponibles (16 total, todos confirmados)

#### Live prices

| Endpoint | Items | Campos clave | Caso de uso |
|----------|-------|--------------|-------------|
| `GET /live/mep` | 301 | `ticker, bid, ask, close, mark, v_ars, v_usd, ars_bid, ars_ask, usd_bid, usd_ask, panel` | **MEP live por CEDEAR** (precio ARS + USD) |
| `GET /live/ccl` | 249 | `ticker_usa, ticker_ar, CCL_bid, CCL_ask, CCL_close, CCL_mark, ars_volume, arg_panel, usa_panel` | **CCL live por acción/CEDEAR** |
| `GET /live/arg_bonds` | 162 | `symbol, q_bid, px_bid, px_ask, q_ask, v, q_op, c, pct_change` | **Precio bonos soberanos live** (GD30, AL35, AE38...) |
| `GET /live/arg_corp` | 573 | idem | **Precio ONs corporativas live** (573 ONs!) |
| `GET /live/arg_notes` | 27 | idem | **Letras/LECAP del Tesoro** (alternativa a BYMA btnLetras) |
| `GET /live/arg_cedears` | 822 | idem | **Precio CEDEARs** (822, más que BYMA panel) |
| `GET /live/arg_stocks` | 95 | idem | **Acciones ARG** (Merval + panel general) |
| `GET /live/usa_adrs` | 207 | `symbol, q_bid, px_bid, px_ask, c, pct_change` en USD | **ADRs NYSE/NASDAQ en USD** |
| `GET /live/usa_stocks` | n/a | idem | Stocks USA en USD |

#### Historical (OHLC)

| Endpoint | Profundidad | Campos | Caso de uso |
|----------|-------------|--------|-------------|
| `GET /historical/stocks/{ticker}` | GGAL desde 2001 (6177 puntos!) | `date, o, h, l, c, v, dr, sa` | Gráfico histórico acciones ARG |
| `GET /historical/cedears/{ticker}` | AAPL desde 2012 (3255 pts) | idem | Gráfico histórico CEDEARs |
| `GET /historical/bonds/{ticker}` | GD30 desde 2021 (1112 pts) | idem + `sa` (vol ajustado?) | **Gráfico histórico bonos** |

#### EOD / Analytics

| Endpoint | Datos | Caso de uso |
|----------|-------|-------------|
| `GET /eod/volatilities/{ticker}` | Risk analytics USA stocks | Análisis riesgo ETFs |
| `GET /eod/option_chain/{ticker}` | Option chains USA | Opciones USA |

### Samples de respuesta

```python
# /live/arg_bonds — precio bonos live
{'symbol': 'GD30', 'q_bid': ..., 'px_bid': 91200, 'px_ask': 91500,
 'q_ask': ..., 'v': ..., 'q_op': ..., 'c': 91500, 'pct_change': 0.27}

# /live/mep — MEP por CEDEAR (precio ARS + USD simultáneo)
{'ticker': 'AAL', 'bid': 1400.85, 'ask': 1430.29, 'close': 1406.84, 'mark': 1415.57,
 'v_ars': 167151300.0, 'v_usd': 20837.7, 'ars_bid': 8195.0, 'ars_ask': 8310.0,
 'usd_bid': 5.81, 'usd_ask': 5.85, 'panel': 'cedear'}

# /live/ccl — CCL implícito por par
{'ticker_usa': 'YPF', 'ticker_ar': 'YPFD', 'CCL_bid': 1455.71, 'CCL_ask': 1473.71,
 'CCL_close': 1463.79, 'CCL_mark': 1464.68, 'ars_volume': 18122860125.0}

# /historical/bonds/GD30
{'date': '2021-09-17', 'o': 7175.0, 'h': 7220.0, 'l': 7130.0, 'c': 7165.0,
 'v': 20505722.0, 'dr': -0.0015, 'sa': 0.2165}
```

### Plan de integración

**P1 — YTM de bonos y ONs desde precio live:**
- `services/data912_client.py` — `get_bond_price(ticker)`, `get_on_price(ticker)`, `get_bond_history(ticker)`
- Calcular YTM desde `c` (precio) + flujos de pago del bono → reemplazar `_BOND_YTM` tabla hardcodeada
- ONs: `c` (precio) como input para calcular TIR implícita (cuando < 100 = descuento, cuando > 100 = prima)

**P2 — Gráfico histórico en InstrumentDetail:**
- BOND/ON: `GET /historical/bonds/{ticker}` → gráfico OHLC similar al de PerformanceChart
- CEDEAR: `GET /historical/cedears/{ticker}` → complemento/alternativa a data actual

**P3 — MEP implícito por CEDEAR:**
- `GET /live/mep` → ver dispersión del MEP por CEDEAR (AAL vs AAPL vs YPF)
- Útil para mostrar qué CEDEARs tienen mayor/menor spread CCL vs MEP

### Limitaciones
- No expone YTM/TIR directamente → hay que calcularlo desde precio + flujos (fecha vencimiento, cupones)
- `arg_notes` (27 letras) puede no coincidir 1:1 con nomenclatura BYMA para LECAPs
- Sin autenticación → podría limitar rate por IP sin aviso

---

## 6. CoinGecko (free tier) — ✅ POC completado

**URL base:** `https://api.coingecko.com/api/v3`
**Auth:** Sin autenticación (rate limited: ~30 req/min).

### Endpoints confirmados

| Endpoint | Datos | Caso de uso |
|----------|-------|-------------|
| `/simple/price?ids=bitcoin,ethereum&vs_currencies=usd` | Precio spot múltiples cryptos | CRYPTO precio actual |
| `/coins/markets?vs_currency=usd&ids=...` | Precio + 24h % + market_cap + rank | InstrumentDetail CRYPTO |
| `/search?query=bitcoin` | id, name, symbol, rank, logo URL | Search bar AddManualPosition |
| `/coins/{id}/market_chart?vs_currency=usd&days=30` | OHLC histórico 30d | Gráfico CRYPTO |

### Plan de integración
- `services/coingecko_client.py` — `search_crypto(q)`, `get_crypto_price_usd(id)`, `get_crypto_market_data(id)`

---

## 7. Binance API pública — ✅ POC completado

**URL base:** `https://api.binance.com/api/v3`
**Auth:** Sin autenticación para datos públicos.

### Endpoints útiles

| Endpoint | Datos | Caso de uso |
|----------|-------|-------------|
| `/ticker/price?symbol=BTCUSDT` | Precio spot | Alternativa CoinGecko |
| `/ticker/24hr?symbol=ETHUSDT` | priceChange, lastPrice, volume, high, low | Stats 24h InstrumentDetail |

### Ventajas vs CoinGecko
- Sin rate limiting estricto
- Pares USDT/USDC/BTC — flexible
- `scripts/binance_explore.py` ya existe (referencia para implementación)

---

## 8. Yahoo Finance (unofficial) — ✅ POC completado (2026-04-14)

**URL base:** `https://query1.finance.yahoo.com`
**Auth:** Sin autenticación. Sin API key.
**Delay:** Tiempo real (15 min delay en mercado USA cerrado).
**Nota:** API no oficial, puede cambiar sin aviso. Estable desde hace años.

### Endpoints confirmados

| Endpoint | Status | Datos confirmados | Caso de uso |
|----------|--------|-------------------|-------------|
| `/v8/finance/chart/{symbol}?interval=1d&range=5d` | ✅ 200 | `regularMarketPrice`, `fiftyTwoWeekHigh`, `fiftyTwoWeekLow`, `chartPreviousClose`, OHLC array | **Precio ETF/stock USA + histórico** |
| `/v8/finance/chart/{symbol}?interval=1d&range=1y` | ✅ 200 | 250 puntos OHLC diario | Gráfico 1 año InstrumentDetail ETF |
| `/v1/finance/search?q={query}&quotesCount=5&newsCount=0` | ✅ 200 (query2) | `symbol, shortname, longname, quoteType` | Search bar ETF/stock USA |
| `/v7/finance/quote?symbols=A,B,C` | ❌ 401 | — | Multi-ticker no disponible sin auth |

### Samples

```python
# /v8/finance/chart/SPY?interval=1d&range=5d
meta = {
    'symbol': 'SPY', 'currency': 'USD', 'instrumentType': 'ETF',
    'regularMarketPrice': 686.1,
    'fiftyTwoWeekHigh': 697.84, 'fiftyTwoWeekLow': 508.46,
    'chartPreviousClose': 658.93  # cierre anterior
}

# /v8/finance/chart/QQQ
'regularMarketPrice': 617.39, 'fiftyTwoWeekHigh': 637.01

# /v1/finance/search?q=SPY
quotes[0] = {'symbol': 'SPY', 'longname': 'State Street SPDR S&P 500 ETF Trust',
             'quoteType': 'ETF', 'exchange': 'PCX'}
```

### Plan de integración

**P1 — InstrumentDetail ETF:**
- `services/yahoo_client.py` — `get_etf_price_usd(ticker)`, `get_etf_market_data(ticker)`, `search_etf(q)`
- InstrumentDetail ETF: variación hoy, 52w high/low, precio actual USD
- Análogo a `get_cedear_market_data()` pero para ETFs USA

**P2 — Gráfico histórico 1y:**
- `GET /v8/finance/chart/{symbol}?interval=1d&range=1y` → array de closes para PerformanceChart en InstrumentDetail ETF

### Limitaciones
- API no oficial → puede romperse sin aviso (riesgo aceptable — gratuita)
- Multi-ticker bulk request no disponible → una llamada por ETF (cachear bien)
- Solo tickers USA — no ARG

---

## 9. Alpha Vantage — ⚠️ Requiere registro (gratis)

**URL base:** `https://www.alphavantage.co/query`
**Auth:** API key gratuita (registro en alphavantage.co, < 20 segundos).
**Rate limit free:** 25 req/día (muy bajo). Plan pagado: 75 req/min.
**POC:** Demo key bloqueada — confirmar con key real.

### Endpoints de interés (documentados, no POC sin key)

| Función | Datos | Rate |
|---------|-------|------|
| `TIME_SERIES_DAILY&symbol=IBM` | OHLC diario USA stocks/ETFs | 1 req |
| `CURRENCY_EXCHANGE_RATE&from=BTC&to=USD` | Cripto spot | 1 req |
| `GLOBAL_QUOTE&symbol=AAPL` | Quote actual | 1 req |

**Veredicto:** 25 req/día es muy bajo para uso en producción. Yahoo Finance es mejor alternativa para ETFs (sin límite, sin auth). Descartar Alpha Vantage salvo acceso a plan pagado.

---

## 10. BCRA oficial — ✅ Parcial

**URL base:** `https://api.bcra.gob.ar`
**Auth:** Sin autenticación. Requiere `verify=False` (certificado SSL propio).

### Endpoints confirmados

| Endpoint | Datos | Status |
|----------|-------|--------|
| `/estadisticascambiarias/v1.0/Cotizaciones` | 39 monedas cotización oficial hoy (AUD, BRL, EUR, USD, GBP...) | ✅ 200 |
| `/cheques/v1.0/entidades` | 59 entidades bancarias | ✅ 200 |

### Limitaciones
- `/estadisticas/v2.0/` → 404 (versión deprecada o incorrecta)
- `/estadisticascambiarias/v1.0/Cotizaciones/{fecha}` → 400 (solo fecha actual)
- Requiere `ssl.CERT_NONE` en requests

---

## 11. IOL API — ✅ En uso (autenticado)

**Auth:** OAuth2, credenciales cifradas en Supabase.
**Endpoints usados:** `/portafolio/`, `/Titulos/cotizacion`, `/Cuenta/saldo`, FCIs.
**Endpoints potenciales:**
- `/api/v2/Cotizacion/opciones/cauciones` → tasa caución real (fix BUG CAUCION)
- `/api/v2/operaciones` → historial → racha de inversión más precisa

---

## 12. ROFEX/MatbaRofex — ❌ No accesible

**Intentado:** `https://api.matbarofex.com.ar/v1/derivatives/futures` → 404
**Estado:** Bloqueado. Monitorear hasta que expongan API pública.
**Fallback activo:** Paridad LECAP/ON en devaluation.py (fuente 2, 19.4% actual).

---

## Plan de integración recomendado (priorizado)

### P1 — Alta prioridad

| # | Tarea | Fuente | Archivo | Impacto |
|---|-------|--------|---------|---------|
| 1 | `coingecko_client.py` — search + precio + market data CRYPTO | CoinGecko | services/ | InstrumentDetail CRYPTO live |
| 2 | `yahoo_client.py` — precio + 52w + histórico ETF USA | Yahoo Finance | services/ | InstrumentDetail ETF live |
| 3 | `data912_client.py` — precio live bonos/ONs | data912 | services/ | Reemplazar tabla _BOND_YTM hardcodeada |
| 4 | ArgentinaDatos FCI renta fija/mixta VCP | ArgentinaDatos | fci_prices.py | Yield FCIs no money market |
| 5 | IOL cauciones TNA real | IOL | iol_client.py | Fix BUG CAUCION |

### P2 — Media prioridad

| # | Tarea | Fuente | Impacto |
|---|-------|--------|---------|
| 6 | Gráfico OHLC histórico BOND/CEDEAR/STOCK en InstrumentDetail | data912 | UX: gráfico evolución |
| 7 | Gráfico OHLC histórico ETF en InstrumentDetail | Yahoo Finance | UX: gráfico ETF |
| 8 | MEP implícito por CEDEAR (dispersión) | data912 /live/mep | Dashboard: señal macro |
| 9 | BCRA Cotizaciones — conversiones multilaterales | BCRA | Conversiones EUR/BRL |

### P3 — Baja / deuda técnica

| # | Tarea | Fuente | Impacto |
|---|-------|--------|---------|
| 10 | Depósitos 30d como tasa libre de riesgo ARS | ArgentinaDatos | Contexto macro recomendaciones |
| 11 | Binance como alternativa/backup CoinGecko | Binance | Redundancia CRYPTO |
| 12 | ROFEX futuros | MatbaRofex | devaluation.py fuente 1 (404 hoy) |

---

## Inventario de servicios actuales en codebase

| Archivo | Fuente | Función |
|---------|--------|---------|
| `services/byma_client.py` | BYMA | get_lecap_tna, get_cedear_price_ars/market_data, get_stock_price_ars/market_data, get_bond_tir, get_on_tir, get_cer_letter_tir |
| `services/fci_prices.py` | ArgentinaDatos | get_lecap_market_tna, get_cocos_vcp, get_uva_ratio_for_cer, get_fci_yield_by_name |
| `services/mep.py` | dolarapi.com | get_mep (MEP spot) |
| `services/historical_prices.py` | bluelytics | MepHistory (MEP histórico 60d) |
| `services/devaluation.py` | BYMA + ArgentinaDatos + bluelytics | get_expected_devaluation (4 fuentes, 19.4% actual) |
| `services/iol_client.py` | IOL API | portafolio, precios, sync, FCI |
| `services/cocos_client.py` | Cocos API | portafolio Cocos |
| `services/ppi_client.py` | PPI API | portafolio PPI |
| `scripts/binance_explore.py` | Binance | exploración (no en prod) |
| — | CoinGecko | ❌ Por implementar: coingecko_client.py |
| — | Yahoo Finance | ❌ Por implementar: yahoo_client.py |
| — | data912 | ❌ Por implementar: data912_client.py |
