# SUPPORT PLAYBOOK — Precios Históricos & Snapshots

> Última actualización: 2026-04-03 (PR #29)

---

## 1. Hallazgos críticos (no cometer de nuevo)

### 1.1 Unit mismatch: BOND/ON y LETRA son "per 100 VN nominal"

**Síntoma**: El campo `ppc` (precio promedio de compra) de IOL para BOND, ON y LETRA
viene expresado **en ARS por cada 100 VN nominal** (convención BYMA), NO por unidad.
`current_price_usd = valorizado / cantidad / mep` sí está por unidad.
Antes del fix el `ppc_usd` de AL30 era `61.74` mientras que `current_price_usd` era `0.61`.

**Fix aplicado** en `iol_client.py`:
```python
avg_price_ars = (ppc / Decimal("100")) if asset_type in ("LETRA", "BOND", "ON") else ppc
```

**Afecta**: cualquier cálculo de rendimiento/ganancia sobre posiciones BOND/ON/LETRA.
Revisar si aparece discrepancia entre `ppc_usd` y `current_price_usd` de ratio ~100x.

---

### 1.2 Yahoo Finance devuelve precio NYSE (no precio CEDEAR ARS/MEP)

**Síntoma**: Snapshot inflado. AMZN en Yahoo = USD 210 (NYSE). AMZN CEDEAR en IOL = ARS 210k/138 = USD 1.52.
Ratio = 138x. Un portfolio de USD 135K aparecía como USD 3.7M.

**Causa raíz**: `yfinance` descarga el precio de la acción en NYSE, no el precio del CEDEAR
en Buenos Aires. Los CEDEARs tienen una relación de equivalencia (ej: 1 AMZN CEDEAR = 1/138 AMZN NYSE).

**Fix aplicado** en `historical_reconstructor.py`:
1. IOL seriehistorica se usa **primero** para todos los tickers CEDEAR/ETF.
   IOL retorna ARS/unidad → dividir por MEP = precio USD correcto del CEDEAR.
2. Yahoo solo como fallback. Si se usa Yahoo, se calcula el equivalente:
   ```python
   equiv = round(yahoo_price / current_price_usd)  # ej: round(210 / 1.52) = 138
   price = raw_yahoo / equiv  # corrige al precio CEDEAR
   ```

**Almacenamiento**: Se usa UPSERT en `price_history` para que precios IOL sobreescriban precios Yahoo:
```sql
INSERT INTO price_history (ticker, price_date, price_usd, source)
VALUES (:ticker, :price_date, :price_usd, :source)
ON CONFLICT (ticker, price_date) DO UPDATE
SET price_usd = EXCLUDED.price_usd, source = EXCLUDED.source
```

**Campo `source`**: `"IOL"` para CEDEAR, `"IOL_BOND"` para BOND/ON, `"YAHOO"` para fallback Yahoo.
Al re-cachear IOL, el cache lookup ignora filas con `source = "YAHOO"`:
```python
cached = {r.price_date: float(r.price_usd) for r in rows if r.source in ("IOL_BOND", "IOL")}
```

---

### 1.3 Tipos de activo desconocidos aparecen como STOCK en IOL

**Síntoma**: NDT25 (bono dual soberano) vino de IOL como tipo `STOCK` y era ignorado
en la reconstrucción de snapshots.

**Fix**: `_TICKER_TYPE_OVERRIDES` en `iol_client.py`:
```python
"NDT25": "BOND",
"NDT26": "BOND",
"NDT27": "BOND",
```

**Regla**: Si un instrumento financiero aparece como STOCK pero claramente no lo es,
agregar el override. Los bonos duales y similares son frecuentes candidatos.

---

## 2. Endpoints de soporte (admin)

Todos requieren header `X-Admin-Key: <ADMIN_SECRET_KEY>`.

### Diagnóstico

```
GET /admin/support/snapshot-health?user_id=<uid>
```
Devuelve:
- Conteo de snapshots
- Valor promedio, mínimo, máximo
- Flag `inflation_detected: true` si `max > 5 * avg`
- Últimos 5 snapshots con fecha y valor

### Reparación completa de usuario

```
POST /admin/support/repair-user?user_id=<uid>&purge_snapshots=true
```
1. Purga todos los snapshots del usuario (opcional con `purge_snapshots=true`)
2. Dispara re-sync completo desde IOL
3. Devuelve IDs de posiciones re-sincronizadas

### Limpiar caché de precios por fuente

```
DELETE /admin/cache/price-source-purge?source=YAHOO
DELETE /admin/cache/price-source-purge?source=YAHOO&ticker=AMZN
```
Purga filas de `price_history` por fuente (YAHOO / IOL / IOL_BOND) opcionalmente filtrado por ticker.

---

## 3. Procedimiento de reparación de cuenta inflada

Cuando un usuario reporta valores de portfolio absurdamente altos:

```bash
# 1. Diagnosticar
curl -H "X-Admin-Key: $ADMIN_KEY" \
  "https://api-production-7ddd6.up.railway.app/admin/support/snapshot-health?user_id=<uid>"

# 2. Verificar si hay precios Yahoo inflados en caché
# (inspeccionar price_history con tickers CEDEAR del usuario)

# 3. Limpiar precios Yahoo del caché
curl -X DELETE -H "X-Admin-Key: $ADMIN_KEY" \
  "https://api-production-7ddd6.up.railway.app/admin/cache/price-source-purge?source=YAHOO"

# 4. Reparar usuario (purge snapshots + re-sync IOL con precios correctos)
curl -X POST -H "X-Admin-Key: $ADMIN_KEY" \
  "https://api-production-7ddd6.up.railway.app/admin/support/repair-user?user_id=<uid>&purge_snapshots=true"

# 5. Verificar resultado
curl -H "X-Admin-Key: $ADMIN_KEY" \
  "https://api-production-7ddd6.up.railway.app/admin/support/snapshot-health?user_id=<uid>"
# Esperar: inflation_detected: false, avg ~ valor real del portfolio
```

---

## 4. Fuentes de precios por tipo de activo

| Tipo       | Fuente primaria          | Conversión                        | Fallback        |
|------------|--------------------------|-----------------------------------|-----------------|
| BOND / ON  | IOL seriehistorica (ARS) | `(ars / 100) / mep`               | Interpolación lineal |
| LETRA      | IOL (ppc ya /100)        | `ars / mep`                       | —               |
| CEDEAR     | IOL seriehistorica (ARS) | `ars / mep`                       | Yahoo + equiv   |
| ETF        | IOL seriehistorica (ARS) | `ars / mep`                       | Yahoo + equiv   |
| STOCK      | Yahoo Finance (USD)      | directo                           | —               |
| CRYPTO     | Yahoo Finance (USD)      | directo                           | —               |
| CASH USD   | 1.0 (constante)          | —                                 | —               |
| FCI        | IOL (valorizado/cant)    | valorizado/cant/mep               | —               |

**data912.com.ar**: Solo precios en vivo de bonos (`/live/arg_bonds`).
No tiene histórico. Útil para YTM actualizado. Ya integrado en `yield_updater.py`.

---

## 5. Casos conocidos que requieren override de tipo

| Ticker  | Tipo IOL | Override correcto | Razón                         |
|---------|----------|-------------------|-------------------------------|
| NDT25   | STOCK    | BOND              | Bono dual soberano            |
| NDT26   | STOCK    | BOND              | Bono dual soberano            |
| NDT27   | STOCK    | BOND              | Bono dual soberano            |
| XBMUSD  | BOND     | FCI               | FCI de liquidez USD           |
| RPC3O   | BOND     | ON                | ON corporativa                |
| DNC5O   | BOND     | ON                | ON corporativa                |

Ver `_TICKER_TYPE_OVERRIDES` en `backend/app/services/iol_client.py` para lista completa.

---

## 6. Diagnóstico rápido via SQL directo

```sql
-- Ver últimos snapshots de un usuario
SELECT date, total_usd FROM portfolio_snapshots
WHERE user_id = '<uid>'
ORDER BY date DESC LIMIT 10;

-- Ver fuentes de precios para un ticker
SELECT price_date, price_usd, source FROM price_history
WHERE ticker = 'AMZN'
ORDER BY price_date DESC LIMIT 10;

-- Detectar tickers con precios Yahoo en cache (potencialmente inflados)
SELECT ticker, COUNT(*) as filas, AVG(price_usd) as avg_usd
FROM price_history
WHERE source = 'YAHOO'
GROUP BY ticker ORDER BY avg_usd DESC;
```
