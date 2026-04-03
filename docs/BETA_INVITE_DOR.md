# DoR — Beta por Invitación
## Definition of Ready por fase

> Una fase está **Ready** cuando todos los ítems ✅ están resueltos.
> Los ítems ⚠️ son bloqueantes. Los ítems 🟡 son deseables pero no bloquean.
> Fecha: 2026-04-03

---

## Qué es DoR en este proyecto

Antes de escribir una línea de código de cada fase, este documento define qué
decisiones tienen que estar tomadas. El objetivo es no arrancar y parar a mitad.

---

## Fase 0 — Story / Landing

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 0.1 | **Copy del nuevo hero** | Texto del titular, subtítulo y tagline de la beta | ⏳ Pendiente |
| 0.2 | **CTA principal** | "Quiero estar en la beta" u otro texto | ⏳ Pendiente |
| 0.3 | **Qué pasa con /login en la nav** | ¿Desaparece de la LandingNav? ¿Solo se oculta? Los usuarios existentes necesitan poder entrar | ⏳ Pendiente |
| 0.4 | **Campos del form de waitlist** | ¿Nombre obligatorio? ¿Contexto opcional o también obligatorio? ¿Qué pregunta hace el campo contexto? | ⏳ Pendiente |
| 0.5 | **Copy del mensaje post-submit** | Qué le decimos al usuario cuando se anota (antes de la aprobación) | ⏳ Pendiente |
| 0.6 | **Email de confirmación al anotarse** | ¿Se manda un email automático de "recibimos tu solicitud"? ¿O solo el de aprobación/rechazo? | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 0.7 | Referencia visual del nuevo hero | Mockup o descripción detallada del look |
| 0.8 | Secciones a modificar/quitar de landing | ¿Alguna sección existente pierde sentido con el nuevo posicionamiento? |

### Criterios de aceptación

- [ ] Visitante anónimo llega a `/` y no ve ningún CTA de "Crear cuenta" ni "Iniciar sesión"
- [ ] La única acción disponible es completar el form de waitlist
- [ ] Usuario autenticado que llega a `/` → redirect automático a `/dashboard`
- [ ] El form acepta nombre + email + contexto (opcional) y da feedback de éxito/error
- [ ] Copy del hero transmite claramente "beta privada, no comercial"

---

## Fase 1 — Backend beta applications

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 1.1 | **Email provider** | ¿Resend aprobado? Alternativas: SendGrid, AWS SES, Mailgun. Resend es la propuesta por DX y free tier | ⏳ Pendiente decisión |
| 1.2 | **Cuenta Resend creada** | Necesita account + API key antes de implementar | ⏳ Pendiente |
| 1.3 | **Dominio de envío** | ¿Emails salen de `@buildfuture.app`? ¿O de Gmail temporalmente? Con Resend, enviar desde Gmail requiere dominio verificado o usar el sandbox de Resend | ⏳ Decisión bloqueante |
| 1.4 | **Copy email de aprobación** | Asunto, cuerpo, tono. Ejemplo: "Fuiste aceptado en la beta de BuildFuture — tu acceso expira en 7 días" | ⏳ Pendiente |
| 1.5 | **Copy email de rechazo** | Asunto, cuerpo cortés. Ejemplo: "Gracias por tu interés — la beta está completa por ahora, te avisamos en la próxima apertura" | ⏳ Pendiente |
| 1.6 | **TTL del invite token** | ¿7 días? ¿14 días? Depende de cuánto tiempo estimás que el usuario tarda en ver el email y registrarse | ⏳ Pendiente |
| 1.7 | **Estrategia de re-invite** | Si el token expira antes de que el usuario lo use, ¿Marcos puede volver a aprobar? ¿Hay botón en backoffice para reenviar? | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 1.8 | Email de confirmación automática al anotarse | Si se decide en Fase 0 que sí va, este template también se hace acá |
| 1.9 | Variable `RESEND_API_KEY` en Railway secrets | Pre-configurar para no hacerlo mid-deploy |
| 1.10 | Test de email en sandbox antes de producción | Resend tiene modo test que no envía realmente |

### Criterios de aceptación

- [ ] `POST /waitlist/` acepta `{ email, name, context, source }` y los persiste
- [ ] `POST /admin/beta/applications/{id}/approve` genera token único, setea `token_expires_at`, envía email con link
- [ ] `POST /admin/beta/applications/{id}/reject` cambia status, envía email de rechazo
- [ ] `GET /invite/validate/{token}` devuelve `{ valid: true, email }` o `{ valid: false, reason: "expired"|"not_found"|"used" }`
- [ ] `POST /invite/register/{token}` setea `token_used_at` — idempotente en segunda llamada
- [ ] Token de un solo uso: segundo intento de validar un token ya usado → `{ valid: false, reason: "used" }`
- [ ] Token expirado → `{ valid: false, reason: "expired" }`
- [ ] Endpoints admin protegidos con `get_current_user` — sin auth → 401

---

## Fase 2 — Backoffice admin

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 2.1 | **URL del backoffice** | ¿`/admin/beta` en el mismo frontend? ¿O ruta separada? La propuesta es `/admin/beta` en el mismo Vercel app | ⏳ Pendiente |
| 2.2 | **Email del admin** | ¿Qué email se usa para el check? `ingonzalezdamian@gmail.com` o uno `@buildfuture.app`. Va a ser env var `ADMIN_EMAIL` | ⏳ Pendiente |
| 2.3 | **Qué muestra el motivo de rechazo** | ¿El motivo que escribe Marcos en el backoffice se incluye en el email al usuario? ¿O es solo interno? | ⏳ Decisión de UX |
| 2.4 | **Qué pasa con tokens expirados** | En la tabla de aprobados, ¿hay indicador de "token expirado"? ¿Botón para re-aprobar (reenviar)? | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 2.5 | Notas internas por aplicación | Campo de texto que solo ve Marcos, no el usuario |
| 2.6 | Orden por defecto de la tabla | Propuesta: pendientes primero, luego por fecha desc |
| 2.7 | Indicador de aplicaciones nuevas | Badge con count en la nav del backoffice |

### Criterios de aceptación

- [ ] Acceder a `/admin/beta` sin estar logueado → redirect a `/login`
- [ ] Loguearse con email que no es el admin → redirect a landing (403)
- [ ] Loguearse como admin → ver tabla de aplicaciones con columnas: nombre, email, fecha, status, contexto
- [ ] Filtros pendientes/aprobados/rechazados/todos funcionan sin reload
- [ ] Botón "Aprobar" → modal de confirmación → confirmar → fila cambia a "aprobado" + email enviado
- [ ] Botón "Rechazar" → modal con campo de motivo opcional → confirmar → fila cambia a "rechazado" + email enviado
- [ ] No se puede aprobar/rechazar una aplicación ya procesada (botones deshabilitados)

---

## Fase 3 — Registro por invitación

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 3.1 | **Deshabilitar signup público en Supabase** | Confirmar que los usuarios existentes NO se ven afectados por esta configuración | ⏳ Verificar con Supabase docs |
| 3.2 | **Grandfathered users** | Marcos y cualquier tester actual necesitan seguir pudiendo hacer login. ¿Hay más usuarios además de Marcos en la DB hoy? | ⏳ Verificar |
| 3.3 | **Pantalla de error de token** | ¿Qué ve el usuario si el link ya expiró? ¿CTA para volver al waitlist? ¿Puede re-anotarse con el mismo email? | ⏳ Decisión de UX |
| 3.4 | **Post-registro redirect** | ¿Va directo al `/dashboard` (FTU flow existente) o hay una pantalla de bienvenida personalizada? | ⏳ Pendiente |
| 3.5 | **Validación de email cruzada** | El email del form de registro debe coincidir con el del token. Si no coincide, ¿qué error se muestra? | ⏳ Pendiente copy |
| 3.6 | **Campo nombre en Supabase** | ¿Se guarda el nombre del aplicante en `user_metadata` de Supabase al momento del signup? | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 3.7 | Pantalla de bienvenida personalizada | "Bienvenido a la beta, [nombre]" — diferente al FTU genérico |
| 3.8 | Pre-fill del campo contraseña con requisitos visibles | Indicador de fortaleza de contraseña |

### Criterios de aceptación

- [ ] Token válido → `/invite/{token}` muestra form con email pre-completado y no editable
- [ ] Token expirado → pantalla de error con mensaje claro y CTA
- [ ] Token ya usado → pantalla de error distinta ("esta invitación ya fue utilizada")
- [ ] Token inválido (no existe) → 404
- [ ] Submit del form → Supabase signup con el email del token
- [ ] Post-signup → `POST /invite/register/{token}` marca como usado → redirect `/dashboard`
- [ ] Intentar hacer signup público en Supabase directamente → bloqueado (Supabase setting)
- [ ] Usuario ya registrado que intenta usar el mismo token → error claro

---

## Fase 4 — Waitlist form actualizado

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 4.1 | **Texto exacto del campo contexto** | La pregunta que ve el usuario. Ejemplo: "¿Por qué querés estar en la beta? (opcional)" | ⏳ Pendiente |
| 4.2 | **¿Es obligatorio el nombre?** | Propuesta: sí. Permite que Marcos personalice el email de aprobación | ⏳ Pendiente |
| 4.3 | **¿Se manda email de confirmación al anotarse?** | Decidido en Fase 0. Si sí, el copy y template se definen acá | ⏳ Depende de 0.6 |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 4.4 | Validación de formato de nombre | Mínimo 2 caracteres, sin números |
| 4.5 | Textarea con límite visible | "0/200 caracteres" para el campo contexto |

### Criterios de aceptación

- [ ] Form muestra campos: Nombre (obligatorio) · Email (obligatorio) · Contexto (opcional)
- [ ] Submit sin nombre → error inline en el campo
- [ ] Submit sin email → error inline en el campo
- [ ] Submit con email ya registrado → responde OK (no revelar si el email existe)
- [ ] Post-submit → mensaje de confirmación con el texto acordado
- [ ] Si se decidió email automático: llega email dentro de 2 minutos de anotarse

---

## Preguntas de arquitectura transversales

Estas preguntas afectan múltiples fases y deben responderse antes de arrancar cualquiera:

### P1 — Dominio del email ⚠️ BLOQUEANTE

**Pregunta:** ¿Los emails de BuildFuture salen de qué dirección?

**Opciones:**
- `noreply@buildfuture.app` — requiere dominio `buildfuture.app` + DNS en Resend
- `marcos@buildfuture.app` — más personal, mismo requisito
- `ingonzalezdamian@gmail.com` — no requiere dominio pero menos profesional y Resend lo soporta con limitaciones

**Impacto:** Bloquea configuración de Resend (Fase 1)

---

### P2 — ¿Tenés el dominio `buildfuture.app`? ⚠️ BLOQUEANTE

**Pregunta:** ¿Compraste `buildfuture.app` o similar? Si no, hay que comprarlo antes de configurar email.

**Costo referencial:** ~USD 12/año en Namecheap / Google Domains

---

### P3 — Usuarios existentes en la DB

**Pregunta:** ¿Cuántos usuarios están registrados hoy en Supabase Auth?

**Por qué importa:** Al deshabilitar signup público, los usuarios existentes pueden seguir haciendo login. Pero si hay testers que Marcos invitó informalmente, necesitan confirmación de que no pierden acceso.

**Acción:** Verificar en Supabase Dashboard → Authentication → Users antes de Fase 3.

---

### P4 — Fecha del kickoff de marketing

**Pregunta:** ¿Cuándo es el post/reel/story del kickoff?

**Por qué importa:** Define qué fases son necesarias ANTES del kickoff y cuáles pueden ir después.

**Escenario mínimo viable para el kickoff:**
- Fase 0 ✅ (landing sin registro, solo waitlist con nombre)
- Fase 4 ✅ (form actualizado)
- Fases 1, 2, 3 pueden ser días después — en el interín Marcos aprueba manualmente y el registro abre temporalmente

---

### P5 — MVP vs full flow

**Pregunta:** ¿Querés lanzar el kickoff con el full flow (fases 0-4) o con un MVP más simple?

**MVP alternativo:**
- Landing actualizada (Fase 0) + form con nombre (Fase 4)
- Waitlist existente en DB, Marcos exporta manualmente el CSV y contacta por Gmail
- Registro sigue siendo público temporalmente (Supabase habilitado)
- Las Fases 1-3 (backend + backoffice + invite token) se hacen la semana post-kickoff

**Ventaja del MVP:** Lanzás el kickoff en 1-2 días de trabajo
**Desventaja:** Marcos gestiona aprobaciones a mano hasta que esté el backoffice

---

## Checklist de DoR — Resumen ejecutivo

Para considerar **READY** cada fase:

| Fase | % Ready hoy | Bloqueantes críticos |
|------|-------------|----------------------|
| **Fase 0** — Landing/Story | 20% | Copy del hero (0.1), campos del form (0.4), qué pasa con /login (0.3) |
| **Fase 1** — Backend emails | 10% | Provider de email (1.1), cuenta Resend (1.2), dominio (1.3), copy emails (1.4, 1.5) |
| **Fase 2** — Backoffice | 30% | URL (2.1), email admin (2.2), decisión motivo rechazo (2.3) |
| **Fase 3** — Invite flow | 25% | Confirmar impacto en Supabase (3.1), usuarios existentes (3.2), pantalla error (3.3) |
| **Fase 4** — Form actualizado | 50% | Copy del campo contexto (4.1), email de confirmación (4.3) |

**Ninguna fase está Ready para implementar hoy.**

El cuello de botella principal es: **dominio + email provider + copy**.
Esas tres decisiones desbloquean el 80% del resto.
