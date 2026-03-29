# Architecture Decision Records — BuildFuture

---

## ADR-001: Supabase como Auth + DB
**Fecha:** 2026-03-29  **Estado:** Accepted

**Contexto:** Necesitamos auth multi-usuario y DB relacional. Opciones: Supabase, Firebase, Auth0 + Postgres separado.

**Decisión:** Supabase. Integra Auth + Postgres + RLS en una sola plataforma. Free tier suficiente para el inicio. Auth helpers oficiales para Next.js.

**Consecuencias:** Vendor lock-in moderado. Ganamos RLS automático y reducimos infraestructura.

---

## ADR-002: Envelope Encryption para credenciales de brokers
**Fecha:** 2026-03-29  **Estado:** Accepted

**Contexto:** Los usuarios nos confían credenciales de ALYC y exchanges. Necesitamos poder usarlas en background (agentes scheduled) sin intervención del usuario.

**Decisión:** Envelope encryption con dos capas — KEK maestro en Railway env vars, DEK único por usuario en DB cifrado con el KEK. Credenciales cifradas con el DEK.

**Consecuencias:** Si DB se filtra, las credenciales son inútiles sin el KEK. Rotación de KEK posible sin re-pedir credenciales. Complejidad adicional en `encryption.py` justificada por el riesgo.

---

## ADR-003: Protocol-based abstraction para brokers y exchanges
**Fecha:** 2026-03-29  **Estado:** Accepted

**Contexto:** Necesitamos soportar múltiples ALYCs (IOL, Balanz, Cocos) y exchanges crypto (Nexo, Bitso, Binance) con diferente auth y schemas de respuesta.

**Decisión:** `BrokerClient` y `CryptoClient` como Python Protocols. Cada integración implementa la interfaz. El `PortfolioSyncAgent` no sabe qué broker está usando.

**Consecuencias:** Agregar una nueva ALYC = implementar el Protocol + registrar en la tabla `integrations`. Zero cambios en el agente.

---

## ADR-004: APScheduler in-process (sin Celery)
**Fecha:** 2026-03-29  **Estado:** Accepted

**Contexto:** Necesitamos agentes scheduled (semanal, mensual). Opciones: Celery + Redis, APScheduler, cron externo (Railway cron).

**Decisión:** APScheduler dentro del proceso FastAPI. Sin Redis, sin worker separado.

**Consecuencias:** Si el proceso se cae, los jobs no corren. Aceptable para esta escala (personal finance app, no fintech de producción). Migrar a Celery si el volumen de usuarios lo justifica.
