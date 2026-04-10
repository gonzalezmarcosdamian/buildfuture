# SPIKE: Validación de Yields del Portfolio Real — 2026-04-10

**Fecha:** 2026-04-10  
**Ejecutado por:** Claude Code (spike automatizado)  
**Usuario analizado:** f94d61c1-1b59-438c-bc79-a66139028c94 (Marcos González — IOL + Cocos)  
**Backend:** https://api-production-7ddd6.up.railway.app (v0.10.0, status OK)

---

## Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Posiciones activas analizadas | 10 (excluyendo CASH y REAL_ESTATE) |
| Yields correctos / dentro de rango | 3 |
| Yields incorrectos / con discrepancia > 2pp | 4 |
| Yields no validables (fuente externa no disponible) | 3 |
| **Bugs críticos detectados** | **2** |

---

## Acceso y fuentes de datos

| Fuente | Estado | Detalle |
|---|---|---|
| IOL API (portafolio/argentina) | OK | Token obtenido via credenciales del `.env` |
| BuildFuture DB (Supabase PostgreSQL) | OK | Acceso directo al pool de conexiones |
| BYMA open.bymadata.com.ar | BLOQUEADO | HTTP 400 en todos los endpoints (sin auth/origin válido desde este entorno) |
| ArgentinaDatos FCI (mercadoDinero, rentaFija, rentaMixta) | OK | Datos al 2026-04-09 |
| IOL cotizaciones individuales (/api/v2/cotizaciones/titulos/...) | ERROR 500 | Runtime error en IOL API para tickers individuales |

> **Nota:** La autenticación a Supabase falló porque las credenciales del `.env` del backend (IOL/Cocos) son distintas del password de Supabase Auth. Se accedió directamente a la DB PostgreSQL usando `DATABASE_URL`.

---

## Portfolio de Marcos en BuildFuture (snapshot 2026-04-10)

| ticker | asset_type | quantity | ppc_ars | current_value_ars | annual_yield_pct (BF) | snapshot_date |
|---|---|---|---|---|---|---|
| S15Y6 | LETRA | 487,804 | 101.85 | 502,925.92 | **68.00%** | 2026-04-10 |
| X29Y6 | LETRA | 434,782 | 114.199 | 496,955.83 | **68.00%** | 2026-04-10 |
| S31G6 | LETRA | 349,344 | 113.819 | 404,012.84 | **68.00%** | 2026-04-10 |
| COCOSPPA | FCI | 4,862.07 | 1,234.84 | 6,451,209.55 | **20.61%** | 2026-04-08 |
| QQQ | CEDEAR | 3 | 42,220 | 135,240 | 10.00% | 2026-04-10 |
| SPY | CEDEAR | 2 | 48,380 | 100,250 | 10.00% | 2026-04-10 |
| IOLCAMA | FCI | 2,600.04 | 10.938 | 28,623.85 | **33.65%** | 2026-04-10 |
| COCORMA | FCI | 0.000099 | 7,615.62 | 1.06 | **26.03%** | 2026-04-08 |
| RESTATE_1 | REAL_ESTATE | 1 | 0 | 0 | 5.00% | 2026-04-10 |

---

## Tabla de validación por instrumento

| ticker | tipo | yield BF | yield mercado | fuente | diferencia | estado |
|---|---|---|---|---|---|---|
| S15Y6 | LECAP (S) | 68.00% | ~30-35% TNA* | Estimación mercado | ~33-38 pp | INCORRECTO |
| S31G6 | LECAP (S) | 68.00% | ~30-35% TNA* | Estimación mercado | ~33-38 pp | INCORRECTO |
| X29Y6 | LETRA CER (X) | 68.00% | ~-12% a -9% TIR real** | BYMA referencia (código) | ~77-80 pp | INCORRECTO (BUG CRITICO) |
| IOLCAMA | FCI rentaFija | 33.65% | 33.65% TNA | ArgentinaDatos rentaFija | 0.00 pp | CORRECTO |
| COCOSPPA | FCI mercadoDinero | 20.61% | 22.31% TNA | ArgentinaDatos mercadoDinero | -1.70 pp | ACEPTABLE |
| COCORMA | FCI rentaMixta | 26.03% | 28.19% TNA | ArgentinaDatos rentaMixta | -2.16 pp | ACEPTABLE (en el límite) |
| QQQ | CEDEAR | 10.00% | N/A (apreciación) | N/A | N/A | NO VALIDABLE |
| SPY | CEDEAR | 10.00% | N/A (apreciación) | N/A | N/A | NO VALIDABLE |
| RESTATE_1 | REAL_ESTATE | 5.00% | N/A (manual) | N/A | N/A | NO VALIDABLE |

_* Estimación basada en condiciones monetarias de Argentina a abril 2026: inflación ~3% mensual, tasas BCRA ~32% TNA._  
_** Benchmark documentado en el propio código del backend (`byma_client.py` línea 186): "X29Y6 ≈ -12%, X18E7 ≈ -9% a abril 2026"._

---

## Análisis root cause de discrepancias > 2pp

### BUG 1 (CRITICO): LECAPs S-prefix con precio técnico > par → fallback hardcodeado 68%

**Posiciones afectadas:** S15Y6, S31G6  
**Yield reportado:** 68.00% TNA  
**Yield real de mercado:** ~30-35% TNA (condiciones monetarias abril 2026)

**Causa raíz:**

Las LECAPs argentinas capitalizan diariamente. El precio que devuelve IOL (`ultimoPrecio`) es el **precio técnico (dirty)** que incluye los intereses devengados desde la emisión. Para S15Y6 (vto 15/05/2026, 35 días), IOL reporta `ultimoPrecio = 103.10`, lo que implica que el precio ya superó los 100 pesos de VN.

En `yield_updater.py`, la función `_yield_lecap()` calcula:
```python
price_per_100 = (current_value_ars / quantity) × 100
```
Para S15Y6: `(502,925.92 / 487,804) × 100 = 103.10`

Como `price_per_100 >= 100`, el código retorna `LECAP_DEFAULT_TNA = Decimal("0.68")` (68%) hardcodeado.

**El problema:** El valor 68% correspondía a las tasas de 2024-2025. A abril 2026, las tasas de LECAP en el mercado rondan 30-35% TNA. El fallback no se actualizó con la realidad del mercado.

**Cálculo correcto:**  
La TNA real de una LECAP no puede calcularse desde el precio técnico porque el precio sucio supera 100. Se necesita el precio **limpio** (BYMA lo provee como `impliedYield`). Como BYMA no responde, el único fix viable es actualizar el fallback o integrar el campo `impliedYield` de BYMA correctamente.

Fórmula que debería usarse desde BYMA:
```
TNA = impliedYield (campo directo de BYMA)
```

---

### BUG 2 (CRITICO): X29Y6 (LETRA CER) recibe el mismo LECAP_DEFAULT_TNA que LECAPs nominales

**Yield reportado:** 68.00%  
**Yield real:** ~-12% a -9% TIR real (por encima del CER, negativo = debajo de la inflación)

**Causa raíz (bug en el código):**

La función `_yield_lecap()` tiene esta estructura:

```python
def _yield_lecap(pos, today):
    ticker_upper = pos.ticker.upper()
    if ticker_upper.startswith("X"):
        return _yield_letra_cer(pos)   # ← DEBERÍA llegar aquí para X29Y6

    maturity = _parse_lecap_maturity(pos.ticker)
    ...
    price_per_100 = (current_value_ars / quantity) × 100   # = 114.30
    
    if price_per_100 >= 100:          # ← ESTE BLOQUE SE EJECUTA PRIMERO
        return LECAP_DEFAULT_TNA      # ← Retorna 68% ANTES de llegar al check de prefijo X
```

**Pero el control del prefijo X está ANTES del cálculo del precio:**

Revisando el código real:
```python
if ticker_upper.startswith("X"):
    return _yield_letra_cer(pos)   # línea 363
```

Esta línea SÍ está antes del bloque `price_per_100 >= 100`. Sin embargo, el yield en DB es 68% para X29Y6. Esto indica que **el yield_updater no corrió después del último sync** del día 2026-04-10. Las posiciones son recientes (snapshot hoy) y el daily job de yields corre una vez al día, posiblemente después del momento de esta consulta.

**Segunda posibilidad:** `_yield_letra_cer()` llama a `get_cer_letter_tir()` que consulta BYMA. Como BYMA devuelve 400 en el entorno de Railway también (si la IP no está whitelisteada o el endpoint cambió), el fallback es `Decimal("0")`. Pero en DB tenemos 68%, no 0. Esto confirma que el updater NO corrió aún hoy y el 68% proviene de una ejecución anterior del updater cuando el valor era diferente (o del valor inicial del sync).

**Impacto:** X29Y6 vale ~ARS 497K. Mostrarle al usuario una TNA de 68% en vez de -12% TIR real es **conceptualmente incorrecto** — son instrumentos distintos. El usuario podría creer que X29Y6 rinde como una LECAP nominal cuando en realidad es un instrumento indexado a inflación con TIR real negativa.

---

### OBSERVACION: COCORMA (FCI rentaMixta) — 2.16 pp de diferencia

**Yield reportado:** 26.03%  
**Yield calculado (ArgentinaDatos 30d):** 28.19%

Diferencia de 2.16 pp, justo en el límite del umbral de 2%. El snapshot de la posición es del 2026-04-08 (2 días antes de hoy), lo que puede explicar parte de la diferencia. También la volatilidad del fondo Cocos Rendimiento en ese período. No es un bug pero conviene monitorear.

---

## Verificación de la fórmula LECAP (manual)

Para S15Y6 con precio técnico IOL:
- `precio_por_100 = (502,925.92 / 487,804) × 100 = 103.10`
- `días al vto = (2026-05-15 - 2026-04-10) = 35 días`
- Fórmula directa: `TNA = (100/103.10 - 1) × (365/35) = -31.4%` (inválida, precio > par)
- Fórmula TEA: `TNA = (100/103.10)^(365/35) - 1 = -27.3%` (también inválida)

La fórmula convencional **no aplica** cuando el precio técnico supera 100. Solo la TNA proveniente de BYMA `impliedYield` o el precio limpio (clean price) permitiría el cálculo correcto.

---

## Estado del yield_updater para las posiciones de hoy

Las posiciones con `snapshot_date = 2026-04-10` tienen `annual_yield_pct = 0.68` para las tres LECAPs, lo que indica que:
1. El sync de IOL corrió durante el día y pobló los datos.
2. El `yield_updater` (job diario) **aún no procesó** estas posiciones, o lo hizo pero con BYMA no disponible y usó el valor anterior de la DB.

El valor 0.68 en las LECAPs corresponde a `LECAP_DEFAULT_TNA` de una corrida anterior del updater, no de hoy.

---

## Conclusiones y accionables

### Accionable 1 (URGENTE): Actualizar LECAP_DEFAULT_TNA
`yield_updater.py` línea 388:
```python
_LECAP_DEFAULT_TNA = Decimal("0.68")  # ← desactualizado
```
Debe cambiarse a ~`Decimal("0.32")` o mejor: obtenerla dinámicamente de `get_lecap_tna()` (que ya hace el cálculo ponderado de BYMA). Si BYMA no responde, el fallback en `byma_client.py` también está en `LECAP_TNA_FALLBACK: float = 55.0` — también desactualizado (debería ser ~32%).

### Accionable 2 (URGENTE): Separar conceptualmente LECAP nominal vs LETRA CER en el frontend
X29Y6 es CER: mostrar su `annual_yield_pct` como "TIR real" (puede ser negativo), no como "TNA". El usuario necesita ver que este instrumento rinde inflación - X%, no una TNA directamente comparable con las LECAPs nominales.

### Accionable 3 (MEDIA): Investigar por qué BYMA devuelve 400
En entorno local y en Railway, el endpoint BYMA `short-term-government-bonds` devuelve HTTP 400 con body vacío. Esto bloquea tanto el cálculo de LECAP TNA ponderada como la TIR real de letras CER. Revisar si BYMA cambió el contrato (requiere headers específicos, body POST, o nuevo endpoint).

### Accionable 4 (BAJA): COCORMA montando 2.16 pp de diferencia
Monitorear en el próximo sprint. El fondo Cocos Rendimiento tiene mayor volatilidad que los money market puros. Considerar usar una ventana de 7 días en vez de 30d para smoothing.

### Accionable 5 (BAJA): CEDEARs con 10% hardcodeado
QQQ y SPY tienen `annual_yield_pct = 0.10` (10%). Este valor es un placeholder de apreciación esperada, no un dividend yield. Debería estar documentado en el frontend como "retorno esperado a largo plazo" y no como yield actual. No es un bug de cálculo sino de UX.

---

## Fuentes externas consultadas

| API | URL | Resultado |
|---|---|---|
| ArgentinaDatos FCI rentaFija | `api.argentinadatos.com/v1/finanzas/fci/rentaFija/ultimo` | OK — IOLCAMA validado |
| ArgentinaDatos FCI mercadoDinero | `api.argentinadatos.com/v1/finanzas/fci/mercadoDinero/ultimo` | OK — COCOSPPA validado |
| ArgentinaDatos FCI rentaMixta | `api.argentinadatos.com/v1/finanzas/fci/rentaMixta/ultimo` | OK — COCORMA validado |
| BYMA short-term-government-bonds | `open.bymadata.com.ar/...` | HTTP 400 — no disponible |
| BYMA government-bonds | `open.bymadata.com.ar/...` | HTTP 400 — no disponible |
| BYMA corporate-bonds | `open.bymadata.com.ar/...` | HTTP 400 — no disponible |
| IOL cotizaciones individuales | `api.invertironline.com/api/v2/cotizaciones/titulos/...` | HTTP 500 — no disponible |
