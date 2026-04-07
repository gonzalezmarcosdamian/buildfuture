# Backlog — Ítems completados (bitácora)

> Registro de cada ítem del backlog cerrado: qué se hizo, por qué, dónde, cómo se detectó.
> Los ítems en ✅ Hecho del backlog son un resumen; este archivo es el detalle.

---

## 2026-04-06

### BUG — Avatar del dashboard muestra "M" para todos los usuarios

**Detectado por:** prueba con usuario beta Nicolás — el avatar del header mostraba "M" en lugar de "N".

**Root cause:**
`app/(app)/dashboard/page.tsx:59` tenía la inicial hardcodeada como string literal:
```tsx
<Link href="/settings" ...>
  M   ← hardcodeado, no viene del usuario autenticado
</Link>
```
Para Marcos funcionaba por coincidencia. Para cualquier otro usuario mostraba "M" igual.

**Análisis previo al fix:**
- `ProfileSection.tsx:153` ya tenía la lógica correcta:
  ```tsx
  const initial = (fullName || email || "?")[0].toUpperCase();
  ```
  usando `user.user_metadata.full_name` y `user.email` de `supabase.auth.getSession()`.
- `dashboard/page.tsx` es Server Component — no puede usar `useAuth()` directamente.
- Solución: extraer un `UserAvatar` Client Component que encapsule la lógica, evitando duplicarla.

**Archivos modificados:**
- `components/ui/UserAvatar.tsx` — nuevo Client Component; lee sesión Supabase, deriva inicial de `full_name || email`, renderiza círculo azul con Link a `/settings`
- `app/(app)/dashboard/page.tsx` — import `Link` eliminado del header; reemplazado el bloque hardcodeado por `<UserAvatar />`

**Retrocompat:** cambio visual puro. Usuarios existentes ven su propia inicial.

**Deuda técnica identificada (no bloqueante):**
`ProfileSection.tsx` tiene su propio círculo de avatar con la misma lógica — puede migrar a usar `<UserAvatar />` en una iteración futura para unificar.

---

## 2026-04-06 (2)

### BYMA 1 — TNA LECAPs en tiempo real para benchmark y recomendaciones

**Detectado por:** spike BYMA Open Data (`docs/SPIKE_BYMA_API.md`) — `lecap_tna_pct` en `market_data.py` estaba hardcodeado a 55%.

**Root cause:**
`MarketSnapshot.lecap_tna_pct = 55.0` era un valor estático. El Expert Committee y el `ProjectionCard` usaban ese número como benchmark de referencia de mercado, sin importar si la tasa real de las LECAPs había cambiado.

**Solución:**
- Nuevo `services/byma_client.py` con `get_lecap_tna()`:
  - Llama a `open.bymadata.com.ar/...free/short-term-government-bonds`
  - Filtra por `securityType == "LETRA"`, descarta vencidas y `impliedYield == 0`
  - Calcula promedio ponderado por volumen operado
  - Cache in-memory TTL 5 min (mismo patrón que `mep.py`)
  - Fallback a 55.0 si BYMA falla — nunca rompe el caller
- `market_data.fetch_market_snapshot()` llama `get_lecap_tna()` en el paso 4

**Tests TDD:** 9 tests en `tests/test_byma_client.py` escritos antes de la implementación. Suite completa: 297 tests, sin regresiones.

**Retrocompat:** `lecap_tna_pct` sigue siendo el mismo campo en `MarketSnapshot`. Todos los consumers sin cambios.

---

## 2026-04-06 (3)

### BYMA 2 — Precios de CEDEARs en ARS directo desde BYMA

**Detectado por:** root cause del bug de Matías — precios de CEDEARs vía Yahoo Finance usaban precio NYSE y requerían conversión `NYSE / ratio / MEP`, fuente de errores y snapshots inflados.

**Solución:**
- Nueva función `get_cedear_price_ars(ticker) -> float | None` en `byma_client.py`:
  - Llama a `open.bymadata.com.ar/...free/cedears` — descarga todos de una vez
  - Cachea el dict `{ticker: price_ars}` con TTL 5 min — una sola request para cualquier ticker
  - Retorna `None` si BYMA falla, ticker no existe, o precio es 0 (el caller decide el fallback)
- Integrado en `historical_reconstructor.py`: para CEDEARs en fecha de hoy, intenta BYMA antes que Yahoo. El fallback Yahoo con corrección por `equiv` sigue activo para tickers que BYMA no tenga o para fechas históricas.

**Tests TDD:** 6 tests nuevos en `test_byma_client.py`. Total byma: 26 tests verdes.

**Retrocompat:** Yahoo sigue como fallback. Los tickers que BYMA no cubra no se ven afectados. Schema sin cambios.

---

## 2026-04-06 (4)

### BYMA 3 — TIR real de bonos soberanos y ONs (reemplaza DEFAULT_YIELDS hardcoded)

**Detectado por:** `DEFAULT_YIELDS` en `iol_client.py` tenía `bono: 9%, on: 9%` calibrados manualmente. Se desactualizan con el mercado — en picos de stress los bonos pueden rendir >15%.

**Solución:**
- Dos nuevas funciones en `byma_client.py`:
  - `get_bond_tir(ticker) -> float | None` — endpoint `government-bonds`
  - `get_on_tir(ticker) -> float | None` — endpoint `corporate-bonds`
  - Ambas con cache dict TTL 5 min, caps de sanidad (BOND: 50%, ON: 30%), retornan `None` si anomalía → fallback al caller
- `_get_tir_from_cache()` — función interna reutilizada por ambas para evitar duplicación
- En `iol_client.py`, loop de sync: para cada posición BOND/ON, intenta BYMA antes del DEFAULT_YIELDS. Si BYMA retorna `None` → sigue con fallback hardcodeado.

**Tests TDD:** 11 tests nuevos en `test_byma_client.py`. Total byma: 26 tests verdes.

**Retrocompat:** `annual_yield_pct` en `Position` mismo campo. DEFAULT_YIELDS siguen como fallback permanente.

---
