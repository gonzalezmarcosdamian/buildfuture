# Spike: Cálculo y presentación de rendimientos

**Fecha:** 2026-04-04
**Objetivo:** Comparar cómo calculan y presentan rendimientos otras apps de inversión.
Identificar qué debería cambiar en BuildFuture.

---

## 1. Benchmark — Cómo lo hacen otros

### IOL (InvertirOnline)

| Aspecto | Detalle |
|---|---|
| Métrica principal | `result_percentage` por posición |
| Fórmula | `(precio_actual − precio_promedio) / precio_promedio × 100` |
| Base | Precio promedio ponderado de compra (FIFO aproximado) |
| Scope | Por posición individual, no portafolio total |
| Frecuencia | Real-time (precio actual vs. cost basis) |
| Presentación | % de ganancia/pérdida coloreado por posición |
| Limitación | No incluye dividendos reinvertidos, no ajusta por inflación, no anualiza |

**Problema**: `result_percentage` mide ganancia de capital, no rendimiento total.
Un FCI de money market puede mostrar 0% de result_percentage si el precio no varía
(cuotapartes fijas) pero tiene TNA real. **BuildFuture ya lo evita** con `annual_yield_pct`
desde `DEFAULT_YIELDS`.

---

### Cocos Capital

| Aspecto | Detalle |
|---|---|
| Métrica principal | `result_percentage` + rendimiento anualizado por producto |
| Fórmula interna | No pública; aparentemente similar a IOL |
| Dato extra | Muestra TNA en FCI money market directamente en la tarjeta |
| Presentación | Rendimiento en pesos + rendimiento anualizado para FCI |
| Diferencia clave | Separa explícitamente gain de capital vs. rendimiento anualizado |

---

### PPI (Portfolio Personal Inversiones)

| Aspecto | Detalle |
|---|---|
| Métrica principal | TIR implícita para bonos, TNA para plazos fijos y FCI |
| Bonds | Muestra precio + TIR (Tasa Interna de Retorno) — no solo % de precio |
| FCI | TNA en pesos o USD según clase |
| Presentación | Más técnica que IOL/Cocos; segmentada por tipo de instrumento |
| Diferencia clave | Distingue metodología por tipo: TIR para deuda, precio para acciones |

---

### Fintual (Chile/Mexico)

| Aspecto | Detalle |
|---|---|
| Métrica principal | Rentabilidad histórica en 12 meses (%) y desde inicio |
| Fórmula | TWR (Time-Weighted Return) ajustado por aportes |
| Frecuencia | Diaria, acumulada, anualizada |
| Presentación | Gráfico de evolución de $1 invertido; comparativa vs. inflación local |
| Clave diferencial | Ajusta por aportes (TWR), no penaliza por timing; muestra inflación real |
| Limitación | Aplica a sus propios fondos, no portafolio heterogéneo |

---

### Portfolio Performance (open source)

| Aspecto | Detalle |
|---|---|
| Métrica principal | IRR (Internal Rate of Return) / TTWROR |
| Metodología | True Time-Weighted Rate of Return + Money-Weighted Return |
| Scope | Portafolio total, por segmento, por cuenta |
| Ajuste | Soporta dividendos, splits, costos de transacción, impuestos |
| Presentación | Dashboard con benchmark (S&P 500, DAX, etc.) |
| Clave diferencial | Distingue MWR vs TWR; benchmarks externos; granularidad máxima |

---

### Decrypto

| Aspecto | Detalle |
|---|---|
| Métrica principal | % rendimiento en USD desde compra |
| Scope | Crypto solamente |
| Fórmula | `(precio_actual − precio_compra) / precio_compra` |
| Presentación | Ganancia/pérdida no realizada por activo y total portafolio |
| Diferencia | Sin anualización, sin ajuste por tiempo |

---

## 2. Cuadro comparativo

| App | Metodología | Benchmarks | TWR/IRR | Tipo por instrumento | Inflación | Historial |
|---|---|---|---|---|---|---|
| IOL | % precio | ✗ | ✗ | ✗ | ✗ | ✗ |
| Cocos | % precio + TNA FCI | ✗ | ✗ | Parcial | ✗ | ✗ |
| PPI | TIR/TNA por tipo | ✗ | ✗ | ✓ | ✗ | ✗ |
| Fintual | TWR | ✓ (inflación) | TWR | ✓ | ✓ | ✓ |
| Portfolio Perf. | TWR + MWR | ✓ (externos) | ✓ | ✓ | ✓ | ✓ |
| Decrypto | % precio | ✗ | ✗ | ✗ | ✗ | ✗ |
| **BuildFuture (actual)** | `annual_yield_pct` por ticker | ✗ | ✗ | ✓ (parcial) | ✗ | Snapshots |

---

## 3. Situación actual de BuildFuture

### Lo que hacemos bien
- `annual_yield_pct` desde `DEFAULT_YIELDS` desacopla el rendimiento del precio de mercado
  → FCIs de money market no quedan en 0% como en IOL/Cocos
- TIR implícita para LECAPs y ONs (yield_updater)
- Snapshots diarios: base para calcular rendimiento histórico
- `PositionSnapshot` tiene campo `snapshot_date` → podríamos calcular variación entre snapshots

### Gaps actuales

| Gap | Impacto UX | Esfuerzo |
|---|---|---|
| No mostramos rendimiento total del portafolio (solo por posición) | Alto | Medio |
| No hay TWR ni IRR — el % que mostramos es "yield esperado", no ganancia real | Medio | Alto |
| No hay benchmark (no comparamos vs. inflación, plazo fijo, S&P) | Medio | Bajo |
| No hay gráfico de evolución del portafolio en ARS/USD a lo largo del tiempo | Alto | Medio |
| El rendimiento de CEDEARs/acciones no está ajustado por tipo de cambio MEP | Medio | Bajo |

---

## 4. Propuesta de mejoras — priorizada

### Tier 1 — Quick wins (no requieren cambio de modelo)

1. **Rendimiento total portafolio** — sumar `annual_yield_pct × weight` para cada posición
   y mostrar el promedio ponderado en el header de `/portfolio`.
   Fórmula: `Σ (valor_usd_i / total_usd) × annual_yield_pct_i`

2. **Benchmark básico: plazo fijo vs. MEP** — mostrar en la vista de proyección:
   "tu portafolio rinde X% anual vs. plazo fijo ~Y% en ARS".
   Dato disponible en `_fetch_market()` (`lecap_tna`).

3. **Evolución del portafolio** — gráfico simple de `total_value_usd` por snapshot.
   `PositionSnapshot` ya tiene los datos; falta agregarlos por día en el endpoint.

### Tier 2 — Medio plazo

4. **Ganancia realizada vs. no realizada** — necesita `cost_basis` por posición.
   Hoy no lo tenemos. Requiere que el usuario ingrese precio de compra (carga manual) o
   que lo obtengamos de IOL (`resultado_pesos`).

5. **Ajuste CEDEARs por MEP** — el rendimiento en USD de un CEDEAR depende del ratio
   CEDEAR/subyacente × tipo de cambio. Hoy asignamos un yield genérico.
   Mejora: usar `ratio` de IOL + precio subyacente vía API (ya disponible en IOL).

### Tier 3 — Largo plazo (requiere nuevo modelo de datos)

6. **TWR (Time-Weighted Return)** — requiere registrar precio de cada posición en cada
   movimiento (aporte/retiro). Implica cambiar el modelo de snapshots.

7. **IRR / MWR** — requiere historial de flujos de caja (cuándo entró cada peso).

---

## 5. Decisión recomendada

Implementar en este orden:
1. **Rendimiento ponderado del portafolio** (Tier 1.1) — una línea de cálculo, mucho impacto
2. **Gráfico evolución portafolio** (Tier 1.3) — visual de alto impacto, datos ya disponibles
3. **Benchmark vs. plazo fijo** (Tier 1.2) — contexto educativo sin trabajo de backend

Los tres juntos forman un PR de "rendimientos v2" que posiciona BuildFuture
claramente por encima de IOL/Cocos en calidad de información.

---

*Este documento es el output del spike. El siguiente paso es convertir Tier 1 en tareas en el backlog.*
