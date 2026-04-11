# Yields v2 — Arquitectura de soberanía de datos

> Estado: **DISEÑO — pendiente implementación Sprint 10**
> Fecha: 2026-04-11
> Autor del análisis: revisión completa de byma_client.py + yield_updater.py

---

## El hallazgo que cambia todo

Mirando el código real de `byma_client.py`:

```python
# línea 582 — get_bond_tir()
# impliedYield viene null en el nuevo endpoint → retorna None hasta que BYMA
# exponga el campo. El caller usa la tabla _BOND_YTM como fallback.

# línea 626 — _get_price_from_panel()
tir = item.get("impliedYield")
# impliedYield actualmente null en BYMA — guardamos el precio de referencia
```

**BYMA nunca nos da yields. `impliedYield` siempre es NULL.**

Lo que BYMA sí nos da, en cada panel (`btnLetras`, `btnTitPublicos`, `btnObligNegociables`, `btnCedears`, `btnLideres`):

| Campo | Tipo | Cambia |
|-------|------|--------|
| `vwap` | Precio promedio ponderado del día | Cada día |
| `tradeVolume` | Volumen operado | Cada día |
| `previousClosingPrice` | Cierre del día anterior | Cada día |
| `tradingHighPrice` / `tradingLowPrice` | Máx/mín intraday | Cada día |
| `impliedYield` | Yield implícito | **SIEMPRE NULL** |

Y en `fichatecnica/especies/general`:

| Campo | Tipo | Cambia |
|-------|------|--------|
| `fechaEmision` | Fecha de emisión | **Nunca** |
| `fechaVencimiento` | Fecha de vencimiento | **Nunca** |
| `interes` (TEM) | Tasa efectiva mensual contractual | **Nunca** |

**Conclusión:** BYMA nos da dos cosas — precios dinámicos diarios y metadata estática por instrumento. Los yields los calculamos nosotros siempre, desde precio + metadata.

El sistema actual ya hace esto correctamente para LECAPs. El problema es que **no guarda nada** — cada vez que necesita el yield, vuelve a llamar a BYMA, hace el cálculo, lo usa y lo descarta. Si BYMA no responde → fallback a tabla estática.

La solución es simple: **guardar lo que ya buscamos**.

---

## Dos tablas. Punto.

### Tabla 1: `instrument_metadata` — datos que nunca cambian

```sql
CREATE TABLE instrument_metadata (
    ticker          VARCHAR(20) PRIMARY KEY,
    asset_type      VARCHAR(20) NOT NULL,
    -- LECAP / BOND / ON
    emision_date    DATE,
    maturity_date   DATE,
    tem             DECIMAL(8,6),        -- tasa efectiva mensual contractual
    currency        CHAR(3) DEFAULT 'ARS', -- 'ARS' o 'USD'
    -- FCI
    fondo_name      VARCHAR(100),
    fci_categoria   VARCHAR(50),
    -- General
    description     VARCHAR(200),
    fetched_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
```

**Se llena una sola vez** por instrumento al primer sync o al primer fetch de fichatecnica. Nunca se borra. Si el instrumento vence, queda como referencia histórica.

Para LECAPs: `tem` + `emision_date` + `maturity_date` son suficientes para computar TEA desde cualquier precio futuro, sin volver a llamar a BYMA.

---

### Tabla 2: `instrument_prices` — precios diarios de cierre

```sql
CREATE TABLE instrument_prices (
    id          SERIAL PRIMARY KEY,
    ticker      VARCHAR(20)    NOT NULL,
    price_date  DATE           NOT NULL,
    vwap        DECIMAL(14,4),       -- precio promedio ponderado (ARS para la mayoría)
    prev_close  DECIMAL(14,4),       -- cierre del día anterior (BYMA previousClosingPrice)
    volume      DECIMAL(18,2),       -- volumen operado (para ponderar promedios de mercado)
    mep         DECIMAL(10,2),       -- MEP del mismo día (para convertir a USD)
    source      VARCHAR(20)  NOT NULL DEFAULT 'BYMA',
    UNIQUE (ticker, price_date)
);

CREATE INDEX idx_ip_ticker_date ON instrument_prices (ticker, price_date DESC);
```

**Se llena cada día hábil a las 18:00**, post-cierre de mercado, con los precios de todos los paneles de BYMA. Una sola pasada de ~5 llamadas HTTP cubre todos los instrumentos del mercado argentino.

**También aplica para FCI:** el VCP (valor cuota parte) de cada fondo se guarda en esta misma tabla. `ticker = fondo_name`. `vwap = vcp`. Estructura uniforme.

---

### Extensión de `position_snapshots` — agregar valor en ARS

```sql
ALTER TABLE position_snapshots
    ADD COLUMN value_ars  DECIMAL(14,2) DEFAULT NULL,
    ADD COLUMN mep        DECIMAL(10,2) DEFAULT NULL;
```

Con `value_ars` + `mep` almacenados por snapshot, podemos reconstruir el retorno real en USD de cualquier posición ARS en cualquier período, capturando automáticamente el efecto devaluación.

---

## Cómo se computa el yield por tipo — sin APIs en runtime

### LECAP (S-prefix)

**Datos necesarios:** `instrument_metadata.tem` + `maturity_date` + `instrument_prices.vwap` del día.

```python
def compute_lecap_tea(ticker: str, price_date: date, db) -> Decimal | None:
    meta = db.get(InstrumentMetadata, ticker)
    price = db.query(InstrumentPrice).filter_by(ticker=ticker, price_date=price_date).first()

    if not meta or not price or not price.vwap:
        return None  # → fallback a BYMA en tiempo real

    days = (meta.maturity_date - price_date).days
    if days <= 0:
        return Decimal("0")

    # meses totales desde emisión a vencimiento (invariante del instrumento)
    total_months = ((meta.maturity_date - meta.emision_date).days) / 30.4375
    vnv = Decimal("100") * (1 + meta.tem) ** total_months

    tea = (vnv / price.vwap) ** (Decimal("365") / days) - 1
    return tea if -0.1 <= float(tea) <= 5.0 else None
```

**Sin BYMA en runtime.** Cero dependencias externas. La fórmula es idéntica a la actual — solo cambia de dónde viene el precio (DB propia vs llamada HTTP).

---

### BOND soberano / ON corporativa

**Datos necesarios:** `instrument_prices.vwap` de los últimos N días.

```python
def compute_bond_yield(ticker: str, db, days: int = 30) -> Decimal | None:
    prices = (
        db.query(InstrumentPrice)
        .filter_by(ticker=ticker)
        .order_by(InstrumentPrice.price_date.desc())
        .limit(days + 5)
        .all()
    )
    if len(prices) < 7:
        return None  # → fallback a _BOND_YTM tabla

    newest, oldest = prices[0], prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days
    if elapsed < 3 or oldest.vwap <= 0:
        return None

    # Para bonos dolarizados: vwap está en ARS → convertir a USD con MEP del día
    if newest.mep and oldest.mep and newest.mep > 0 and oldest.mep > 0:
        usd_new = float(newest.vwap) / float(newest.mep)
        usd_old = float(oldest.vwap) / float(oldest.mep)
    else:
        usd_new = float(newest.vwap)
        usd_old = float(oldest.vwap)

    raw = (usd_new / usd_old - 1) * (365 / elapsed)

    # Bonos soberanos: rango razonable -30% a +50% anual
    return Decimal(str(round(raw, 4))) if -0.3 <= raw <= 0.5 else None
```

**Elimina `_BOND_YTM` definitivamente.** Con 7 días de precios, el mercado mide mejor que cualquier tabla calibrada a mano.

**Nota:** para bonos con cupones frecuentes, el retorno observado de precio subestima el retorno total (no captura el cupón cobrado entre snapshots). Esto es una limitación conocida — aceptable para el uso actual (mostrar yield orientativo). Para YTM exacta se necesitaría el schedule de flujos, que no provee BYMA.

---

### FCI

**Datos necesarios:** `instrument_prices.vwap` (VCP diario) de los últimos 30 días.

```python
def compute_fci_yield(fondo_name: str, db, days: int = 30) -> Decimal | None:
    prices = (
        db.query(InstrumentPrice)
        .filter_by(ticker=fondo_name)
        .order_by(InstrumentPrice.price_date.desc())
        .limit(days + 5)
        .all()
    )
    if len(prices) < 2:
        return None  # → fallback a ArgentinaDatos en tiempo real

    newest, oldest = prices[0], prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days
    if elapsed < 3 or float(oldest.vwap) <= 0:
        return None

    tna = (float(newest.vwap) / float(oldest.vwap) - 1) * (365 / elapsed)
    return Decimal(str(round(tna, 4))) if 0 < tna < 5.0 else None
```

**Elimina la dependencia en tiempo real de ArgentinaDatos.** Solo se llama ArgentinaDatos en el job nocturno para llenar `instrument_prices`. En runtime: cero llamadas externas.

---

### Position — retorno real observado (máxima precisión)

**Datos necesarios:** `position_snapshots.value_ars` + `position_snapshots.mep` históricos.

```python
def compute_position_actual_return(
    db, user_id: str, ticker: str, asset_type: str, days: int = 30
) -> Decimal | None:
    snaps = (
        db.query(PositionSnapshot)
        .filter_by(user_id=user_id, ticker=ticker)
        .order_by(PositionSnapshot.snapshot_date.asc())
        .all()
    )
    if len(snaps) < 2:
        return None

    newest = snaps[-1]
    cutoff = newest.snapshot_date - timedelta(days=days)
    window = [s for s in snaps if s.snapshot_date >= cutoff]
    if len(window) < 2:
        return None

    oldest = window[0]
    elapsed = (newest.snapshot_date - oldest.snapshot_date).days
    if elapsed < 3:
        return None

    # ARS: usar value_ars/mep para capturar efecto devaluación correctamente
    if (asset_type in ("LETRA", "FCI")
            and oldest.value_ars and newest.value_ars
            and oldest.mep and newest.mep
            and float(oldest.mep) > 0):
        usd_old = float(oldest.value_ars) / float(oldest.mep)
        usd_new = float(newest.value_ars) / float(newest.mep)
    else:
        usd_old = float(oldest.value_usd)
        usd_new = float(newest.value_usd)

    if usd_old <= 0:
        return None

    raw = (usd_new / usd_old - 1) * (365 / elapsed)
    return Decimal(str(round(raw, 4))) if -0.5 <= raw <= 2.0 else None
```

Este es el número más preciso posible. Captura todo: apreciación del precio, efecto devaluación, reinversión de cupones (si el broker los reinvierte en la posición), dividendos, todo. Sin ninguna API externa.

---

## Cadena de fallback definitiva

```
Para cada posición, en orden estricto de prioridad:

① compute_position_actual_return()          — retorno real observado
  requiere: position_snapshots con value_ars/mep, >= 7 días

② compute_<tipo>_yield() desde instrument_prices  — precio almacenado propio
  requiere: >= 1 día de precios en instrument_prices

③ BYMA / ArgentinaDatos en tiempo real      — solo bootstrap
  se activa: usuario nuevo, instrumento nuevo (< 1 día en DB)

④ Último annual_yield_pct conocido en Position  — "ayer era X, hoy lo mismo"
  se activa: ③ también falla

⑤ Promedio del tipo (calculado desde todas las Position activas del mismo asset_type)
  se activa: posición nueva sin historial, APIs caídas
  → nunca un número hardcodeado
```

Con el Price Collector corriendo 7 días seguidos, el nivel ③ nunca se activa para instrumentos conocidos. Con 30 días, el nivel ① domina para todos los usuarios activos.

---

## El Price Collector — job nocturno

Se suma al scheduler existente, corre a las 18:30 (post-cierre BYMA):

```python
async def _collect_daily_prices(db: Session) -> None:
    """
    5 llamadas HTTP. Cubre todo el mercado argentino de renta fija y variable.
    Si BYMA falla → loguea y sigue. Los datos del día anterior persisten como proxy.
    """
    today = date.today()
    mep = _get_mep_del_dia(db)  # ya disponible en BudgetConfig o PortfolioSnapshot

    # 1. LECAPs + CER (btnLetras) — precio vwap + fichatecnica una vez por ticker
    for item in byma_client.fetch_panel("btnLetras"):
        ticker = item["symbol"]
        # Metadata: solo si no está ya en DB
        if not db.get(InstrumentMetadata, ticker):
            ficha = byma_client.get_ficha_tecnica(ticker)
            if ficha:
                db.merge(InstrumentMetadata(ticker=ticker, asset_type="LETRA", ...))
        # Precio diario: siempre
        db.merge(InstrumentPrice(ticker=ticker, price_date=today, vwap=item["vwap"],
                                  prev_close=item["previousClosingPrice"],
                                  volume=item["tradeVolume"], mep=mep, source="BYMA"))

    # 2. Bonos soberanos (btnTitPublicos)
    for item in byma_client.fetch_panel("btnTitPublicos"):
        db.merge(InstrumentPrice(ticker=item["symbol"], price_date=today,
                                  vwap=item["vwap"], mep=mep, source="BYMA"))

    # 3. ONs corporativas (btnObligNegociables)
    for item in byma_client.fetch_panel("btnObligNegociables"):
        db.merge(InstrumentPrice(ticker=item["symbol"], price_date=today,
                                  vwap=item["vwap"], mep=mep, source="BYMA"))

    # 4. CEDEARs (btnCedears) — ya los tenemos de IOL, pero guardamos el BYMA también
    for item in byma_client.fetch_panel("btnCedears"):
        db.merge(InstrumentPrice(ticker=item["symbol"], price_date=today,
                                  vwap=item["vwap"], mep=mep, source="BYMA"))

    # 5. FCIs — VCP diario de ArgentinaDatos (todas las categorías)
    for categoria in ["mercadoDinero", "rentaMixta", "rentaVariable", "rentaFija"]:
        for fondo in argentinadatos.fetch_fci_categoria(categoria):
            db.merge(InstrumentPrice(ticker=fondo["fondo"], price_date=today,
                                      vwap=fondo["vcp"], source="ArgentinaDatos"))

    db.commit()
```

**Costo:** ~5 HTTP requests/día. Sin loops N+1. Sin fichatecnica repetida (la metadata se guarda una sola vez por ticker y nunca se vuelve a pedir).

---

## Por qué fichatecnica es la clave

La insight central que BYMA nos da gratis y no estamos aprovechando:

La TEM, `fechaEmision` y `fechaVencimiento` de una LECAP **son datos contractuales. No cambian jamás**. Una LECAP S31G6 siempre tiene:
- TEM = 2.60%
- Emisión = 2025-02-28
- Vencimiento = 2026-08-31

Hoy llamamos a `fichatecnica` cada vez que necesitamos calcular la TEA de una LECAP — incluso si ya la calculamos 5 minutos atrás. Con `instrument_metadata`, la primera vez que vemos S31G6 guardamos los tres campos. Nunca más llamamos a `fichatecnica` para ese ticker.

Cuando S31G6 venza, el registro queda en la tabla como referencia histórica. Si el usuario tuvo S31G6 y quiero reconstruir su yield del 15 de marzo, tengo precio del 15/3 en `instrument_prices` y metadata en `instrument_metadata`. TEA calculable sin ninguna API.

---

## Impacto en cada dependencia frágil

| Dependencia actual | Situación post-v2 |
|-------------------|-------------------|
| BYMA `fichatecnica` por ticker | **Llamada única por instrumento.** Metadata guardada para siempre. |
| BYMA `btnLetras` en tiempo real | Solo en Price Collector nocturno. Runtime: cero llamadas. |
| BYMA `btnTitPublicos` en tiempo real | Ídem. |
| BYMA `btnObligNegociables` | Ídem. |
| `impliedYield` = null | No importa. Nunca lo usamos. Calculamos desde precio + metadata. |
| `_BOND_YTM` tabla hardcodeada | **Eliminada.** Reemplazada por retorno observado de precio. |
| `LECAP_TNA_FALLBACK = 32%` | **Eliminado.** Reemplazado por último precio conocido en DB. |
| `CAUCION 30%` hardcodeado | **Eliminado.** Caucion tiene fecha y tasa al momento de apertura → guardar en instrument_metadata al sync IOL. |
| ArgentinaDatos FCI yields en runtime | Solo en Price Collector nocturno. Runtime: cero llamadas. |
| Problema ARS yield × USD value | **Resuelto.** `annual_yield_pct` pasa a ser retorno USD real cuando viene de PositionSnapshot (value_ars/mep). |

---

## El fix del problema conceptual: denominación del yield

El campo `annual_yield_pct` en `Position` no dice si es ARS o USD. Agregar un campo:

```sql
ALTER TABLE positions
    ADD COLUMN yield_currency CHAR(3) DEFAULT 'ARS';
    -- 'ARS' = tasa nominal ARS (sistema actual)
    -- 'USD' = retorno real en USD (sistema v2 cuando viene de PositionSnapshot)
```

En `split_portfolio_buckets()`:

```python
if pos.yield_currency == 'USD':
    # Retorno ya en USD — aplicar directo
    renta_monthly += pos.current_value_usd * pos.annual_yield_pct / 12
else:
    # ARS nominal — convertir: (1 + yield_ars) / (1 + devaluacion_anual) - 1
    # Si no tenemos devaluacion esperada: mostrar separado, no mezclar con USD
    renta_monthly_ars += pos.current_value_usd * pos.annual_yield_pct / 12
```

En el frontend, separar en la UI: "Renta ARS" y "Renta USD". No mezclar. El freedom score usa solo renta USD hasta que el usuario defina si sus gastos son en ARS o USD.

---

## Estado actual vs estado futuro

| | Hoy (v0.11.0) | v2 |
|--|--------------|-----|
| TEA LECAP | BYMA en runtime → cálculo → descartado | DB propia → cálculo → sin APIs |
| YTM BOND | Tabla `_BOND_YTM` hardcodeada abril 2026 | Retorno observado desde precios históricos |
| Yield FCI | ArgentinaDatos en runtime → descartado | VCP histórico en DB → cálculo offline |
| Yield CAUCION | 30% hardcodeado | Tasa contractual guardada en instrument_metadata |
| Freedom score | ARS nominal × USD value | Retorno real USD desde PositionSnapshot |
| Disponibilidad | Degradada si BYMA/ArgentinaDatos caen | 100% self-sufficient después de día 1 |

---

## Plan de implementación — Sprint 10

### 10A — Tablas + metadata (día 1)
1. Migración Alembic: crear `instrument_metadata`, `instrument_prices`
2. `models.py`: agregar ambos modelos
3. `ALTER TABLE position_snapshots`: agregar `value_ars`, `mep`
4. `ALTER TABLE positions`: agregar `yield_currency`
5. Backfill `instrument_metadata`: al startup, por cada Position activa de tipo LETRA/BOND/ON → llamar fichatecnica una sola vez y guardar

### 10B — Price Collector (día 1-2)
6. `services/price_collector.py`: el job de 5 llamadas HTTP
7. `scheduler.py`: agregar `_collect_daily_prices` a las 18:30
8. Poblar `value_ars` + `mep` en `save_position_snapshots()` (usa `Position.current_value_ars` + MEP del portfolio snapshot del mismo día)
9. Tests: mock BYMA → precios guardados; BYMA caído → datos del día anterior persisten; idempotente si corre dos veces el mismo día

### 10C — Yield Calculator v2 (día 2-3)
10. `services/yield_calculator_v2.py`: las 4 funciones compute_*
11. `yield_updater.py`: integrar cadena de fallback — v2 primero, sistema actual como bootstrap
12. Agregar `yield_currency` al update cuando viene de PositionSnapshot ('USD') vs sistema actual ('ARS')
13. Tests TDD: LECAP con 7d precios → TEA correcta; BOND con 30d → YTM razonable; FCI → TNA desde VCP; sin historial → fallback a BYMA

### 10D — Fix freedom score (día 3)
14. `split_portfolio_buckets()`: separar renta ARS de renta USD
15. `calculate_freedom_score()`: freedom_pct calculado solo sobre renta USD
16. Frontend: label correcto ("X% TNA ARS" vs "X% anual USD") según `yield_currency`
17. Tests: freedom score con LECAP yield_currency='ARS' no suma a freedom_pct en USD

---

## Invariantes

1. `instrument_metadata` es inmutable después de insertar. Si cambia algo (imposible para letras, teóricamente posible para ONs) → nueva fila con `fetched_at` más reciente.
2. `instrument_prices` es append-only por día. Nunca borrar histórico de precios.
3. `value_ars` en `PositionSnapshot` se guarda siempre que `Position.current_value_ars > 0`. Para CRYPTO/CEDEAR/BOND USD → `value_ars = NULL`, solo `mep` se guarda.
4. El Price Collector no falla silenciosamente. Loguea qué instrumentos no pudo actualizar. Si falla > 80% de instrumentos → alerta (indica que BYMA cambió su API de nuevo).
5. La tabla `_BOND_YTM` se mantiene en el código como último recurso hasta que el Price Collector tenga 30 días de historia para todos los bonos en cartera de usuarios activos.
