# Yields y rentabilidad — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

El sistema de yields reales fue implementado en PR #16 (feature/real-yields, abril 2026). Los yields se actualizan diariamente a las 17:30 ART junto al cierre del scheduler.

### Archivos clave

| Archivo | Rol |
|---------|-----|
| `backend/app/services/yield_updater.py` | Servicio central — calcula yields reales por tipo |
| `backend/app/scheduler.py` | Dispara `_update_yields(db, mep)` en daily close (17:30) |
| `backend/app/routers/integrations.py` | Llama `update_yields` post-sync para tener yield correcto inmediatamente |
| `backend/app/services/iol_client.py` | `get_live_yields()` para LECAPs |
| `backend/tests/test_yield_updater.py` | 36 tests |

---

## Flujo de annual_yield_pct

```
Sync IOL/Cocos/Binance/PPI
  └─ annual_yield_pct = DEFAULT_YIELDS[tipo]
       (0.68 LETRA, 0.08 FCI, 0.09 BOND, 0 CASH, 0 CRYPTO sin datos)

Post-sync inmediato
  └─ update_yields(db, mep) → enriquece inmediatamente

Daily close (17:30 ART)
  └─ yield_updater.update_yields(db, mep)
       ├─ LETRA  → TIR real (precio actual + días al vencimiento desde ticker)
       ├─ FCI    → ArgentinaDatos: promedio mercadoDinero o exacto si tiene external_id
       ├─ BOND/ON → tabla _BOND_YTM calibrada a precios de mercado
       └─ CRYPTO  → CoinGecko: variación 30d anualizada
```

---

## Comportamiento esperado (invariantes)

1. `annual_yield_pct` en el sync viene siempre de `DEFAULT_YIELDS`, nunca del proveedor. Los valores del proveedor (ej. `result_percentage` de Cocos) son retornos históricos, no yields anualizados.
2. `annual_yield_pct` es **Platform-owned**: se preserva entre syncs via `_get_enrichment()` si fue enriquecido por `yield_updater` (distinto al DEFAULT del tipo).
3. El scheduler llama `get_mep()` UNA sola vez y lo pasa a `_update_yields`. No duplicar llamadas HTTP.
4. Si `price_per_100 >= 100` para LECAP → retornar DEFAULT_TNA (0.68), no TIR negativa.

---

## Yields por tipo de instrumento

### LETRA (LECAP, LEDE)
- TIR real calculada desde precio actual y días al vencimiento del ticker.
- Precio: `valorizado / cantidad` del portfolio IOL (puede superar 100 per 100 VN para LECAPs vencidas).
- Si `price_per_100 >= 100` → usar DEFAULT_TNA (0.68).
- `_parse_lecap_maturity(ticker)` extrae fecha de vencimiento del nombre del ticker. Si no parseable → 180 días proxy.
- Convención: `current_value_ars / quantity * 100` da `price_per_100` en el rango [70-100].

### FCI
- Si tiene `external_id` → yield exacto de ArgentinaDatos por nombre de fondo.
- Si no → `_fci_market_avg_yield()`: promedio de categoría `mercadoDinero` (una sola llamada HTTP, cacheada por batch).
- Cap: 150% TNA máximo (detectado IOLCAMA matcheando incorrectamente a 198.8%).
- IOLCAMA/IOLMMA: IOL los clasifica como BOND pero son FCI. Override en `_TICKER_TYPE_OVERRIDES`.
- Cocos Pesos Plus: `fci_prices.py` busca solo en `mercadoDinero` — puede dar yield incorrecto (está en `rentaMixta`/`rentaVariable`).

### BOND / ON
- Tabla estática `_BOND_YTM` en `yield_updater.py`, calibrada a precios de mercado abril 2026.
- Actualizar cuando precios cambien ±5pp.
- ONs argentinas (ARC1O, DNC5O, TLCMO, YM34O, etc.) no calibradas → DEFAULT 9%.
- CAUCION: hardcodeado 30% — aproximación razonable hoy. Escalar a P1 si tasa cambia ±5pp.
- Cupones son semestrales pero se muestran como renta mensual prorrateada (aceptado).

### CRYPTO (Binance + manual)
- CoinGecko: variación de precio 30d → anualizada como yield estimado.
- Stablecoins: yield = 0%.
- Si CoinGecko no tiene precio → skip con WARNING.

### REAL_ESTATE (manual)
- `annual_yield_pct = (monthly_rent_usd × 12) / purchase_price_usd`
- Se recalcula en cada `update_manual_position` si cambia renta o valuación.

### CASH
- `annual_yield_pct = 0` — el cash no rinde (puede cambiar si se integra plazo fijo en el futuro).

---

## Arquitectura ALYC-owned vs Platform-owned

El patrón deactivate-all → INSERT-new en cada sync destruía el yield enriquecido. Solución (PR #17): `_get_enrichment(db, user_id, source)`.

**Regla:** `annual_yield_pct` se preserva solo si es distinto al DEFAULT del tipo. Posiciones nuevas siguen recibiendo el DEFAULT normalmente, luego se enriquecen en el próximo `update_yields`.

---

## Zonas calientes para conflictos

| Archivo | Qué toca | Conflicto probable con |
|---|---|---|
| `yield_updater.py` | `_BOND_YTM` dict | Ramas que actualicen precios de bonos manualmente |
| `scheduler.py` | orden del job diario | Ramas que agreguen pasos al daily close |
| `integrations.py` | construcción de `Position` en sync | Cualquier rama que agregue campos al sync |
| `portfolio.py /instrument/{ticker}` | serialización del detalle | Ramas que extiendan el endpoint de detalle |
| `InstrumentDetail.tsx` | sección P&L hero + PositionMetrics | Ramas que rediseñen el detalle |

---

## Bugs conocidos / deuda técnica

| # | Bug | Severidad | Workaround |
|---|-----|-----------|------------|
| 1 | LETRA CER (X-prefix: X29Y6, X18E7): TIR real pendiente, devuelve 0% como fallback | P1 | Mostrar 0% |
| 2 | Cocos Pesos Plus: `fci_prices.py` busca solo en `mercadoDinero`, debería buscar en `rentaMixta` también | P1 | Yield promedio categoría equivocado |
| 3 | CAUCION yield hardcodeado 30% | P2 | Razonable hoy si tasa estable |
| 4 | ArgentinaDatos `/v1/finanzas/bonos` retorna 404 | P2 | Tabla `_BOND_YTM` como único fallback |
| 5 | ONs argentinas sin calibrar en `_BOND_YTM` | P2 | DEFAULT 9% |
| 6 | `_BOND_YTM` tabla estática — no se actualiza automáticamente | Deuda | Actualización manual periódica |

---

## Cambios recientes

| Fecha | Cambio |
|-------|--------|
| 2026-04-02 | PR #16: yield_updater.py, 36 tests, yields reales por tipo |
| 2026-04-02 | PR #17: `_get_enrichment()` preserva annual_yield_pct entre syncs |
| 2026-04-02 | Fix: LECAP price_per_100 >= 100 → DEFAULT_TNA en lugar de TIR negativa |

---

## Decisiones de diseño

**Por qué no usar `result_percentage` de Cocos:** es el retorno del período de tenencia, no un yield anualizado. Comparar entre instrumentos requiere que todos usen la misma convención (yield anualizado). `yield_updater` garantiza esta consistencia.

**Por qué tabla estática `_BOND_YTM` y no API en tiempo real:** las APIs de YTM calculado (data912, BYMA) requieren modelar flujos de caja por instrumento. Es un proyecto en sí mismo. La tabla estática es suficientemente precisa para el uso actual (libertad financiera, no trading).
