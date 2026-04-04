# LEARNINGS — BuildFuture

> Qué fallió, qué funcionó, qué haríamos diferente. Se actualiza en cada iteración.

---

## Formato

```
## [YYYY-MM-DD] Título del aprendizaje
**Contexto:** Qué estábamos haciendo.
**Qué pasó:** El problema o descubrimiento.
**Solución / Decisión:** Cómo lo resolvimos.
**Aplica a:** [integración / arquitectura / UX / agentes / vibe-coding]
```

---

## [2026-04-03] IOL cotiza BOND/ON/LETRA per 100 VN nominal (convención BYMA)

**Contexto:** Cliente Matías reportó portfolio en millones. Investigación de precios históricos BOND/ON.  
**Qué pasó:** IOL devuelve `ppc` (precio promedio de compra) en ARS por cada 100 VN nominal para BOND, ON y LETRA. El código dividía `/100` solo para LETRA. Para BOND/ON, `ppc_usd` quedaba 100x mayor que `current_price_usd`.  
**Solución:** Extender la división `/100` a `asset_type in ("LETRA", "BOND", "ON")` en `iol_client.py`.  
**Aplica a:** integración — cualquier valor `ppc`/`ppc_ars` de IOL para instrumentos de renta fija es por 100 VN.

---

## [2026-04-03] Yahoo Finance devuelve precio NYSE, no precio CEDEAR ARS/MEP

**Contexto:** Fix de snapshots inflados — CEDEARs usando `yfinance` para precios históricos.  
**Qué pasó:** `yfinance` descarga el precio de la acción en NYSE (AMZN=$210, MELI=$1,800). El CEDEAR en Buenos Aires tiene una relación de equivalencia: 1 CEDEAR AMZN = 1/138 de la acción NYSE → precio CEDEAR = ARS/MEP ~$1.52 USD. Sin corrección, portfolio de $135K aparecía como $3.7M–$5.7M.  
**Solución:** Usar IOL `seriehistorica` como fuente primaria (retorna ARS/unidad → `/mep` = precio real). Yahoo solo como fallback con `equiv = round(yahoo_price / current_price_usd)` para corregir escala.  
**Aplica a:** integración — nunca usar Yahoo directamente para tickers CEDEAR argentinos.

---

## [2026-04-03] IOL clasifica bonos duales (NDT25/26/27) como STOCK

**Contexto:** Análisis de posiciones de Matías — NDT25 no aparecía en reconstrucción histórica.  
**Qué pasó:** IOL devuelve `tipo = "accion"` para NDT25 (bono dual soberano). El reconstructor ignoraba tipo STOCK.  
**Solución:** `_TICKER_TYPE_OVERRIDES` en `iol_client.py` — mapeo explícito por ticker.  
**Aplica a:** integración — cualquier nuevo instrumento que aparezca como tipo incorrecto en IOL.

---

## [2026-04-03] Railway no redespliega automáticamente tras merge a main

**Contexto:** PR #29 mergeado pero Railway seguía corriendo código viejo por horas.  
**Qué pasó:** Los commits post-merge (playbook docs, cherry-picks) no tocaban `backend/`. Railway puede tener el webhook desconectado o filtrar por paths. Cada auto-sync cada 4h regeneraba snapshots inflados con el código viejo.  
**Solución:** Bump de versión en `main.py` y push para forzar trigger. Verificar siempre con `/health` que la versión actualizada antes de dar deploy por hecho.  
**Aplica a:** arquitectura — siempre verificar `version` en `/health` post-deploy. 404 en endpoint nuevo = Railway no deployó.

---

## [2026-03-29] Crypto como fuente de portafolio desde el inicio

**Contexto:** Definiendo las fuentes del portafolio.

**Qué pasó:** El usuario tiene cuentas en Nexo y Bitso además de IOL. Incluirlos desde el diseño inicial evita tener que refactorizar el modelo de datos después.

**Solución / Decisión:** El modelo `Position` soporta `asset_type: CRYPTO` y `source: NEXO | BITSO | IOL`. El `PortfolioSyncAgent` consolida las tres fuentes antes de calcular el freedom score.

**Aplica a:** arquitectura, modelo de datos
