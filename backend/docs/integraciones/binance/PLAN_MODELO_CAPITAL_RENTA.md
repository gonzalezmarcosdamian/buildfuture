# Plan: Modelo Capital vs Renta — Normalización multi-ALYC + Binance

**Fecha:** 2026-04-03  
**Alcance:** Modelo financiero unificado, integración Binance completa, ajustes UI/UX, escalabilidad

---

## 1. El problema actual

El modelo actual mezcla conceptos:
- `monthly_return_usd` en `PortfolioSnapshot` se calcula como `total_usd × 0.008` (hardcoded)
- El yield de CEDEAR/crypto (especulativo) se suma a la freedom bar igual que el de una LECAP (real)
- No hay separación explícita entre activos de **renta** y activos de **capital**
- El `DashboardHero` ya tiene las secciones Renta / Capital en UI, pero el backend no modela esa distinción

---

## 2. Modelo financiero correcto

### 2.1 Clasificación por asset_type

| Asset type | Categoría | Renta mensual | Capital |
|------------|-----------|---------------|---------|
| LETRA | Renta | yield diario capitalizable → mensual ✅ | No |
| FCI | Renta | TNA / 12 × tenencia ✅ | No |
| BOND / ON | Renta | cupón mensual estimado desde yield ✅ | No |
| CEDEAR | Capital | No (dividendos son marginales) | Sí |
| ETF | Capital | No | Sí |
| CRYPTO | Capital | No | Sí |
| STOCK | Capital | No | Sí |

**Regla:** Solo generan renta los activos con flujo periódico predecible.  
Crypto/CEDEAR/ETF son apreciación de capital — su yield 30d NO entra en `monthly_return_usd`.

### 2.2 Nuevo cálculo de monthly_return_usd (backend)

```python
RENTA_TYPES = {"LETRA", "FCI", "BOND", "ON"}

def compute_monthly_return(positions: list[Position]) -> float:
    """
    Renta mensual real = suma de (valor_usd × annual_yield_pct / 12)
    solo para activos de renta. Crypto/CEDEAR/ETF no aportan renta.
    """
    total = 0.0
    for p in positions:
        if p.asset_type.upper() not in RENTA_TYPES:
            continue
        value_usd = float(p.quantity) * float(p.current_price_usd or 0)
        yield_monthly = float(p.annual_yield_pct or 0) / 12
        total += value_usd * yield_monthly
    return round(total, 2)
```

### 2.3 Separación capital_total_usd vs renta_total_usd

```python
CAPITAL_TYPES = {"CEDEAR", "ETF", "CRYPTO", "STOCK"}

def compute_capital_total(positions: list[Position]) -> float:
    return sum(
        float(p.quantity) * float(p.current_price_usd or 0)
        for p in positions
        if p.asset_type.upper() in CAPITAL_TYPES
    )

def compute_renta_total(positions: list[Position]) -> float:
    return sum(
        float(p.quantity) * float(p.current_price_usd or 0)
        for p in positions
        if p.asset_type.upper() in RENTA_TYPES
    )
```

Estos valores ya existen parcialmente en el endpoint `GET /portfolio` — hay que agregarlos explícitamente.

---

## 3. Cambios en backend

### 3.1 `GET /portfolio` — response ampliada

```python
# Agregar al response actual:
{
  # Ya existe:
  "total_usd": 5279.85,
  "monthly_return_usd": 45.20,   # CORREGIDO: solo renta real

  # Nuevo desglose:
  "capital_total_usd": 2150.00,   # CEDEAR + ETF + CRYPTO
  "renta_total_usd":   3129.85,   # LETRA + FCI + BOND + ON
  "crypto_total_usd":   19.98,    # subset de capital — útil para UI

  # Por fuente (para el breakdown en UI):
  "by_source": {
    "IOL":     {"total_usd": 5259.87, "capital_usd": 2130.02, "renta_usd": 3129.85},
    "COCOS":   {"total_usd": 0.0,     "capital_usd": 0.0,     "renta_usd": 0.0},
    "BINANCE": {"total_usd": 19.98,   "capital_usd": 19.98,   "renta_usd": 0.0},
  }
}
```

### 3.2 `PortfolioSnapshot` — campo monthly_return_usd corregido

Hoy: `monthly_return_usd = total_usd × 0.008` (hardcoded, incorrecto).  
Fix: calcular desde posiciones activas con `compute_monthly_return()` al momento del snapshot.

```python
# En reconstruct_portfolio_history y en el sync diario:
monthly_return = compute_monthly_return(current_positions)
snapshot = PortfolioSnapshot(
    ...
    monthly_return_usd=Decimal(str(monthly_return)),
)
```

### 3.3 Migración de snapshots existentes

Los snapshots históricos tienen `monthly_return_usd` incorrecto. Al purgar y regenerar (que ya se hace al sync), se recalculan automáticamente.

### 3.4 `GET /portfolio/history` — campos nuevos en cada punto

```python
# Cada HistoryPoint agrega:
{
  "total_usd": 5279.85,
  "monthly_return_usd": 45.20,
  "capital_total_usd": 2150.00,   # nuevo
  "renta_total_usd": 3129.85,     # nuevo
}
```

### 3.5 Binance sync — integración en el flujo

```
sync_binance_positions()
  → get_positions() → Position con source="BINANCE", asset_type="CRYPTO"
  → compute_monthly_return() no los incluye (CRYPTO no es renta)
  → capital_total_usd sí los incluye
  → get_snapshot_history() → PortfolioSnapshot histórico 30d con solo cripto
     (se suma a los snapshots existentes de IOL/Cocos)
```

**Merge de snapshots multi-source:** para una misma fecha, si ya existe un snapshot de IOL y llega uno de Binance:
- No se duplican — se actualiza `total_usd` sumando el valor crypto del día
- Campo `positions_count` se incrementa

---

## 4. Cambios en frontend

### 4.1 `DashboardHero` — ya tiene la estructura correcta

El componente ya divide en "Renta mensual" y "Capital acumulado". Solo necesita consumir los nuevos campos del backend:

```typescript
// Props actuales → agregar:
interface Props {
  // ...existentes...
  capitalTotalUsd: number      // CEDEAR + ETF + CRYPTO (ya existe parcialmente)
  rentaTotalUsd: number        // LETRA + FCI + BOND + ON  ← nuevo
  cryptoTotalUsd: number       // subset de capital ← nuevo
  bySource: SourceBreakdown    // nuevo — para badges por ALYC
}
```

### 4.2 `FreedomBar` — sin cambios de UI, solo datos correctos

```
freedomPct = monthlyReturnUSD / monthlyExpensesUSD
```

Con el fix del backend, `monthlyReturnUSD` ya no incluye crypto → la barra refleja libertad real.  
**No hay cambio de componente** — el fix es puramente en el dato que recibe.

### 4.3 `PerformanceChart` — nuevo modo "Por tipo"

Agregar un tercer `ChartMode` además de `tenencia` / `rendimiento`:

```typescript
type ChartMode = "tenencia" | "rendimiento" | "composicion"
```

**Modo `composicion`:** área apilada mostrando:
- Renta (verde esmeralda)
- Capital (violeta)
- Crypto (amarillo Binance)

Esto permite ver en el tiempo cómo evoluciona la estructura del portfolio.

### 4.4 Sección Binance en `/portfolio`

**Tab o sección "Crypto"** dentro de PortfolioTabs:

```
Tabs: Todos | IOL | Cocos | Binance
```

Cuando el usuario tiene Binance conectado:
- Badge amarillo en cada posición crypto
- Total crypto separado visualmente
- Tooltip: "Valor de mercado — sin renta proyectada (activo de capital)"

### 4.5 Modal `RentaModal` — clarificar qué entra y qué no

Agregar nota explicativa:

```
💡 Solo incluye activos de renta (LECAP, FCI, Bonos).
   CEDEAR, ETF y Crypto son capital — no generan renta mensual estimada.
```

### 4.6 `ConnectBinanceForm` — nuevo componente (1 paso)

```typescript
// components/integrations/ConnectBinanceForm.tsx
// Formulario simple:
// - API Key (input text)
// - Secret Key (input password)
// - Tooltip: instrucciones paso a paso para generar la key
// - Badge: "⚡ Auto-sync habilitado — sin 2FA requerido"
// - Estado: loading → éxito → onSuccess()
```

### 4.7 `IntegrationCard` — agregar BINANCE a providerMeta

```typescript
BINANCE: {
  label: "Binance",
  description: "Crypto spot (read-only)",
  color: "text-yellow-400",
  bgColor: "bg-yellow-950/30",
  borderColor: "border-yellow-900/30",
  form: <ConnectBinanceForm onSuccess={onSuccess} />,
}
```

### 4.8 SOURCE_BADGES — badge amarillo Binance

```typescript
// components/portfolio/PortfolioClient.tsx o donde estén los badges:
SOURCE_BADGES: {
  IOL:     { label: "IOL",     className: "bg-blue-950 text-blue-400 border-blue-900" },
  COCOS:   { label: "COCOS",   className: "bg-orange-950 text-orange-400 border-orange-900" },
  BINANCE: { label: "BINANCE", className: "bg-yellow-950 text-yellow-400 border-yellow-900" },
  MANUAL:  { label: "MANUAL",  className: "bg-slate-800 text-slate-400 border-slate-700" },
}
```

---

## 5. Historial multi-source — merge de snapshots

**Problema:** IOL tiene snapshots desde Mar 30. Binance tiene snapshots desde Mar 4 (30d).  
Las fechas donde solo hay Binance no tienen snapshot de IOL todavía.

**Solución — snapshot aditivo:**

```python
def upsert_snapshot(db, user_id, date, total_usd_delta, positions_count_delta, mep):
    """
    Si ya existe snapshot para esa fecha: suma el delta.
    Si no existe: crea uno nuevo.
    Esto permite que cada fuente contribuya al snapshot del día.
    """
    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.user_id == user_id,
        PortfolioSnapshot.snapshot_date == date,
    ).first()

    if existing:
        existing.total_usd += Decimal(str(total_usd_delta))
        existing.positions_count += positions_count_delta
    else:
        db.add(PortfolioSnapshot(
            user_id=user_id,
            snapshot_date=date,
            total_usd=Decimal(str(total_usd_delta)),
            monthly_return_usd=Decimal("0"),  # recalcular al final del día
            positions_count=positions_count_delta,
            fx_mep=Decimal(str(mep)),
            cost_basis_usd=Decimal("0"),
        ))
```

**Resultado:** el gráfico de historial muestra desde Mar 4 (Binance) con solo crypto, y desde Mar 30 suma IOL encima. El área apilada en modo `composicion` lo hace visual y claro.

---

## 6. Escalabilidad — próximos brokers

El modelo está diseñado para que agregar un nuevo broker sea:

1. Nuevo `BrokerClient` con `get_positions()` → lista de `Position` con `source="NUEVO"`
2. Las funciones `compute_monthly_return()` y `compute_capital_total()` ya lo manejan por `asset_type`
3. `upsert_snapshot()` suma automáticamente sin romper el historial existente
4. Frontend: solo agregar entry en `SOURCE_BADGES` y `providerMeta`

No hay código específico por broker en el modelo financiero — todo es agnóstico a la fuente.

---

## 7. Resumen de cambios por archivo

### Backend
| Archivo | Cambio |
|---------|--------|
| `app/services/portfolio_calculator.py` | Nuevo (o en `portfolio.py`): `compute_monthly_return`, `compute_capital_total`, `compute_renta_total` |
| `app/routers/portfolio.py` | `GET /portfolio` agrega `capital_total_usd`, `renta_total_usd`, `crypto_total_usd`, `by_source` |
| `app/routers/portfolio.py` | `GET /portfolio/history` agrega `capital_total_usd`, `renta_total_usd` por punto |
| `app/services/historical_reconstructor.py` | Fix `monthly_return_usd` usando `compute_monthly_return` |
| `app/services/binance_client.py` | Nuevo |
| `app/routers/integrations.py` | Endpoints `/binance/connect`, `/sync`, `/disconnect` |
| `app/scheduler.py` | `_maybe_sync_binance` en `_daily_close_job` |
| `app/services/snapshot_service.py` | Nuevo (o inline): `upsert_snapshot` aditivo |

### Frontend
| Archivo | Cambio |
|---------|--------|
| `components/freedom-bar/FreedomBar.tsx` | Sin cambios — fix es en el dato |
| `components/portfolio/DashboardHero.tsx` | Consume `rentaTotalUsd`, `cryptoTotalUsd`, `bySource` |
| `components/portfolio/PerformanceChart.tsx` | Nuevo ChartMode `composicion` con área apilada |
| `components/portfolio/PortfolioTabs.tsx` | Tab "Binance/Crypto" cuando conectado |
| `components/portfolio/RentaModal.tsx` | Nota aclaratoria sobre qué genera renta |
| `components/integrations/ConnectBinanceForm.tsx` | Nuevo |
| `components/integrations/IntegrationCard.tsx` | `providerMeta["BINANCE"]` |
| `components/portfolio/PortfolioClient.tsx` | `SOURCE_BADGES["BINANCE"]` |

---

## 8. Orden de implementación

```
Sprint 1 — Modelo financiero correcto (sin Binance):
  1. compute_monthly_return / compute_capital_total en backend
  2. Fix monthly_return_usd en reconstructor y sync
  3. GET /portfolio agrega capital_total_usd, renta_total_usd
  4. DashboardHero consume nuevos campos
  5. RentaModal con nota aclaratoria
  6. Tests: test_compute_monthly_return (RED → GREEN)

Sprint 2 — Binance Iter 1:
  7. tests/test_binance_client.py (RED)
  8. binance_client.py (GREEN)
  9. upsert_snapshot aditivo
  10. integrations.py — endpoints binance
  11. scheduler — _maybe_sync_binance
  12. ConnectBinanceForm + providerMeta + SOURCE_BADGES
  13. Smoke test completo

Sprint 3 — Historial y visualización:
  14. GET /portfolio/history agrega capital/renta por punto
  15. PerformanceChart modo composicion (área apilada)
  16. PortfolioTabs tab Crypto/Binance
```

---

## 9. Definition of Done global

- [ ] `monthly_return_usd` nunca incluye yield especulativo de crypto/CEDEAR
- [ ] Freedom bar = renta real / gastos reales (sin especulación)
- [ ] Capital y renta visibles por separado en DashboardHero
- [ ] Binance conectado → posiciones en portfolio con badge BINANCE
- [ ] Historial 30d de Binance se suma al gráfico al conectar
- [ ] Gráfico modo composición muestra Renta + Capital + Crypto apilados
- [ ] Agregar un nuevo broker futuro requiere tocar solo 4 archivos (client, integrations, scheduler, IntegrationCard)
- [ ] Tests pasan, ruff + eslint + tsc sin errores
