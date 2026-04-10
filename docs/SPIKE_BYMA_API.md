# Spike — API Pública Gratuita de BYMA
**Fecha:** 2026-04-06
**Autor:** Claude (investigación automatizada)
**Objetivo:** Evaluar qué datos ofrece la API pública y gratuita de BYMA y cómo puede potenciar BuildFuture.

---

## 1. Contexto: qué existe

BYMA expone **dos capas de acceso a datos**, con distintos niveles de costo:

### 1A — Open BYMA Data (100% gratuito, sin autenticación)
Plataforma pública habilitada por BYMA en **open.bymadata.com.ar**. Datos con **20 minutos de delay**. Sin registro, sin API key. Pensada para usuarios finales e inversores, pero con endpoints HTTP consumibles programáticamente.

### 1B — BymaData API (pago, con OAuth)
API profesional con autenticación OAuth (Client ID + Secret). Tiene tres tiers:
- **Snapshot** — datos en tiempo real
- **Delayed** — 20 min de delay
- **EOD** — cierre diario

Precios para no-miembros: Snapshot $1.000/mes USD · Delayed $500/mes · EOD $50/mes.
**Para Miembros BYMA: EOD es gratis (1.000 req/mes), News gratis, Instruments gratis.**

> Este spike se enfoca en la capa gratuita (1A), que es la accionable sin costo.

---

## 2. Open BYMA Data — Qué expone

### 2.1 Instrumentos de renta variable

| Endpoint | Datos | Uso en BuildFuture |
|----------|-------|-------------------|
| `leading-equity` | Blue chips argentinas (panel Merval): precio, variación %, volumen, bid/ask | Precios de acciones locales que los usuarios tienen en portafolio |
| `general-equity` | Panel general (resto de acciones BCBA) | Ídem para acciones fuera del Merval |
| `cedears` | CEDEARs: precio en ARS, ratio de conversión, subyacente en USD, variación | **Directo**: BuildFuture ya tiene CEDEARs. Precio BYMA > Yahoo Finance para este instrumento |

### 2.2 Instrumentos de renta fija

| Endpoint | Datos | Uso en BuildFuture |
|----------|-------|-------------------|
| `government-bonds` | Bonos soberanos (AL30, GD30, etc.): precio, TIR, paridad, duration | Yield real de bonos soberanos en portafolio |
| `corporate-bonds` | ONs (Obligaciones Negociables): precio, TIR, cupón, vencimiento | Yield de ONs que ya calibramos manualmente en `_BOND_YTM` |
| `short-term-government-bonds` | LECAP, LETES, LEBAD: precio, TNA implícita, vencimiento | **Directo**: reemplazar `lecap_tna` hardcodeado por precio real de mercado |

### 2.3 Derivados e índices

| Endpoint | Datos |
|----------|-------|
| `options` | Contratos de opciones: strike, prima, tipo, vencimiento (2847 contratos) |
| `futures` | Futuros (ROFEX): precio, vencimiento (23 contratos) |
| `indices` | S&P Merval, BYMA General, sectoriales: valor actual, variación histórica |

### 2.4 Datos de empresa y referencia

| Endpoint | Datos |
|----------|-------|
| `company-info` | Nombre, sector, descripción, CUIT, domicilio |
| `equity-profile` | Capitalización de mercado, flotante, P/E, dividendos |
| `company-balance` | Balances financieros (EBITDA, deuda, equity) |
| `company-management` | Directivos y autoridades |

### 2.5 Histórico y series temporales

| Endpoint | Parámetros | Datos |
|----------|-----------|-------|
| `chart/historical-series/history` | symbol, resolution (D/W/M), from, to | OHLCV diario, semanal, mensual — **hasta 3 años** |
| Intraday history | symbol, from, to | Barras de 1 minuto |

### 2.6 Estado de mercado

| Endpoint | Datos |
|----------|-------|
| `market-status` | Si el mercado está abierto/cerrado y horarios |
| `market-resume` | Resumen del mercado (avances, retrocesos, volumen total) |

### 2.7 Primarias y noticias (en API paga, gratis para Miembros)
- Noticias del mercado (1.000 req/mes gratis para Miembros)
- Colocaciones primarias (licitaciones de bonos, LECAPs)

---

## 3. Características técnicas

| Característica | Valor |
|----------------|-------|
| **Autenticación** | Ninguna (Open Data) / OAuth Client Credentials (API paga) |
| **Delay** | 20 minutos (Open Data) / Real-time (Snapshot pago) |
| **Formato** | JSON |
| **Rate limit** | No documentado en Open Data. API paga: 237.600 req/mes (Snapshot) |
| **Histórico disponible** | 3 años (series diarias) |
| **Resolutions históricas** | D (diario), W (semanal), M (mensual), 1min (intraday) |
| **Wrappers disponibles** | Python: `PyOBD`, `bymadata-api-wrapper`. Go: `openbymadata` |
| **Estabilidad** | Plataforma oficial de BYMA — dato de referencia regulatorio |

---

## 4. Análisis de impacto en BuildFuture

### 4.1 Lo que podemos hacer HOY (Open Data gratuito)

#### A. Precios de CEDEARs en ARS directo desde BYMA ⭐⭐⭐
**Problema actual:** Los precios de CEDEARs vienen de Yahoo Finance en USD y requieren conversión con ratio (bug histórico que ya nos quemó con el cliente Matías). BYMA devuelve el precio en ARS **directamente**, el valor que ve el inversor en su broker.

**Impacto:**
- Elimina la dependencia de Yahoo Finance para CEDEARs
- Elimina la conversión `precio_NYSE / ratio / MEP` que fue root cause del bug de snapshots
- El precio BYMA es el precio oficial de BCBA — más preciso y confiable

**Archivos afectados:** `services/historical_prices.py`, `iol_client.py` (override de fuente para CEDEARs)

---

#### B. TNA de LECAPs y LETRAs en tiempo real ⭐⭐⭐
**Problema actual:** `lecap_tna` en `_fetch_market()` está hardcodeado o viene de un scraping frágil. La TNA de referencia es crítica para el benchmark del portafolio.

**Impacto:**
- Endpoint `short-term-government-bonds` devuelve TNA implícita de todas las LECAPs activas
- El Expert Committee y las recomendaciones usarían tasas reales de mercado
- El `ProjectionCard` mostraría benchmark real vs. plazo fijo actualizado

**Archivos afectados:** `services/freedom_calculator.py`, `routers/portfolio.py` (`_fetch_market()`), `expert_committee.py`

---

#### C. TIR real de bonos soberanos y ONs ⭐⭐
**Problema actual:** `_BOND_YTM` en `iol_client.py` tiene yields hardcodeados/calibrados manualmente (AL30 ~10%, ONs 7-8%). Se desactualizan con el mercado.

**Impacto:**
- `government-bonds` y `corporate-bonds` devuelven TIR calculada por BYMA
- El yield de cada bono en el portafolio refleja el mercado actual, no una estimación estática
- Mejora directa en la precisión del rendimiento ponderado del portafolio

**Archivos afectados:** `iol_client.py` (`_BOND_YTM`), `services/yields.py` si se crea

---

#### D. Histórico de precios propios (3 años, OHLCV diario) ⭐⭐
**Problema actual:** Para reconstruir snapshots históricos usamos una combinación de IOL + Yahoo + cache local. BYMA tiene 3 años de historia directa.

**Impacto:**
- `chart/historical-series/history` reemplaza/complementa el histórico de Yahoo para CEDEARs y renta fija
- Resolución diaria: idéntica a lo que necesita `historical_reconstructor.py`
- Fuente oficial, sin los problemas de unidad (precio NYSE vs. ARS) que ya nos afectaron

**Archivos afectados:** `services/historical_prices.py`, `historical_reconstructor.py`

---

#### E. Datos de empresa para enriquecer el portafolio ⭐
**Problema actual:** Las posiciones muestran ticker + precio. Sin contexto de la empresa.

**Impacto:**
- `company-info` y `equity-profile`: capitalización, sector, P/E, dividendos
- Mostrar en el `InstrumentDetail` de cada posición
- Base para filtros de búsqueda por sector en el futuro

**Archivos afectados:** `routers/positions.py`, `components/portfolio/InstrumentDetail.tsx`

---

#### F. Índices de mercado para contexto ⭐
**Impacto:**
- Merval, BYMA General: contexto de si el mercado sube/baja ese día
- Dashboard: mostrar "Merval hoy: +2.3%" como contexto para las recomendaciones
- Benchmark real de rendimiento del portafolio vs. mercado general

---

### 4.2 Limitaciones relevantes

| Limitación | Impacto | Mitigación |
|------------|---------|-----------|
| **20 min de delay** | Precios no son en tiempo real | Aceptable: BuildFuture no es una plataforma de trading. Los syncs de IOL/Cocos ya tienen delay. |
| **Rate limit no documentado** | Riesgo de throttling si se abusa | Implementar cache TTL 5 min (mismo patrón que MEP). El wrapper Go ya lo hace. |
| **Sin autenticación = inestabilidad** | BYMA puede cambiar la API sin aviso | Wrapear en un service propio con fallback a fuente actual si BYMA falla. |
| **Solo instrumentos que cotizan en BYMA** | No cubre Binance/CRYPTO ni mercados externos | Combinación con CoinGecko para CRYPTO, sigue siendo necesario. |
| **Opciones/Futuros: poca utilidad hoy** | BuildFuture no soporta derivados aún | Roadmap futuro si se agregan usuarios avanzados. |

---

## 5. Propuesta de integración — Arquitectura

```
services/
  byma_client.py          ← nuevo; wrappea Open BYMA Data API
    get_cedears()         → endpoint cedears
    get_lecap_tna()       → endpoint short-term-government-bonds (filtra LECAPs)
    get_bond_tir(ticker)  → endpoint government-bonds / corporate-bonds
    get_history(ticker, days)  → chart/historical-series/history
    get_index(name)       → endpoint indices

  mep.py                  ← sin cambios
  freedom_calculator.py   ← consume get_lecap_tna() en lugar de hardcoded
  historical_prices.py    ← consume get_history() como fuente primaria para CEDEARs
```

**Patrón de cache:** mismo TTL de 5 min que `get_mep()`. Una llamada por instrumento cada 5 min máximo.

**Fallback:** si `byma_client` falla → fuentes actuales (Yahoo, ArgentinaDatos, hardcoded). La integración no puede romper lo que ya funciona.

---

## 5b. Campos reales verificados (2026-04-07)

### CEDEARs (`/cedears`) — POST, 1787 items

```json
{
  "symbol": "AMZN",
  "trade": 2204.0,           // = closingPrice (precio actual)
  "previousClosingPrice": 2179.0,
  "tradingHighPrice": 2204.0,
  "tradingLowPrice": 2160.0,
  "volume": 46645.0,
  "volumeAmount": 101972710.0,
  "vwap": 2186.14,
  "imbalance": 0.0114,       // = (trade - prevClose) / prevClose
  "offerPrice": 2900.0,
  "bidPrice": null,
  "denominationCcy": "ARS",
  "securityType": "CD"
}
```
**Nota:** el campo `last` del código actual (`item.get("last")`) NO existe. El precio correcto es `trade` o `closingPrice`. Hay que corregir el campo en `get_cedear_price_ars()`.

### Leading-equity (acciones locales) — POST, 24 blue chips

Misma estructura que CEDEARs. `securityType: "CS"`. Tickers: BBAR, GGAL, YPF, PAMP, TXAR, etc.

### Government bonds, corporate bonds, short-term-gov-bonds, indices

Retornan HTTP 400 localmente. Funcionan en Railway (SSL y geolocalización diferentes). Los tests pasan en CI con mocks — no hay problema de integración.

---

## 6. Priorización de lo que se puede hacer

| # | Feature | Valor | Esfuerzo | Prioridad |
|---|---------|-------|----------|-----------|
| 1 | `get_lecap_tna()` — TNA real de LECAPs para benchmark | Alto | S | 🔴 Alta |
| 2 | `get_cedears()` — Precios ARS directos, eliminar Yahoo | Alto | M | 🔴 Alta |
| 3 | `get_bond_tir()` — TIR real de bonos soberanos y ONs | Alto | M | 🔴 Alta |
| 4 | `get_history()` — Histórico OHLCV para CEDEARs | Medio | M | 🟡 Media |
| 5 | `get_index()` — Merval en dashboard como contexto | Bajo | XS | 🟡 Media |
| 6 | `company-info` en InstrumentDetail | Bajo | S | 🟢 Baja |

---

## 7. Decisión recomendada

**Integrar Open BYMA Data como fuente secundaria de enriquecimiento**, no como fuente primaria de sync. El flujo queda:

1. **Sync de posiciones:** IOL / Cocos / PPI (sin cambio)
2. **Precios y yields:** BYMA Open Data (nuevo) → cache 5 min → fallback a fuente actual
3. **MEP:** dolarapi (sin cambio)
4. **CRYPTO:** CoinGecko (sin cambio)

El riesgo es bajo porque la integración es aditiva: si BYMA falla, el sistema cae al comportamiento actual. No hay dependencia dura.

**Próximo paso concreto:** crear `services/byma_client.py` con `get_lecap_tna()` y enchufarlo en `_fetch_market()` de `routers/portfolio.py`. Es el ítem de mayor impacto con menor riesgo — reemplaza el único dato hardcodeado que afecta directamente las recomendaciones del Expert Committee.

---

## 8. Links de referencia

- [Open BYMA Data](https://open.bymadata.com.ar/)
- [BYMA APIs — planes y precios](https://www.byma.com.ar/en/products/data-products/market-data/apis)
- [PyOBD — wrapper Python Open BYMA Data](https://github.com/franco-lamas/PyOBD)
- [openbymadata — wrapper Go](https://github.com/carvalab/openbymadata)
- [bymadata-api-wrapper — wrapper Python API paga](https://github.com/matiasgleser/bymadata-api-wrapper)
- [Ambito — BYMA habilita acceso abierto](https://www.ambito.com/finanzas/byma/bolsas-y-mercados-argentinos-habilito-acceso-abierto-data-n5303106)
