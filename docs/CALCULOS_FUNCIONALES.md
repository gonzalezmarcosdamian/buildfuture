# Cómo BuildFuture calcula lo que ves en pantalla

> Documento funcional — explica, número a número, qué hay detrás de cada valor
> que aparece en el dashboard, el portafolio y las metas.
> Última actualización: 2026-04-06

---

## Fuentes de datos — de dónde vienen los números

| Fuente | Qué aporta | Frecuencia |
|--------|-----------|-----------|
| **IOL InvertirOnline** | Posiciones, precios, yields de LETRA/FCI/BOND/ON/CEDEAR | Auto-sync cada vez que abrís el dashboard |
| **Cocos Capital** | Posiciones FCI y CASH en pesos | Auto-sync manual (TOTP) |
| **PPI** | Posiciones de renta fija | Auto-sync periódico |
| **Cargas manuales** | CASH ARS/USD que cargás vos | Cuando vos lo actualizás |
| **dolarapi.com** | Tipo de cambio MEP (dólar bolsa) | En cada request, cache 5 min |
| **Open BYMA Data** | TNA real de LECAPs vigentes | En cada request, cache 5 min |
| **ArgentinaDatos** | Yield de FCIs (TNA real de mercado) | Durante el sync |

---

## 1. Portafolio Total

**Lo que ves:** el número grande arriba del dashboard y de la pantalla Portafolio.

```
Portafolio Total (USD) = Σ current_value_usd de todas tus posiciones activas
```

`current_value_usd` de cada posición se setea en el sync:
- **LETRA / BOND / ON**: `cantidad × precio_actual` (precio IOL en ARS / MEP)
- **CEDEAR / ETF**: `cantidad × precio_IOL_ars / MEP`
- **FCI**: `cuotapartes × valor_cuotaparte` (IOL o Cocos)
- **CASH_ARS manual**: `monto_ars / MEP` (usando el MEP del momento de carga)
- **CASH_USD manual**: `monto_usd` directo (1:1)

**En ARS:** si tenés el toggle en `$`:
```
Total ARS = Σ current_value_ars (si existe) ó current_value_usd × MEP (fallback)
```

> `current_value_ars` se guarda explícitamente para CASH manual (el ARS exacto que cargaste).
> Para las demás posiciones se convierte con el MEP del momento de la consulta.

---

## 2. Barra de Renta (verde 💰)

**Lo que ves:** "X USD/mes · Y% de tus gastos cubiertos"

### 2a. Renta mensual USD

Solo cuentan los instrumentos de **renta real** — no todo el portafolio:

| Tipo | Contribuye a renta | Cómo |
|------|--------------------|------|
| LETRA (LECAP, LETE) | ✅ Sí | `valor_usd × annual_yield_pct / 12` |
| FCI | ✅ Sí | `valor_usd × annual_yield_pct / 12` |
| BOND / ON | ✅ Parcial (50%) | `valor_usd × annual_yield_pct / 12 × 0.5` |
| CEDEAR / ETF | ❌ No | Apreciación de capital, no renta predecible |
| CRYPTO | ❌ No | Especulativo, sin yield fijo |
| CASH | ❌ No | Líquido sin rendimiento asignado |

```
renta_mensual_usd = Σ (valor_usd_i × yield_i / 12)   [solo instrumentos de renta]
```

**Por qué todo en USD si la LECAP es en pesos:**
El sistema necesita una unidad de cuenta común para sumar LECAP + CEDEAR + CASH en un solo número.
El valor de la LECAP se convierte a USD dividiendo por MEP en el momento del sync (`valorizado_ars / MEP`).
La renta se calcula sobre ese valor en USD multiplicado por la TNA en ARS (68%), lo que da un número en USD aproximado.
Es una simplificación — si el MEP sube, tu LECAP "vale menos en USD" aunque en ARS valga igual.
La alternativa más correcta sería `(valor_ars × tna / 12) / MEP`, pero da el mismo resultado si el MEP es estable.

**El 50% de BOND/ON — por qué:**
Un bono (AL30, GD30) o una ON tienen dos fuentes de retorno:
- **Cupón periódico** → es renta (flujo predecible, como una LECAP)
- **Apreciación del precio** → puede subir o bajar → es capital (no predecible)

BuildFuture no puede saber en tiempo real cuánto viene del cupón y cuánto de la suba de precio,
entonces usa una convención: divide el bono en dos mitades iguales.
Ejemplo: $1.000 en AL30 con yield 9% → renta mensual = `$500 × 9% / 12 = $3.75/mes` + $500 cuenta como capital.

**De dónde sale `annual_yield_pct`:**
- **LECAP**: TIR calculada desde precio actual vs. VN al vencimiento (yield real de IOL, no estimado)
- **FCI**: TNA real de ArgentinaDatos para el fondo específico (IOLCAMA, IOLMMA, etc.)
- **BOND soberano**: YTM calibrada por tipo (~9-11%) — próximamente desde BYMA Open Data
- **ON**: yield calibrado por ticker (~9%) — próximamente desde BYMA Open Data

### 2b. Porcentaje de la barra

```
rentaPct = (renta_mensual_usd / gastos_mensuales_usd) × 100
```

`gastos_mensuales_usd` viene de tu presupuesto configurado en **Metas → Presupuesto**.
Si no configuraste presupuesto, el sistema usa $2.000 USD como fallback.

### 2c. Categorías cubiertas

Tu presupuesto tiene categorías (alquiler, comida, transporte, etc.). El sistema las ordena
de menor a mayor en USD y va "pagándolas" con la renta en orden:

```
remaining = renta_mensual_usd
para cada categoría (de más barata a más cara):
  si remaining >= cat.amount_usd  → "cubierta" (verde)
  si remaining > 0                → "parcial"  (amarillo)
  si remaining = 0                → "pendiente" (gris)
  remaining -= cat.amount_usd
```

> Estrategia: cubrir primero las categorías pequeñas garantiza que siempre haya "algo cubierto"
> aunque la renta total sea baja.

---

## 3. Barra de Capital (violeta 📈)

**Lo que ves:** "X USD acumulados · Y% de tus metas"

### 3a. Capital acumulado (numerador)

Solo cuentan los instrumentos de **crecimiento de capital**:

```
capital_usd = CEDEARs + ETFs + CRYPTO + CASH + 50% de BOND/ON
```

| Tipo | Cuenta como capital |
|------|---------------------|
| CEDEAR | ✅ 100% |
| ETF | ✅ 100% |
| CRYPTO | ✅ 100% |
| CASH (ARS o USD manual) | ✅ 100% |
| BOND / ON | ✅ 50% (el otro 50% va a renta) |
| LETRA / FCI | ❌ No (son renta, no capital de largo plazo) |

### 3b. Porcentaje de la barra

```
capitalPct = capital_usd / suma_objetivos_metas × 100
```

`suma_objetivos_metas` = suma de `target_usd` de todas tus metas de capital en **Metas → Capital**.
Si no tenés metas configuradas, la barra muestra 0% con el mensaje "Sin metas".

---

## 4. Freedom Score (% de libertad financiera)

**Lo que ves:** en `/goals` la proyección de cuándo llegás al 100%.

```
freedom_pct = renta_mensual_usd / gastos_mensuales_usd
```

- **0%**: no tenés renta o no tenés presupuesto
- **100%**: tu renta mensual cubre todos tus gastos → libertad financiera por renta

También se calcula:
```
annual_return_pct = (renta_mensual_usd × 12) / renta_total_usd
```
Este es el rendimiento anual efectivo de tu bucket de renta (no de todo el portafolio).

---

## 5. Proyección DCA (ProjectionCard)

**Lo que ves:** "Llegás al 25% de libertad en X meses"

Los 4 milestones son 25%, 50%, 75%, 100% de libertad financiera (renta = gastos).

Para cada milestone:
```
capital_requerido = (gastos_mensuales_usd × milestone_pct × 12) / annual_return_pct
```

Luego busca binariamente cuántos meses de ahorro + interés compuesto se necesitan:
```
para N meses:
  capital_proyectado = capital_actual × (1 + tasa_mensual)^N
                     + ahorro_mensual × [(1+tasa_mensual)^N - 1] / tasa_mensual
```

`tasa_mensual = annual_return_pct / 12`
`ahorro_mensual` viene de `savings_monthly_usd` de tu presupuesto.

> Si `annual_return_pct = 0` (no tenés instrumentos de renta), la proyección retorna `null` — no puede proyectar sin tasa.

---

## 6. Racha (🔥 meses invirtiendo)

**Lo que ves:** "3 meses invirtiendo" con la llama naranja.

Fuente primaria: tabla `investment_months` con las operaciones reales registradas en IOL.
Fallback: meses donde tenés al menos una posición con `snapshot_date`.

```
calendario = últimos 12 meses
para cada mes desde el más reciente hacia atrás:
  si el mes está en investment_months → suma 1 al streak
  si no → frena
```

---

## 7. MEP — Tipo de cambio

Siempre se usa el **dólar bolsa (MEP)** para convertir entre ARS y USD.

Orden de prioridad:
1. `fx_rate` de tu presupuesto (si lo tenés guardado)
2. dolarapi.com en tiempo real (cache 5 min)
3. Fallback: $1.430 ARS/USD

---

## 8. TNA de LECAPs (benchmark)

Desde 2026-04-06 la TNA de referencia de LECAPs viene de **Open BYMA Data**:

```
TNA_lecap = promedio ponderado por volumen de LECAPs vigentes en BYMA
           (filtra vencidas, filtra yield=0)
```

Fallback si BYMA falla: 55% TNA.

Esta tasa se usa en:
- Expert Committee (comparar si tu carry supera o no la LECAP)
- ProjectionCard (benchmark "vs. tasa libre de riesgo")

---

## 9. Performance de cada posición

**Lo que ves:** "+12.5%" en verde o "-3.2%" en rojo por posición.

```
performance_pct     = (precio_actual / precio_promedio_compra - 1) × 100   [en USD]
performance_ars_pct = (precio_actual × MEP_actual / (precio_promedio_compra × MEP_compra) - 1) × 100
```

`ppc` (precio promedio de compra) viene del broker en el sync.
`purchase_fx_rate` es el MEP al momento de la compra (guardado en la posición).

---

## 10. Auto-sync IOL

Cada vez que abrís el dashboard, el endpoint `/portfolio/gamification` dispara un
auto-sync de IOL **en background** (no bloquea la respuesta). Usa un lock por usuario
para evitar dos syncs simultáneos.

El sync:
1. Lee posiciones actuales de IOL API
2. Upserta en la tabla `positions` (crea nuevas, actualiza precios, marca inactivas las que no aparecen)
3. Actualiza `annual_yield_pct` con los yields reales de IOL/ArgentinaDatos/BYMA
4. Invalida el cache del freedom score para que el próximo request tenga datos frescos
5. Guarda un `PositionSnapshot` por posición para el historial

---

## Glosario rápido

| Término | Significado |
|---------|-------------|
| **Renta** | Flujo periódico: intereses de LECAP, dividendos FCI, cupones de BOND/ON |
| **Capital** | Valor acumulado para largo plazo: CEDEARs, ETFs, CRYPTO, CASH |
| **MEP** | Tipo de cambio dólar bolsa (dólar MEP / dólar bolsa) |
| **TNA** | Tasa Nominal Anual en ARS |
| **TIR / YTM** | Tasa Interna de Retorno en USD — rendimiento real de un bono a vencimiento |
| **Freedom pct** | % de gastos mensuales cubiertos por tu renta |
| **PPC** | Precio promedio de compra |
| **Snapshot** | Foto del valor de una posición en una fecha — base del historial |
