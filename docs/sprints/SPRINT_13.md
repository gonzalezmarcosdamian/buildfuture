# Sprint 13 — Datos externos + fixes de rentabilidad
**Fecha:** 2026-04-13  
**Rama:** main (commits directos)

## Objetivo
Integrar fuentes de datos externas para enriquecer InstrumentDetail con market data en tiempo real, y corregir bugs de rentabilidad en ARS/USD e infraestructura.

---

## Entregables

### 1. Fix navbar scroll (WebKit/Safari)
**Problema:** `body { overflow-x: hidden }` crea scroll container en Safari → BottomNav pierde `position: fixed` al hacer scroll.  
**Fix:** Eliminar `overflow-x: hidden` de `body`. Mantener `html { overflow-x: clip }` (clip no crea scroll container).  
**Archivo:** `frontend/app/globals.css` — commit `b2698b1`

### 2. Renta ARS vs USD en InstrumentDetail
**Problema:** LECAP y FCI mostraban la misma TNA en modo ARS y USD. En USD debería mostrarse el yield real descontando la devaluación esperada.  
**Fix:**
- BE: `portfolio.py` expone `real_yield_usd_pct` = `max(0, (1+TNA)/(1+devaluation) - 1)` + `expected_devaluation_pct`
- FE: `InstrumentDetail.tsx` usa `real_yield_usd_pct` para ARS instruments en modo USD; label "Yield real USD"
**Commits:** `f10a495`, `b2698b1`

### 3. BYMA `_parse_date` — año corrupto en CER
**Problema:** BYMA fichatecnica retorna `"0206-02-27"` (año 206) para algunos bonos CER.  
**Fix:** Guard `if parsed.year < 2000 or parsed.year > 2100: return None` en `_parse_date()`.  
**Archivo:** `backend/app/services/byma_client.py` — commit `a1e6d7a`

### 4. POC + documentación fuentes de datos externas
Investigación y prueba de 6 proveedores. Resultado en `docs/SPIKE_DATA_SOURCES_2026_04.md`.  
**Veredicto:** CoinGecko ✅ · data912 ✅ · Yahoo Finance ✅ · Alpha Vantage ❌ (25 req/day) · Binance P2 · ROFEX P3.  
**Commit:** `75d17e1`

### 5. `data912_client.py` — nuevo cliente de datos argentina
Fuente: [data912.com](https://data912.com) — open data, sin auth, sin rate limit documentado.  
**Funciones:** `get_bond_price()`, `get_on_price()`, `get_cedear_price()`, `get_mep_by_cedear()`, `get_ccl_by_ticker()`, `get_bond_history()`, `get_cedear_history()`.  
Cache 5 min en memoria. 822 CEDEARs, 573 ONs, 162 bonos.  
**Archivo:** `backend/app/services/data912_client.py` — commit `40c0549`

### 6. CoinGecko `get_market_data()` para CRYPTO
**Función:** `crypto_prices.get_market_data(coingecko_id)` → `{price_usd, change_24h_pct, high_24h, low_24h, market_cap, market_cap_rank, volume_24h}`.  
**Commit:** `40c0549`

### 7. Yahoo Finance `get_market_data()` para ETF/STOCK USA
**Función:** `external_prices.get_market_data(ticker)` → `{price_usd, change_pct, prev_close, week52_high, week52_low, name, currency, exchange}`.  
API: `query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d` (no auth).  
**Commit:** `40c0549`

### 8. InstrumentDetail — market data CRYPTO / ETF / BOND / ON
`portfolio.py /instrument/{ticker}` incluye `crypto_market`, `etf_market`, `bond_market`.  
`InstrumentDetail.tsx` muestra MetricRows específicos por tipo:
- CRYPTO: Variación 24h · Máx/Mín 24h · Market Cap rank
- ETF: Variación hoy · Máx/Mín 52 semanas
- BOND/ON: Variación día · Bid/Ask live de data912
**Commits:** `40c0549` (BE), `95c3092` (FE)

### 9. Fix BUG CAUCION — TNA real desde IOL
**Problema:** `DEFAULT_YIELDS["cauciones"] = 0.30` hardcodeado, no refleja tasa de mercado.  
**Fix:** `IOLClient.get_caucion_tna()` → GET `/api/v2/Cotizacion/opciones/cauciones`, toma el plazo más corto. Fetch lazy en `get_portfolio()`, fallback a 0.30 si IOL no responde.  
**Archivo:** `backend/app/services/iol_client.py` — commit `a254ebf`

---

## Bugs encontrados durante el sprint (no scope)
- `expert_committee.py` logueaba WARNING por `yfinance` no instalado → downgrade a DEBUG (commit `a1e6d7a`)
- `yield_updater: 0/31` en logs normales → comportamiento correcto cuando yields no cambian

---

## Próximos pasos (Sprint 14)
1. `AddManualPosition.tsx` — SearchBar CRYPTO con debounce vía `search_coins`
2. Tests P1: `test_portfolio.py` (endpoint más crítico sin cobertura)
3. ON InstrumentDetail — label "TIR X%" + emisor desde `description`
4. `db.rollback()` en sync IOL/PPI/Cocos antes del commit de error
