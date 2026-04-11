# Freedom Score y Barra de Libertad — BuildFuture

> Última revisión: 2026-04-11

---

## Estado actual

El Freedom Score es la métrica central de BuildFuture: qué porcentaje de los gastos mensuales cubre el rendimiento del portafolio. Se calcula en `backend/app/services/freedom_calculator.py` y se muestra como barra de progreso en el dashboard.

---

## Comportamiento esperado (invariantes)

1. **`freedom_pct = monthly_return_usd / monthly_expenses_usd`** — porcentaje de cobertura de gastos.
2. Solo los activos de **renta** contribuyen a `monthly_return_usd`. Los activos de capital (CEDEAR, ETF, CRYPTO) no generan renta mensual predecible.
3. `monthly_expenses_usd` viene de la configuración del usuario (budget). Si no está configurado → `freedom_pct = 0`.
4. La barra se invalida (`_invalidate_score_cache`) tras cualquier mutación de posición.

---

## Clasificación de activos (buckets)

```
RENTA (generan ingreso mensual predecible):
  LETRA, FCI, REAL_ESTATE
  → renta_monthly += value × annual_yield_pct / 12

CAPITAL (crecimiento, no renta):
  CEDEAR, ETF, CRYPTO, CASH
  → capital_total += value
  → NO contribuyen a monthly_return

AMBOS (BOND, ON — split 50/50):
  → 50% a renta_monthly (cupón)
  → 50% a capital_total (apreciación)

NEUTRAL (STOCK, OTHER):
  → no contribuyen a ningún bucket
```

---

## Fórmula Freedom Score

```python
def calculate_freedom_score(positions, monthly_expenses_usd):
    buckets = split_portfolio_buckets(positions)
    monthly_return = buckets["renta_monthly_usd"]
    
    # annual_return_pct: para proyecciones de milestones
    annual_return_pct = monthly_return * 12 / renta_total  # si renta_total > 0
    
    freedom_pct = monthly_return / monthly_expenses_usd
    
    return {
        portfolio_total_usd,  # suma de todas las posiciones
        monthly_return_usd,   # renta mensual del bucket renta
        monthly_expenses_usd, # gastos del usuario
        freedom_pct,          # la barra
        annual_return_pct,    # para proyecciones de milestones
    }
```

---

## Milestones y proyecciones

```python
def calculate_milestone_projections(
    current_portfolio_usd,
    monthly_savings_usd,
    monthly_expenses_usd,
    annual_return_pct,
    milestones = [0.25, 0.50, 0.75, 1.00]  # 25%, 50%, 75%, 100% libertad
):
    # Para cada milestone:
    required_capital = (monthly_expenses_usd × target_pct × 12) / annual_return_pct
    # Meses hasta llegar: búsqueda binaria con FV = portfolio × (1+r)^n + savings × annuity
```

Los milestones 25/50/75/100% representan cuánto capital se necesita para cubrir ese porcentaje de gastos con renta pasiva. La fecha proyectada asume aportes mensuales constantes y rendimiento constante.

---

## Desglose por fuente (by_source)

`split_portfolio_buckets` también desglosa por fuente (IOL, COCOS, BINANCE, MANUAL):
```json
{
  "IOL":    {"total_usd": 5000, "capital_usd": 2000, "renta_usd": 3000, "crypto_usd": 0},
  "COCOS":  {"total_usd": 2000, "capital_usd": 0, "renta_usd": 2000, "crypto_usd": 0},
  "BINANCE":{"total_usd": 20, "capital_usd": 20, "renta_usd": 0, "crypto_usd": 20}
}
```

---

## Decisiones de diseño

**Por qué CRYPTO no contribuye a renta:** la apreciación del precio es especulativa y no predecible mensualmente. Incluirla en `monthly_return` daría una barra inflada que no refleja flujo de caja real.

**Por qué BOND/ON split 50/50:** los bonos tienen dos componentes: cupón (renta predecible) y precio (capital). Sin modelar cada bono individualmente, el 50/50 es una aproximación razonable para el objetivo de la app.

**Por qué REAL_ESTATE es RENTA:** la renta mensual del alquiler es flujo de caja real. La apreciación del inmueble (capital) se ignora en el cálculo mensual — la libertad financiera se construye con flujo, no con paper gains.

**Por qué CASH es CAPITAL:** el cash disponible representa liquidez, no renta. Si el usuario quiere que el cash "rinda", debería estar en un FCI o LETRA.
