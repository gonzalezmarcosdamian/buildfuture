# Beta por Invitación — Plan de Producto

> Documento vivo. Creado: 2026-04-03. Actualizado: 2026-04-03 (iter 4 — auditoría completa Etapa 0).
> Estado: **Etapa 0 lista para implementar (pendiente OK de Marcos).**
> Objetivo: 0 problemas legales en el peor de los casos.

---

## Visión

BuildFuture pasa de tener registro público a **acceso controlado por el fundador**.

La beta no es comercial. Es un experimento real construido por alguien que lo necesitaba,
compartido con una comunidad seleccionada de argentinos que invierten activamente.

---

## Etapas del plan

```
Etapa 0 (ahora)         → Landing repositionada + contacto directo + Marcos da alta manual en Supabase
Etapa 1 (post-dominio)  → Waitlist form + emails automáticos via Resend
Etapa 2 (paralelo a 1)  → Backoffice admin para gestionar aplicaciones
Etapa 3 (post-1 y 2)    → Invite link único validado + signup bloqueado públicamente
Etapa L (transversal)   → Legal: AAIP, Acuerdo de Beta, TyC v1.1, consents
```

---

## Etapa 0 — MVP manual

### Qué es

Bloquear el registro público y reemplazar todos los CTAs de "Crear cuenta" por
contacto directo con Marcos. Sin backend adicional, sin invite tokens, sin emails automáticos.

Marcos recibe el contacto, evalúa, y da de alta manualmente en **Supabase Dashboard → Authentication → Users → Invite user**.

### Por qué es la decisión correcta

- **Lanzable hoy** — sin esperar dominio, email provider ni backoffice
- **Control total** — Marcos conoce personalmente a cada usuario de la beta
- **Cero riesgo legal de escala** — imposible argumentar "servicio comercial masivo"
- **Story auténtica** — "escribime, te agrego yo" es coherente con el posicionamiento de fundador
- **No bloquea el kickoff de MKT** — la landing nueva puede publicarse mientras

### Flujo Etapa 0

```
Kickoff MKT
  → Usuario llega a landing
    → Ve: "Beta cerrada · Acceso por invitación personal"
    → CTA único: "Quiero acceso →" → scroll a sección de contacto
      → Email / LinkedIn / WhatsApp con Marcos
        → Marcos evalúa
          → Sí → Supabase Dashboard → Add User → envía email de bienvenida manual
          → No → responde cortésmente
```

### Flujo de TyC por invitación

Los Términos y Condiciones se aceptan **dentro de la app**, no en el paso de contacto.
El mecanismo ya está deployado (TosGate + TosModal):

```
Marcos invita en Supabase Dashboard → "Send invitation"
  → Supabase envía email con link de registro
    → Usuario hace click → completa contraseña → entra a /auth/callback
      → Redirige a /dashboard
        → TosGate detecta que no aceptó TyC
          → TosModal bloqueante aparece (no se puede cerrar ni bypassear)
            → Usuario acepta TyC v1.0
              → Queda registrado en tos_acceptances con timestamp
                → Accede normalmente al dashboard
```

> **Por qué esto es suficiente:** TosModal es bloqueante y no dismissible. Es más robusto
> que un checkbox en un form externo que nadie controla. Queda registro en base de datos
> con timestamp exacto de aceptación por usuario.

### Cómo da de alta Marcos en Supabase

1. Ir a `supabase.com` → proyecto BuildFuture → Authentication → Users
2. Botón **"Add user"** → "Send an invitation" → ingresá el email del beta user
3. Supabase envía automáticamente un email de invitación con link de registro
4. El usuario hace click → completa su contraseña → listo

> **Importante:** Esto funciona aunque "Enable new user signups" esté deshabilitado.
> El admin siempre puede crear usuarios manualmente desde el dashboard.

---

## Qué se implementa en Etapa 0

### Supabase (Marcos hace esto manualmente, 1 clic)

- Dashboard → Auth → Settings → "Enable new user signups" → **OFF**

### Frontend — rama `feat/beta-stage0`

**Auditoría completa de secciones de landing:**

| Sección | Cambio |
|---------|--------|
| **LandingNav** | Sacar "Crear cuenta gratis" e "Iniciar sesión". Agregar link discreto "¿Ya tenés acceso? →" a /login |
| **SectionHero** | Badge "Beta cerrada · Acceso por invitación" + nuevo copy + CTA único scrollea a #contacto |
| **SectionComoFunciona (PASOS)** | Paso 01 "Creá tu cuenta" → "Recibí tu invitación" · Subtítulo "Tres pasos. Sin fricciones." → "Acceso personal. Sin fricciones." |
| **SectionWaitlist** | Convertir form en sección de contacto directo: email + LinkedIn + WhatsApp de Marcos |
| **SectionCTAFinal** | Nuevo copy sin CTA de registro. CTA → scroll a #contacto |
| **SectionFAQs** | Actualizar "¿Es gratis?" · Agregar "¿Cómo accedo?" y "¿Por qué beta cerrada?" |
| **SectionFounder** | Revisar si tiene CTA de registro al final — reemplazar por contacto |
| **SectionBrokers / Integraciones** | Revisar si tiene CTA de registro — eliminar o reemplazar |
| **Trust badges (hero)** | "Beta gratuita" → "Beta privada · No comercial" · "Open Finance · Argentina" → "Beta cerrada · Acceso por invitación" |
| **Footer** | Auditar links: eliminar "Crear cuenta" si existe. Mantener "Iniciar sesión" como link discreto |

**Pantallas de error (nuevas):**

| Escenario | Solución |
|-----------|----------|
| `/login` — usuario sin acceso intenta loguearse | Texto fijo bajo el form: "¿No tenés acceso todavía? Esta es una beta cerrada. → Contactá a Marcos" + link a #contacto en landing |
| `/register` (si existe) o signup directo | Redirect a `/` con banner "El acceso es por invitación. → Quiero acceso" |
| Email de Supabase con link expirado | `/auth/callback` maneja error de token expirado con mensaje claro + CTA para contactar a Marcos |

### Wording global — qué cambia

| Antes | Después |
|-------|---------|
| "Crear cuenta gratis" | Eliminado |
| "Iniciar sesión" | Solo como link discreto "¿Ya tenés acceso?" en nav |
| "Empezar gratis" | "Quiero acceso →" (scroll a #contacto) |
| "Beta gratuita" | "Beta privada · No comercial" |
| "Open Finance · Argentina" | "Beta cerrada · Acceso por invitación" |
| "01 — Creá tu cuenta" | "01 — Recibí tu invitación" |
| "Tres pasos. Sin fricciones." | "Acceso personal. Sin fricciones." |
| "¿Es gratis?" FAQ | "¿BuildFuture es gratuito?" — respuesta actualizada |
| Waitlist form | Sección de contacto directo con Marcos |

---

## Riesgo de deployar Etapa 0 para kickoff de MKT

### Técnico
| Riesgo | Prob | Mitigación |
|--------|------|-----------|
| Supabase signup OFF rompe algo en el login flow | Baja | Testear /login antes de publicar |
| CTA de registro que se pase sin cambiar | Media | Auditoría completa de secciones (ver tabla arriba) |
| Datos de contacto mal pegados en sección contacto | Media | QA manual antes de publicar |

### Legal
El post de MKT **no genera riesgo legal por sí mismo.** El riesgo comienza cuando Marcos agrega el primer beta user.
Eso da una ventana: publicar → recibir contactos → **antes de dar de alta al primer usuario**, tener:

1. Disclaimer in-app en sugerencias (L4) — 1hs dev
2. Acuerdo de Beta redactado (L3) — 2hs redacción
3. TyC v1.1 con cláusula transferencia internacional (L2) — 1hs dev

---

## Etapa 1 — Waitlist automatizada (post-dominio)

Cuando el dominio `buildfuture.app` esté disponible y Resend configurado.

**Qué agrega sobre Etapa 0:**
- Form de waitlist con nombre + email + contexto (reemplaza contacto manual)
- Email automático de confirmación al anotarse
- Emails de aprobación/rechazo disparados desde el backoffice
- Invite token único con TTL de 7 días

**Prerrequisitos bloqueantes:**
- Dominio `buildfuture.app` activo
- Cuenta Resend creada + DNS verificado
- Acuerdo de Beta redactado (para incluir en email de aprobación)
- Copy de emails definido

---

## Etapa 2 — Backoffice (paralelo a Etapa 1)

UI para que Marcos gestione aplicaciones sin ir al dashboard de Supabase.

**Qué agrega:**
- `/admin/beta`: tabla de aplicaciones con filtros pending/approved/rejected
- Aprobar → genera token → dispara email automático
- Rechazar → dispara email de rechazo

**Prerrequisitos:** Etapa 1 backend funcionando.

---

## Etapa 3 — Invite link validado (post Etapas 1 y 2)

El signup de Supabase pasa a ser controlado por el backend de BuildFuture, no por el dashboard.

**Qué agrega:**
- `/invite/[token]`: página que valida el token antes de permitir el registro
- Validación cruzada: email del form debe coincidir con el del token
- `beta_agreement_accepted_at` guardado en DB
- Supabase "Enable new user signups" sigue OFF — el registro solo ocurre a través del invite link

**Prerrequisito:** Etapas 1 y 2 completas.

---

## Etapa L — Legal (transversal, sin código)

Sin dependencia técnica. Se puede avanzar en paralelo a cualquier etapa.

| # | Acción | Prioridad | Cuándo |
|---|--------|-----------|--------|
| L1 | Registrar base de datos en AAIP | Media | Post-dominio (necesita URL pública) |
| L2 | TyC v1.1 — cláusula transferencia internacional | Alta | Antes del primer beta user |
| L3 | Acuerdo de Beta redactado | Alta | Antes del primer beta user |
| L4 | Disclaimer in-app en sugerencias | Alta | Antes del primer beta user |
| L5 | Consent separado credenciales de broker | Media | Antes Etapa 3 |
| L6 | Breach notification doc interno | Media | Cuando haya tiempo |
| L7 | Opinión legal externa | Baja | Pre-comercial |

---

## Mapa de riesgo legal

| Riesgo | Prob | Impacto | Mitiga en |
|--------|------|---------|-----------|
| Usuario demanda por sugerencia | Baja | Medio | TyC v1.1 + disclaimer in-app |
| Brecha de credenciales | Baja | Muy alto | Consent + doc cifrado |
| Broker demanda por API | Muy baja | Bajo | Consent al conectar |
| AAIP (base no registrada) | Muy baja | Medio | Registro AAIP post-dominio |
| CNV (sugerencias reguladas) | Baja | Medio | Disclaimer in-app (L4) |
| Transferencia datos sin consent | Media | Medio | TyC v1.1 (L2) |

---

## Estado actual

| Etapa | Estado |
|-------|--------|
| Etapa 0 — MVP manual | ⏳ Lista para implementar — pendiente OK |
| Etapa 1 — Waitlist automatizada | ⏳ Pendiente dominio |
| Etapa 2 — Backoffice | ⏳ Pendiente |
| Etapa 3 — Invite link | ⏳ Pendiente |
| Etapa L — Legal | ⏳ En proceso (TyC v1.0 deployado) |
