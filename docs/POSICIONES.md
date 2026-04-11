# Posiciones — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

Las posiciones representan cada instrumento financiero del portafolio de un usuario. Pueden ser automáticas (sincronizadas desde un broker) o manuales (ingresadas por el usuario).

| Fuente | Tipos soportados | Sync |
|--------|-----------------|------|
| IOL | CEDEAR, ETF, LETRA, BOND, ON, FCI, STOCK | Automático |
| Cocos | FCI, BOND, STOCK, CASH_COCOS, CASH_COCOS_USD | Automático |
| Binance | CRYPTO | Automático |
| PPI | CEDEAR, ETF, BOND, ON, STOCK | Manual (2FA) |
| MANUAL | CRYPTO, FCI, ETF, STOCK, REAL_ESTATE, CASH | Usuario |

---

## Comportamiento esperado (invariantes)

1. **Toda mutación manual (create/update/delete) dispara `_snapshot_after_manual_change()`:** graba `PositionSnapshot` de hoy para cada posición activa + recalcula `PortfolioSnapshot` de hoy. La posición aparece en el gráfico inmediatamente, sin esperar al scheduler.

2. **`snapshot_date` en `Position`:** se setea a `date.today()` al crear la posición. Para posiciones manuales es la fecha exacta de ingreso. Para automáticas es la fecha del último sync. **No usar este campo para inferir la fecha de inicio histórica** — usar `MIN(PositionSnapshot.snapshot_date)` en su lugar.

3. **Soft delete:** las posiciones nunca se borran físicamente. `is_active = False` en delete.

4. **Tickers auto-generados (REAL_ESTATE):** formato `RESTATE_{uuid8}`. Son IDs técnicos internos — nunca mostrarlos al usuario. Usar `description` como nombre legible.

5. **CASH:** `current_value_ars` se calcula en el backend. CASH_ARS: `ppc_ars` es el monto en ARS. CASH_USD: `quantity × purchase_fx_rate`.

---

## Flujo de mutación manual

```
POST /positions/manual (create)
  → Crea Position(source=MANUAL, snapshot_date=hoy)
  → _snapshot_after_manual_change()
    → save_position_snapshots() → PositionSnapshot(ticker, hoy, value_usd) ← primer registro histórico
    → _refresh_today_snapshot()  → PortfolioSnapshot(hoy, total_usd) actualizado
  → _invalidate_score_cache()

PATCH /positions/manual/{id} (update)
  → Actualiza campos en Position
  → _snapshot_after_manual_change() ← misma lógica
  → _invalidate_score_cache()

DELETE /positions/manual/{id} (soft delete)
  → Position.is_active = False
  → _snapshot_after_manual_change() ← recalcula sin la posición eliminada
  → _invalidate_score_cache()
```

---

## Tipos de posición y su comportamiento

### CASH (CASH_ARS / CASH_USD)
- `quantity = 1`, `current_price_usd = monto_usd`
- `current_value_ars = ppc_ars` (para CASH_ARS) o `quantity × purchase_fx_rate` (para CASH_USD)
- `annual_yield_pct = 0` — el cash no rinde por defecto
- Al editar: recalcular `current_value_ars` con los valores actualizados

### REAL_ESTATE
- `ticker = RESTATE_{uuid8}` auto-generado
- `quantity = 1` siempre — la valuación va en `avg_purchase_price_usd`
- `current_price_usd = purchase_price_usd` (valuación actual)
- `annual_yield_pct = (monthly_rent_usd × 12) / purchase_price_usd`
- Al editar: si cambia `purchase_price_usd` o `monthly_rent_usd` → recalcular yield

### CRYPTO manual
- Precio live via CoinGecko (igual que Binance)
- Si el ticker no está mapeado → precio fallback desde `manual_yield_pct` y `purchase_price_usd`

### FCI / ETF / STOCK manual
- Precio via `_get_live_price_and_yield()`: ArgentinaDatos → IOL → fallback manual

---

## Campos Platform-owned vs ALYC-owned

**ALYC-owned** (se sobreescriben en cada sync): `quantity`, `current_price_usd`, `current_value_ars`, `avg_purchase_price_usd`, `ppc_ars`, `purchase_fx_rate`, `description`

**Platform-owned** (se preservan via `_get_enrichment()`): `annual_yield_pct`, `external_id`, `fci_categoria`

---

## Checklist al agregar un nuevo asset_type

- [ ] `_resolve_price_and_yield` en `positions.py`: branch o safe fallback para el nuevo tipo
- [ ] `_ASSET_CONTEXT` en `portfolio.py`: agregar entrada o fallback genérico
- [ ] `repair-user` / `backfill` en `admin.py`: ¿el nuevo tipo se cubre en reconstrucción?
- [ ] `freedom_calculator.py`: ¿aporta correctamente al capital/renta?
- [ ] `list_manual_positions`: ¿devuelve todos los campos que necesita el frontend?
- [ ] `InstrumentDetail.tsx`: branch específico o fallback
- [ ] `PortfolioTabs.tsx`: ticker/description/badge correctos
- [ ] `ASSET_BADGES`: color y label propio

---

## Bugs conocidos / deuda técnica

| # | Bug | Severidad | Archivo |
|---|-----|-----------|---------|
| 1 | `_sync_cocos` no crea `PositionSnapshot` al sincronizar (solo lo crea GET /portfolio/history) | P1 | integrations.py:1785 |
| 2 | `_sync_binance` no crea `PositionSnapshot` por ticker | P2 | integrations.py:1996 |

---

## Cambios recientes

| Fecha | Cambio |
|-------|--------|
| 2026-04-11 | `create/update/delete` manual ahora dispara `_snapshot_after_manual_change()` → resuelve BUG-2 de TENENCIA.md |
| 2026-04-10 | `REAL_ESTATE`: ticker auto-generado `RESTATE_{uuid}`, yield desde renta mensual |
| 2026-04-03 | PR #29: fix ppc per-100VN para BOND/ON en IOL |

---

## Decisiones de diseño

**Por qué soft delete:** las posiciones son parte del historial financiero. Borrarlas físicamente rompería la reconstrucción de snapshots históricos para esa posición. Con `is_active=False` el registro persiste y la auditoría es posible.

**Por qué `snapshot_date` no es la fecha de inicio real:** las posiciones automáticas actualizan `snapshot_date` en cada sync. El campo refleja el ÚLTIMO sync, no el primero. La fecha real de inicio se deriva de `MIN(PositionSnapshot.snapshot_date)`.
