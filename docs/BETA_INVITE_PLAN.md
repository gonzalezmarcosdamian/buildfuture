# Beta por Invitación — Plan de Producto

> Documento vivo. Creado: 2026-04-03. Contexto: kickoff de marketing inminente.
> Estado: **EN PLANIFICACIÓN — sin implementación iniciada**

---

## Visión

BuildFuture pasa de tener registro público a **acceso por invitación personal**.

La beta no es comercial. Es un experimento real construido por alguien que lo necesitaba,
compartido con una comunidad seleccionada de argentinos que invierten activamente.

El flujo completo:

```
Kickoff MKT (post/reel/story)
  → Landing (solo waitlist — sin registro público)
    → Marcos revisa aplicaciones en backoffice
      → Aprueba → email con link único de 7 días
        → Usuario registra con ese link (validación cruzada)
          → Dashboard / FTU flow normal
      → Rechaza → email de notificación cortés
```

---

## Posicionamiento (story)

### Lo que cambia vs hoy

| Hoy | Beta por invitación |
|-----|---------------------|
| "Crear cuenta gratis" | Sin CTA de registro en landing |
| Registro público abierto | Solo por invite link personal |
| "Producto SaaS" | "Beta privada no comercial" |
| CTA doble: login + registro | Una sola acción: anotarse |

### Mensajes clave

- **No es un producto comercial** — es una herramienta que Marcos usa y comparte
- **Acceso limitado e intencionado** — no es para todos, eso tiene valor
- **Construido en público** — transparencia total, sin inversores, sin agenda corporativa
- **Comunidad primero** — las integraciones se priorizan por demanda real de la beta

### Landing nueva (copy orientativo)

- Hero: "Sabés cuánto invertís. ¿Sabés cuándo sos libre?"
- Sub: "Beta privada · Acceso por invitación · No comercial"
- CTA único: "Quiero estar en la beta" → scroll al form de waitlist
- Quitar: "Crear cuenta", "Iniciar sesión", referencias a precio/suscripción

---

## Fases de implementación

### Fase 0 — Story / Landing
Reposicionamiento visual y de copy. Sin cambios técnicos en backend.

**Alcance:**
- Nuevo copy del hero, sub y CTA
- Eliminar botones de login/registro de la LandingNav
- `/login` sigue existiendo pero sin acceso público desde la landing
- Waitlist form: agregar campo nombre (obligatorio) + contexto (opcional)
- Mensaje post-submit actualizado: "Revisamos tu solicitud y te escribimos"
- Usuarios autenticados que llegan a `/` → redirect `/dashboard` (ya funciona)

**Explícitamente fuera de scope:**
- No tocar el diseño visual base
- No cambiar la estructura de secciones (Hero, Integraciones, etc.)

---

### Fase 1 — Backend beta applications
Motor del flujo: aplicaciones con estados, tokens, emails.

**Alcance:**
- Extender tabla `waitlist_entries`:
  - `name TEXT` — nombre del aplicante
  - `context TEXT` — por qué quiere estar en la beta (opcional)
  - `status TEXT DEFAULT 'pending'` — pending | approved | rejected
  - `invite_token TEXT UNIQUE` — generado al aprobar
  - `token_expires_at TIMESTAMPTZ` — TTL del link (propuesta: 7 días)
  - `token_used_at TIMESTAMPTZ` — marca cuándo se usó (post-registro)
  - `reviewed_at TIMESTAMPTZ` — cuándo fue aprobado/rechazado
  - `rejection_reason TEXT` — interno, no se muestra al usuario
- Endpoints admin (auth requerida):
  - `GET /admin/beta/applications?status=pending|approved|rejected|all`
  - `POST /admin/beta/applications/{id}/approve` → genera token + envía email
  - `POST /admin/beta/applications/{id}/reject` → envía email de rechazo
- Endpoints públicos:
  - `GET /invite/validate/{token}` → `{ valid, email, expired }`
  - `POST /invite/register/{token}` → marca `token_used_at` post-registro
- Email service: **Resend** (resend.com)
  - SDK Python: `resend` PyPI
  - Free tier: 3.000 emails/mes — suficiente para beta
  - Variable nueva: `RESEND_API_KEY` en Railway
- Templates de email:
  - **Aprobación**: asunto, cuerpo con link `/invite/{token}`, aviso de expiración
  - **Rechazo**: asunto, cuerpo cortés, CTA "te avisamos en la próxima apertura"

**Explícitamente fuera de scope:**
- No crear tabla nueva — extender `waitlist_entries`
- No manejar reenvío de invite (primera versión: Marcos lo aprueba de nuevo)
- No roles ni múltiples admins — solo Marcos

---

### Fase 2 — Backoffice admin
UI para que Marcos gestione las aplicaciones.

**Alcance:**
- Ruta: `/admin/beta` — protegida por Supabase auth + check de email de admin
- Auth: si `user.email !== ADMIN_EMAIL` (env var) → redirect a landing
- UI:
  - Tabla de aplicaciones: nombre, email, fecha, status (pill), contexto (expandible)
  - Filtros: Pendientes · Aprobados · Rechazados · Todos
  - Acciones: botón "Aprobar" (verde) + "Rechazar" (gris) con modal de confirmación
  - Campo opcional de motivo de rechazo (interno, no se muestra al usuario)
  - Indicador de token expirado en aprobados (para re-aprobar si hace falta)
- Feedback inmediato: al aprobar/rechazar, la fila cambia de estado sin reload completo

**Explícitamente fuera de scope:**
- Sin notas internas por aplicación (v1)
- Sin paginación (volumen esperado < 200 en beta)
- Sin export CSV (v1)
- Sin dashboard de métricas de conversión (v1)

---

### Fase 3 — Registro por invitación
El usuario llega con su link único y puede registrarse.

**Alcance:**
- Página `/invite/[token]`:
  - Server component: valida token via `GET /invite/validate/{token}`
  - Si inválido/expirado → pantalla de error con CTA "volver a la landing"
  - Si válido → form con email pre-completado (no editable) + campo contraseña
  - Post-submit: Supabase `signUp` con email del token
  - On success: `POST /invite/register/{token}` → marca token usado → redirect `/dashboard`
- Deshabilitar registro público en Supabase:
  - Dashboard → Auth → Settings → "Enable Signups" = OFF
  - Los usuarios existentes NO se ven afectados (solo bloquea nuevos signups directos)
- Validación cruzada:
  - Email del formulario debe coincidir con email del token (backend verifica)
  - Token de un solo uso (second use → 400)
  - Token con expiración (expirado → 410 Gone)

**Explícitamente fuera de scope:**
- Sin magic link alternativo (v1)
- Sin reenvío de invite desde la página de error (v1)
- El FTU flow existente cubre el onboarding del nuevo usuario sin cambios

---

### Fase 4 — Waitlist form actualizado
Mejoras al formulario de captación con los nuevos campos.

**Alcance:**
- Agregar campo `nombre` (obligatorio) al form actual
- Agregar campo `contexto` como textarea opcional: "¿Por qué querés estar en la beta? (opcional)"
- Actualizar mensaje post-submit
- Actualizar endpoint `POST /waitlist/` para aceptar los nuevos campos
- Email de confirmación automático al anotarse: "Recibimos tu solicitud — te avisamos"

**Explícitamente fuera de scope:**
- Sin validación de LinkedIn o redes sociales
- Sin score automático de aplicaciones

---

## Diagrama de estados de una aplicación

```
       submit form
           ↓
       [pending]
       /       \
 [approved]  [rejected]
      ↓            ↓
  email         email
  con link      rechazo
      ↓
  [link_sent]       (token generado, no usado aún)
      ↓
  [registered]      (token_used_at seteado, usuario en Supabase)
```

---

## Dependencias técnicas

| Necesidad | Solución | Estado |
|-----------|----------|--------|
| Email transaccional | Resend (resend.com) | ⏳ Pendiente crear cuenta |
| Dominio de envío | @buildfuture.app o Gmail | ⚠️ Decisión pendiente |
| Deshabilitar signup público | Supabase dashboard (1 click) | ⏳ Pendiente |
| Token seguro | `secrets.token_urlsafe(32)` | ✅ Built-in Python |
| Auth backoffice | Supabase existente + env var ADMIN_EMAIL | ✅ Disponible |
| Tabla waitlist existente | `waitlist_entries` en Supabase DB | ✅ Existe |

---

## Preguntas abiertas (bloqueantes para arrancar)

1. **Email provider**: ¿Resend aprobado? ¿Usar dominio propio o Gmail para el from?
2. **Dominio**: ¿Ya tenemos `@buildfuture.app`? ¿O enviamos desde Gmail temporalmente?
3. **Fecha kickoff MKT**: ¿Cuándo es el post/reel/story? Define urgencia de cada fase
4. **Volumen esperado**: ¿Cuántas aplicaciones estimás recibir? Define prioridad del backoffice
5. **Usuarios existentes**: Marcos y cualquier tester actual son grandfathered in — ¿hay otros?
6. **Copy de emails**: ¿Escribís vos los textos de aprobación/rechazo o lo definimos juntos?
7. **TTL del invite**: ¿7 días es suficiente? ¿O querés más tiempo para que el usuario se organice?

---

## DoR (Definition of Ready) por fase

Ver sección completa a continuación.
