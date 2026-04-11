# Yields v2 — Soberanía de datos: la mejor solución posible

> Estado: **DISEÑO APROBADO — pendiente de implementación**
> Fecha: 2026-04-11
> Contexto: el sistema actual (v0.11.0) calcula yields dependiendo de BYMA, ArgentinaDatos y tablas estáticas hardcodeadas que se desactualizan. Esta arquitectura los elimina permanentemente.

---

## Por qué el sistema actual es insuficiente

### El problema conceptual (el más grave)

```python
# yield_updater.py — lo que hacemos hoy
monthly_return_usd = current_value_usd × annual_yield_pct / 12
#                    ↑ USD               ↑ TNA ARS nominal
```

Aplicar una tasa nominal ARS a un valor en USD no tiene unidades coherentes. El resultado no es renta en USD. Es un número sin interpretación financiera válida.

**Consecuencia:** el freedom score, la renta mensual estimada y las proyecciones de milestones están calculados sobre una base incorrecta. Es la métrica core del producto.

### Las dependencias frágiles

| Dependencia | Disponibilidad real | Riesgo |
|------------|---------------------|--------|
| BYMA `btnLetras` POST | ~85% — falla en feriados, fine de semana, mantenimientos | Todas las LECAPs caen al fallback |
| BYMA `fichatecnica` | ~80% — inestable, timeout frecuente | TEA calculada incorrectamente |
| ArgentinaDatos FCI yields | ~70% — 404 periódicos documentados | FCI cae a 38% hardcodeado |
| `_BOND_YTM` tabla estática | 100% pero INCORRECTA tras ±5% de precio | YTM desactualizada en semanas |
| `LECAP_TNA_FALLBACK = 32%` | 100% pero INCORRECTA si tasa se mueve | ±10pp error posible |
| `CAUCION = 30%` | 100% pero INCORRECTA si BCRA mueve tasas | Error permanente |

---

## La solución: Price Store propio + cálculo desde datos almacenados

### Principio arquitectural

> **No preguntar cuánto rinde un instrumento. Observarlo nosotros mismos, todos los días, y calcularlo desde nuestra propia historia.**

En lugar de llamar a BYMA en tiempo real para obtener una TEA, guardamos el **precio de cierre diario** de cada instrumento en nuestra DB. Con precios propios almacenados podemos calcular cualquier yield sin depender de disponibilidad externa.

Después de 30 días, el sistema es 100% autónomo.

---

## Arquitectura de tres capas

```
┌─────────────────────────────────────────────────────────────────┐
│  CAPA 1: Price Store                                             │
│  instrument_prices — precio de cierre diario por ticker          │
│  fci_vcp_history   — valor cuota parte diario por fondo FCI      │
│  mep_history       — tipo de cambio MEP diario                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ alimenta
┌────────────────────────────▼────────────────────────────────────┐
│  CAPA 2: Yield Calculator                                        │
│  Computa yield desde historia propia. Sin APIs externas.         │
│  LECAP: TEA desde precio almacenado + metadata del ticker        │
│  BOND/ON: retorno observado desde value_usd history              │
│  FCI: retorno 30d desde vcp_history                              │
│  Position: retorno real desde PositionSnapshot history           │
└────────────────────────────┬────────────────────────────────────┘
                             │ si no hay datos suficientes
┌────────────────────────────▼────────────────────────────────────┐
│  CAPA 3: Bootstrap (sistema actual)                              │
│  BYMA / ArgentinaDatos / tablas estáticas                        │
│  Solo actúa los primeros 7-30 días hasta que Price Store tenga   │
│  historia suficiente. Luego queda inactivo.                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tablas nuevas — migración Alembic

### `instrument_prices`

```sql
CREATE TABLE instrument_prices (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20)    NOT NULL,
    price_date      DATE           NOT NULL,
    price_ars       DECIMAL(14,4),   -- precio en ARS (LECAP, BOND, ON, CEDEAR, STOCK)
    price_usd       DECIMAL(14,6),   -- precio en USD (BOND, ON, CEDEAR)
    vwap_ars        DECIMAL(14,4),   -- precio promedio ponderado por volumen (BYMA)
    tem             DECIMAL(8,6),    -- TEM contractual (solo LECAP)
    emision_date    DATE,            -- fecha de emisión (solo LECAP, BOND)
    maturity_date   DATE,            -- fecha de vencimiento (LECAP, BOND, CAUCION)
    source          VARCHAR(20)  NOT NULL DEFAULT 'BYMA',
    UNIQUE (ticker, price_date)
);

CREATE INDEX idx_instrument_prices_ticker_date ON instrument_prices (ticker, price_date DESC);
```

**Por qué `tem` y `emision_date` en esta tabla:**
Para una LECAP, `TEA = (VNV / precio)^(365/días) - 1` donde `VNV = 100 × (1+TEM)^meses_totales`.
La TEM viene de `fichatecnica` de BYMA — la guardamos una sola vez al primer fetch. No cambia en la vida del instrumento. Así evitamos llamar a `fichatecnica` todos los días.

---

### `fci_vcp_history`

```sql
CREATE TABLE fci_vcp_history (
    id          SERIAL PRIMARY KEY,
    fondo_name  VARCHAR(100)   NOT NULL,
    categoria   VARCHAR(50)    NOT NULL,
    price_date  DATE           NOT NULL,
    vcp         DECIMAL(18,6)  NOT NULL,   -- valor cuota parte del día
    source      VARCHAR(20)    NOT NULL DEFAULT 'ArgentinaDatos',
    UNIQUE (fondo_name, price_date)
);

CREATE INDEX idx_fci_vcp_ticker_date ON fci_vcp_history (fondo_name, price_date DESC);
```

**Por qué no usar `PositionSnapshot` para FCI:**
Un fondo puede estar en el portfolio de muchos usuarios. El VCP es único por fondo por día — no tiene sentido duplicarlo por user. La historia del VCP es un dato de mercado, no de usuario.

---

### Extensión de `position_snapshots`

Agregar dos columnas a la tabla existente:

```sql
ALTER TABLE position_snapshots
    ADD COLUMN value_ars  DECIMAL(14,2) DEFAULT NULL,
    ADD COLUMN mep        DECIMAL(10,2) DEFAULT NULL;
```

`value_ars`: valor en ARS al momento del snapshot (para instrumentos ARS).
`mep`: tipo de cambio MEP del día del snapshot.

Con estos dos campos, dado cualquier snapshot histórico, podemos reconstruir el valor en USD con el MEP de esa fecha — capturando así el efecto de devaluación automáticamente.

---

## El cálculo correcto por tipo de instrumento

### LECAP (S-prefix) — TEA desde precio almacenado

```python
def compute_lecap_tea(ticker: str, price_date: date, db) -> Decimal | None:
    row = db.query(InstrumentPrice).filter(
        InstrumentPrice.ticker == ticker,
        InstrumentPrice.price_date == price_date
    ).first()

    if not row or not row.vwap_ars or not row.tem or not row.maturity_date:
        return None

    days = (row.maturity_date - price_date).days
    if days <= 0:
        return Decimal("0")

    # Meses totales desde emisión a vencimiento (para calcular VNV)
    total_months = (
        (row.maturity_date.year - row.emision_date.year) * 12
        + (row.maturity_date.month - row.emision_date.month)
    )
    vnv = Decimal("100") * (1 + row.tem) ** total_months
    tea = (vnv / row.vwap_ars) ** (Decimal("365") / days) - 1

    if -0.1 <= float(tea) <= 5.0:  # sanity: entre -10% y +500%
        return tea.quantize(Decimal("0.0001"))
    return None
```

**Sin BYMA en runtime.** BYMA solo se consulta en el job diario que llena `instrument_prices`.

---

### LECAP CER (X-prefix) — TIR real desde delta de precios

```python
def compute_cer_tir(ticker: str, db, days_window: int = 30) -> Decimal | None:
    """
    La TIR real de una LECAP CER es el rendimiento sobre el CER.
    Si guardamos el precio diario en ARS y el índice UVA/CER diario,
    podemos calcular el spread real sin BYMA.

    Retorno real = (precio_hoy / precio_30d × índice_30d / índice_hoy) ^ (365/30) - 1
    """
    prices = db.query(InstrumentPrice).filter(
        InstrumentPrice.ticker == ticker
    ).order_by(InstrumentPrice.price_date.desc()).limit(days_window + 5).all()

    if len(prices) < 7:
        return None

    newest = prices[0]
    oldest = prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days
    if elapsed < 3:
        return None

    # Si tenemos UVA histórico (guardado en instrument_prices con ticker="UVA")
    # podemos calcular el retorno real. Por ahora: retorno nominal ARS anualizado.
    ars_return = (newest.vwap_ars / oldest.vwap_ars) ** (Decimal("365") / elapsed) - 1
    return ars_return
```

**Fase futura:** agregar UVA diario a `instrument_prices` → cálculo de TIR real completo.

---

### BOND / ON — Retorno observado desde precio histórico

```python
def compute_bond_return(ticker: str, db, days_window: int = 30) -> Decimal | None:
    """
    YTM aproximada desde variación de precio observada.
    Para bonos con cupones: el retorno observado incluye precio + cupón cobrado.
    La tabla _BOND_YTM estática desaparece — el mercado mide mejor que cualquier tabla.
    """
    prices = db.query(InstrumentPrice).filter(
        InstrumentPrice.ticker == ticker
    ).order_by(InstrumentPrice.price_date.desc()).limit(days_window + 5).all()

    if len(prices) < 7:
        return None

    newest = prices[0]
    oldest = prices[-1]
    elapsed = (newest.price_date - oldest.price_date).days
    if elapsed < 3:
        return None

    # BOND cotiza en USD (o ARS/D): usamos price_usd si disponible, si no price_ars/mep
    if newest.price_usd and oldest.price_usd and oldest.price_usd > 0:
        raw = (newest.price_usd / oldest.price_usd) ** (Decimal("365") / elapsed) - 1
    elif newest.price_ars and oldest.price_ars and oldest.price_ars > 0:
        # Convertir con MEP del portafolio snapshot del mismo día
        raw = (newest.price_ars / oldest.price_ars) ** (Decimal("365") / elapsed) - 1
    else:
        return None

    if -0.3 <= float(raw) <= 0.5:  # -30% a +50% anual para bonos soberanos
        return raw.quantize(Decimal("0.0001"))
    return None
```

---

### FCI — Retorno 30d desde VCP histórico propio

```python
def compute_fci_yield(fondo_name: str, categoria: str, db) -> Decimal | None:
    """
    TNA real del fondo desde su VCP history propio.
    Si tenemos >= 30 días de VCP → cálculo exacto.
    Si tenemos >= 7 días → aproximación razonable.
    """
    rows = db.query(FciVcpHistory).filter(
        FciVcpHistory.fondo_name == fondo_name,
        FciVcpHistory.categoria == categoria
    ).order_by(FciVcpHistory.price_date.desc()).limit(35).all()

    if len(rows) < 2:
        return None

    newest = rows[0]
    oldest = rows[-1]
    elapsed = (newest.price_date - oldest.price_date).days
    if elapsed < 3:
        return None

    tna = (newest.vcp / oldest.vcp) ** (Decimal("365") / elapsed) - 1
    if 0 < float(tna) < 5.0:  # 0% a 500% — amplio para Argentina
        return tna.quantize(Decimal("0.0001"))
    return None
```

---

### Position — Retorno real desde PositionSnapshot + value_ars/mep

```python
def compute_position_actual_return(
    db, user_id: str, ticker: str, asset_type: str, days: int = 30
) -> Decimal | None:
    """
    El yield más preciso posible: retorno observado real de la posición del usuario.
    Captura todo: apreciación, devaluación, cupones, amortizaciones.
    No depende de ningún cálculo externo.
    """
    snaps = db.query(PositionSnapshot).filter(
        PositionSnapshot.user_id == user_id,
        PositionSnapshot.ticker == ticker
    ).order_by(PositionSnapshot.snapshot_date.asc()).all()

    if len(snaps) < 2:
        return None

    # Tomar ventana de hasta `days` días
    newest = snaps[-1]
    cutoff = newest.snapshot_date - timedelta(days=days)
    window = [s for s in snaps if s.snapshot_date >= cutoff]
    if len(window) < 2:
        return None

    oldest = window[0]
    elapsed = (newest.snapshot_date - oldest.snapshot_date).days
    if elapsed < 3:
        return None

    # Para ARS: usar value_ars + mep del día (captura efecto devaluación)
    if asset_type in ("LETRA", "FCI") and oldest.value_ars and newest.value_ars and oldest.mep and newest.mep:
        usd_old = float(oldest.value_ars) / float(oldest.mep)
        usd_new = float(newest.value_ars) / float(newest.mep)
    else:
        usd_old = float(oldest.value_usd)
        usd_new = float(newest.value_usd)

    if usd_old <= 0:
        return None

    raw = (usd_new / usd_old - 1) * (365 / elapsed)
    if -0.5 <= raw <= 2.0:  # -50% a +200% anual
        return Decimal(str(round(raw, 4)))
    return None
```

---

## El job diario: Price Collector

Nuevo scheduler job que corre junto al daily close (después del sync, antes del snapshot):

```python
# scheduler.py — nuevo job
async def _collect_daily_prices(db: Session) -> None:
    """
    Corre una vez por día hábil a las 18:00 (post-cierre BYMA).
    Guarda precios de cierre en instrument_prices y fci_vcp_history.
    Si BYMA no responde → guarda el último precio conocido como proxy.
    Nunca falla silenciosamente: loguea qué pudo y qué no.
    """

    # 1. LECAPs — precio + metadata contractual (TEM, fechas)
    letras = byma_client.fetch_all_letras()  # btnLetras POST, una sola llamada
    for letra in letras:
        ticker = letra["symbol"]
        ficha = byma_client.get_ficha_tecnica_cached(ticker)  # cache 24h — metadata no cambia
        upsert_instrument_price(db, InstrumentPrice(
            ticker=ticker,
            price_date=date.today(),
            vwap_ars=letra["vwap"],
            tem=ficha.get("tem"),
            emision_date=ficha.get("emision"),
            maturity_date=ficha.get("vencimiento"),
            source="BYMA"
        ))

    # 2. BONDs soberanos — precio USD
    soberanos = byma_client.fetch_all_soberanos()  # btnTitPublicos POST
    for bond in soberanos:
        upsert_instrument_price(db, InstrumentPrice(
            ticker=bond["symbol"],
            price_date=date.today(),
            price_usd=bond.get("price_usd") or bond.get("vwap") / mep,
            price_ars=bond.get("vwap"),
            source="BYMA"
        ))

    # 3. ONs corporativas
    ons = byma_client.fetch_all_ons()  # btnObligNegociables POST
    for on in ons:
        upsert_instrument_price(db, InstrumentPrice(
            ticker=on["symbol"],
            price_date=date.today(),
            price_usd=on.get("price_usd") or on.get("vwap") / mep,
            source="BYMA"
        ))

    # 4. FCIs — VCP diario de todas las categorías
    for categoria in ["mercadoDinero", "rentaMixta", "rentaVariable", "rentaFija"]:
        fondos = argentinadatos_client.fetch_fci_categoria(categoria)
        for fondo in fondos:
            upsert_fci_vcp(db, FciVcpHistory(
                fondo_name=fondo["fondo"],
                categoria=categoria,
                price_date=date.today(),
                vcp=fondo["vcp"],
                source="ArgentinaDatos"
            ))

    # 5. MEP del día (ya lo tenemos en BudgetConfig — también guardarlo en instrument_prices)
    upsert_instrument_price(db, InstrumentPrice(
        ticker="MEP",
        price_date=date.today(),
        price_ars=mep_today,
        source="IOL"
    ))

    logger.info("_collect_daily_prices: %d letras, %d bonos, %d ONs, %d FCIs guardados",
                len(letras), len(soberanos), len(ons), fci_count)
```

**Costo por ejecución:** ~5 llamadas HTTP (una por panel BYMA + una a ArgentinaDatos por categoría). Se resuelve en < 10 segundos. Si BYMA falla → los datos del día anterior persisten y el yield calculator usa el último precio conocido.

---

## La cadena de fallback definitiva

```
Para cada posición, en orden:

1. compute_position_actual_return()  ← retorno real observado (PositionSnapshot)
   → requiere >= 7 días de snapshots

2. compute_<tipo>_yield() desde Price Store  ← precio almacenado propio
   → requiere >= 1 día de precio en instrument_prices / fci_vcp_history

3. Yield externo en tiempo real (sistema actual — BYMA/ArgentinaDatos)
   → solo si Price Store está vacío (usuario nuevo, instrumento nuevo)

4. Último yield conocido en DB (Position.annual_yield_pct actual)
   → si la API externa también falla

5. Promedio del tipo de instrumento (desde Position donde asset_type == X)
   → último recurso, nunca hardcodeado
```

Después de 7 días de Price Collector corriendo, **el nivel 3 nunca se activa**.
Después de 30 días, **el nivel 1 cubre la mayoría de los instrumentos** con retorno real observado.

---

## El fix del problema conceptual: yield en USD real

Con `value_ars` + `mep` en `PositionSnapshot`, el cálculo en `split_portfolio_buckets` cambia:

```python
# HOY (incorrecto)
renta_monthly += value_usd × annual_yield_pct_ars / 12

# v2 (correcto)
# annual_yield_pct ya vendrá calculado como retorno USD real
# porque compute_position_actual_return() usa:
#   usd_old = value_ars_old / mep_old
#   usd_new = value_ars_new / mep_new
# El yield resultante YA incluye el efecto devaluación.
# No hay multiplicación cruzada de unidades.
renta_monthly += value_usd × annual_yield_pct_real_usd / 12
```

El `annual_yield_pct` almacenado en `Position` pasa a ser el **retorno real en USD anualizado**, no la tasa nominal ARS. Esto afecta positivamente:
- Freedom score
- Renta mensual estimada
- Proyecciones de milestones
- InstrumentDetail yield display

---

## Impacto en datos de Marcos (ejemplo concreto)

| Instrumento | Yield actual (ARS nominal) | Yield v2 (USD real estimado) | Diferencia |
|-------------|---------------------------|------------------------------|------------|
| LECAP S31G6 | ~32% TNA ARS | ~3-8% USD real* | −24pp |
| COCOSPPA | ~18% TNA ARS | ~2-5% USD real* | −13pp |
| AL30D | ~16% YTM USD | ~16% YTM USD | Sin cambio |
| GD35 | ~15% YTM USD | ~15% YTM USD | Sin cambio |

*Estimación: depende del ritmo de crawling peg del peso. Con MEP estable → yield USD ≈ yield ARS. Con devaluación acelerada → yield USD negativo.

**Freedom score de Marcos hoy:** sobreestimado por la porción LECAP/FCI.
**Freedom score v2:** más conservador y correcto. Los bonos USD no cambian.

---

## Plan de implementación — sprints

### Sprint 10A — Infraestructura (no visible al usuario)
1. Migración Alembic: crear `instrument_prices`, `fci_vcp_history`
2. Extender `position_snapshots`: agregar `value_ars`, `mep`
3. `models.py`: agregar los tres modelos nuevos
4. `services/price_store.py`: funciones upsert para cada tabla
5. Poblar `value_ars` + `mep` en `save_position_snapshots()` (usa Position.current_value_ars + BudgetConfig.fx_rate)

### Sprint 10B — Price Collector
6. `services/price_collector.py`: job de recolección diaria (letras, bonos, ONs, FCIs, MEP)
7. `scheduler.py`: agregar `_collect_daily_prices` al daily close job (después de syncs, antes de snapshot)
8. Tests: mock BYMA → verifica que se guardan precios con fecha correcta; fallo BYMA → datos del día anterior persisten

### Sprint 10C — Yield Calculator v2
9. `services/yield_calculator_v2.py`: las 4 funciones compute_*
10. `yield_updater.py`: integrar cadena de fallback (v2 primero, luego sistema actual)
11. Tests TDD: posición con 7d history → usa price store; con 0d → usa BYMA fallback; BYMA down → usa último yield conocido

### Sprint 10D — Fix conceptual (el más visible)
12. `annual_yield_pct` en `Position` pasa a ser retorno USD real cuando se calculó con v2
13. `split_portfolio_buckets()`: sin cambios de código — el yield ahora es correcto por construcción
14. Frontend: cambiar label "18.52% anual" → mostrar unidad: "3.2% anual USD" o "32% anual ARS" según de dónde venga
15. Tests: freedom score con LECAP calcula retorno USD real, no TNA ARS

---

## Invariantes que deben mantenerse

1. **`instrument_prices` es append-only por día** — nunca se borra un precio histórico. Si el dato mejoró (ej: BYMA respondió después de un retry), se puede actualizar el precio del día actual pero no borrar.

2. **El fallback al sistema actual es transparente** — el caller no sabe si el yield viene del Price Store o de BYMA en tiempo real. La interfaz de `update_yields()` no cambia.

3. **`value_ars` en `PositionSnapshot` se guarda SIEMPRE que existe** — aunque la posición sea de un broker que no reporta ARS (ej: Binance). En ese caso `value_ars = NULL`, `mep = mep_del_día`. Nunca completar artificialmente.

4. **El yield en `annual_yield_pct` siempre debe indicar su denominación** — problema actual: no sabemos si el 0.32 guardado es TNA ARS o retorno USD. En v2: agregar campo `yield_currency CHAR(3) DEFAULT 'ARS'` a `Position`. Permite separar correctamente en `split_portfolio_buckets`.

---

## Decisiones de diseño

- **No usar TimescaleDB / InfluxDB**: Supabase PostgreSQL es suficiente para el volumen esperado (< 500 usuarios × 50 instrumentos × 365 días = 9M filas/año). Índices por (ticker, price_date DESC) son suficientes.
- **Metadata de LECAP en `instrument_prices`**: la TEM y fechas son invariantes del instrumento. No se vuelven a pedir a BYMA una vez almacenadas. Cache efectivo de por vida.
- **FCI VCP separado de instrument_prices**: el VCP es un dato por fondo (no por posición de usuario). Normalizar evita duplicación.
- **Retorno observado > yield calculado > yield de mercado**: la jerarquía refleja la calidad del dato. Lo que realmente ocurrió (retorno observado desde PositionSnapshot) es siempre más preciso que cualquier TEA o YTM calculada.
- **No eliminar el sistema actual hasta Sprint 10D**: conviven durante la transición. Rollback posible sin pérdida de datos.

---

## Archivos a crear/modificar

| Archivo | Tipo | Acción |
|---------|------|--------|
| `alembic/versions/xxxx_price_store.py` | migration | Crear: 3 tablas nuevas + 2 columnas |
| `backend/app/models.py` | existente | Agregar: `InstrumentPrice`, `FciVcpHistory` + campos en `PositionSnapshot`, `Position` |
| `backend/app/services/price_store.py` | nuevo | Upsert functions para cada tabla |
| `backend/app/services/price_collector.py` | nuevo | Job diario de recolección |
| `backend/app/services/yield_calculator_v2.py` | nuevo | Las 4 funciones compute_* |
| `backend/app/services/yield_updater.py` | existente | Integrar cadena de fallback v2 |
| `backend/app/scheduler.py` | existente | Agregar `_collect_daily_prices` al daily close |
| `backend/app/routers/portfolio.py` | existente | `split_portfolio_buckets` usa yield_currency |
| `backend/app/services/freedom_calculator.py` | existente | Separar renta ARS de renta USD |
| `tests/test_yield_calculator_v2.py` | nuevo | TDD: las 4 funciones + cadena fallback |
| `tests/test_price_collector.py` | nuevo | TDD: mock BYMA, fallo BYMA, idempotencia |
