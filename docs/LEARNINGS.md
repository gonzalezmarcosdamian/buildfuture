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

## [2026-03-29] Crypto como fuente de portafolio desde el inicio

**Contexto:** Definiendo las fuentes del portafolio.

**Qué pasó:** El usuario tiene cuentas en Nexo y Bitso además de IOL. Incluirlos desde el diseño inicial evita tener que refactorizar el modelo de datos después.

**Solución / Decisión:** El modelo `Position` soporta `asset_type: CRYPTO` y `source: NEXO | BITSO | IOL`. El `PortfolioSyncAgent` consolida las tres fuentes antes de calcular el freedom score.

**Aplica a:** arquitectura, modelo de datos
