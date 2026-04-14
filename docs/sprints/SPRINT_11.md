# Sprint 11 — "STOCK Market Data + non_iol_offset + BYMA Connect Timeout"

**Inicio:** 2026-04-13
**Cierre real:** 2026-04-13
**Versión:** v0.13.0
**Objetivo:** STOCK InstrumentDetail con market data live (variación hoy, máx/mín desde BYMA Líderes), fix connect timeout BYMA desde Railway, non_iol_offset_usd en modelo.

---

## Items del Sprint

| # | Ítem | Capa | Esfuerzo | Estado | PR/Commit |
|---|------|------|----------|--------|-----------|
| 1 | `_fetch_stock_panel()` — centraliza fetch btnLideres, popula price + full cache | BE | S | ✅ Hecho | 31ec8bc |
| 2 | `get_stock_market_data(ticker)` — variación, máx/mín desde BYMA Líderes | BE | S | ✅ Hecho | 31ec8bc |
| 3 | InstrumentDetail STOCK: MetricRows variación hoy + máx/mín | FE | S | ✅ Hecho | 8569922 |
| 4 | `assetLabelWithEmoji` import fix en InstrumentDetail.tsx | FE | XS | ✅ Hecho | 8569922 |
| 5 | `httpx.Timeout(connect=5.0, read=10.0)` en todos los POST BYMA | BE | XS | ✅ Hecho | 52c0169 |
| 6 | `PortfolioSnapshot.non_iol_offset_usd` campo SQLAlchemy | BE | XS | ✅ Hecho | 99f14d1 |
| 7 | Documentar sprints 9/10/11 en BITACORA + PRODUCTO | PM | S | ✅ Hecho | a3babd0 |

---

## Daily Log

### 2026-04-13 — Implementación STOCK market data

**_fetch_stock_panel():** Nueva función privada en `byma_client.py` que:
- Hace POST a BYMA con panel `btnLideres` (24 acciones líderes Merval)
- Popula `_stock_cache` (price only, para `get_stock_price_ars()`) y `_stock_full_cache` (extended)
- Patrón idéntico a CEDEARs — reutilización máxima

**get_stock_market_data(ticker):** Interfaz pública, misma firma que `get_cedear_market_data`. Retorna `{price_ars, prev_close_ars, high_ars, low_ars, variation_pct}` o None si BYMA falla o ticker no está en Líderes.

**Frontend InstrumentDetail STOCK:** Branch `asset_type === "STOCK"` con MetricRows:
- Variación hoy con color verde/rojo según signo
- Máx / Mín del día con "20 min delay · BYMA Líderes" como sublabel

**Connect timeout fix:** BYMA era alcanzable desde Railway con intermitencia. `httpx.Timeout(connect=5.0, read=10.0)` previene que el collector cuelgue el proceso por más de 5 segundos en la fase de conexión TCP.

**non_iol_offset_usd:** Campo `Mapped[Optional[Decimal]]` en `PortfolioSnapshot` para eventual offset de posiciones no-IOL en el snapshot diario. Migración ya existía en main.py:171.

### Deploy

Dos deploys Railway: primero sin version bump (restauró v0.12.0), segundo con v0.13.0 correcto.

---

## Limitaciones conocidas al cierre

- BYMA accesible desde Railway con latencia variable — connect timeout mitiga el cuelgue pero no garantiza datos frescos
- STOCK panel (Líderes) tiene ~24 tickers — STOCKs fuera del panel → `stock_market: null`
- Tests TDD pendientes: 5 tests `test_get_stock_market_data` análogos a CEDEAR

---

## Velocidad real

7/7 ítems completados ✅
