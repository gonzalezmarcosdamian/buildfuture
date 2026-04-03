# DoR — Beta por Invitación
## Definition of Ready por fase (iter 3 — auditoría completa Etapa 0)

> Una fase está **Ready** cuando todos los ítems ✅ están resueltos.
> ⚠️ Bloqueante. 🟡 Deseable. 📋 Legal específico.
> Actualizado: 2026-04-03

---

## Fase L — Legal (transversal)

Esta fase no tiene código. Debe completarse parcialmente **antes del primer beta user** (no antes del post de MKT).

| # | Acción | Quién | Esfuerzo | Prioridad | Estado |
|---|--------|-------|----------|-----------|--------|
| L1 | Registrar base de datos en AAIP (rnbd.aaip.gob.ar) | Marcos | 30 min | 🔴 Post-dominio | ⏳ Pendiente |
| L2 | Cláusula de transferencia internacional en TyC v1.1 | Dev | 1hs | 🔴 Antes 1er usuario | ⏳ Pendiente |
| L3 | Redactar Acuerdo de Beta | Marcos + Claude | 2hs | 🔴 Antes 1er usuario | ⏳ Pendiente |
| L4 | Disclaimer in-app en cada sugerencia visible | Dev | 1hs | 🔴 Antes 1er usuario | ⏳ Pendiente |
| L5 | Checkbox consent credenciales de broker en Settings | Dev | 2hs | 🟡 Deseable kickoff | ⏳ Pendiente |
| L6 | Política de breach notification (doc interno) | Marcos | 30 min | 🟡 Deseable | ⏳ Pendiente |
| L7 | Documentar proceso de cifrado en ARCHITECTURE.md | Dev | 30 min | 🟡 Deseable | ⏳ Pendiente |
| L8 | Opinión legal externa (CNV + datos personales) | Abogado externo | Externo | ⬜ Pre-comercial | ⏳ Pendiente |

### Por qué L1 (AAIP) es urgente y fácil

La Ley 25.326 Art. 21 obliga a registrar toda base de datos con información personal en el
Registro Nacional de Bases de Datos de la AAIP. No hacerlo no tiene consecuencias inmediatas,
pero ante cualquier denuncia o investigación, la ausencia del registro agrava la situación.
Es gratuito, tarda 30 minutos y muestra buena fe.

**Qué completar en el formulario:**
- Nombre del fichero: "BuildFuture — Usuarios Beta"
- Responsable: Marcos Damián González, DNI [tu DNI], ingonzalezdamian@gmail.com
- Finalidad: "Gestión de acceso a plataforma de seguimiento personal de portafolio de inversiones"
- Categoría de datos: identificativos (email), financieros (credenciales cifradas, posiciones)
- Medidas de seguridad: cifrado AES-256, acceso por JWT, servidores en EE.UU. (con consentimiento)
- Cesión a terceros: No (excepto proveedores de infraestructura: Supabase, Railway, Vercel)

### Contenido mínimo del Acuerdo de Beta (L3)

Distinto al TyC general — más específico y más corto. Cubre:

1. **Naturaleza no comercial de la beta**
   > "BuildFuture es un proyecto personal en etapa experimental, sin fines comerciales.
   > El acceso es gratuito y así seguirá mientras dure la beta."

2. **Limitación de responsabilidad beta**
   > "El software puede contener errores. BuildFuture no garantiza la exactitud de los datos
   > mostrados. El usuario es el único responsable de sus decisiones de inversión."

3. **Transición a modelo comercial**
   > "Si BuildFuture pasa a un modelo de pago, los usuarios beta recibirán 30 días de aviso
   > previo y podrán eliminar su cuenta sin penalidad."

4. **Confidencialidad (opcional pero recomendado)**
   > "Los participantes beta aceptan no compartir públicamente detalles técnicos internos
   > del producto sin autorización del fundador."

5. **Almacenamiento de credenciales de broker**
   > "Al conectar una cuenta de broker, el usuario autoriza a BuildFuture a almacenar
   > las credenciales de forma cifrada (AES-256) exclusivamente para sincronizar
   > sus posiciones de solo lectura. El usuario puede revocarlas en cualquier momento."

6. **Jurisdicción**
   > Argentina. Ciudad de Córdoba.

---

## Fase 0 — Landing + Pantallas de error

### Contexto: TyC en el flujo de invitación

El TyC **no se acepta en el paso de contacto** — se acepta dentro de la app vía TosModal (ya deployado).
El mecanismo es: Supabase invite → /auth/callback → /dashboard → TosGate muestra modal bloqueante → usuario acepta.
No se necesita checkbox en la landing. El registro en `tos_acceptances` queda con timestamp exacto.

### ⚠️ Bloqueantes — Landing

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 0.1 | **Copy del nuevo hero** | Titular, subtítulo, tagline de la beta | ⏳ Pendiente |
| 0.2 | **CTA principal** | Texto exacto del botón ("Quiero acceso →" u otro) | ⏳ Pendiente |
| 0.3 | **Datos de contacto de Marcos** | Email visible + LinkedIn URL + WhatsApp (opcional) | ⏳ Pendiente |
| 0.4 | **Copy del mensaje de contacto** | Qué ven los interesados encima del email/LinkedIn/WhatsApp | ⏳ Pendiente |
| 0.5 | **Copy FAQs nuevas** | Texto de "¿Cómo accedo?" y "¿Por qué beta cerrada?" | ⏳ Pendiente |

### ⚠️ Bloqueantes — Pantallas de error

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 0.E1 | **Copy bajo form de /login** | Texto para usuario sin acceso ("¿No tenés acceso? Beta cerrada. Contactá a Marcos") | ⏳ Pendiente |
| 0.E2 | **Copy de token de invitación expirado** | Qué le decimos cuando el link de Supabase venció | ⏳ Pendiente |
| 0.E3 | **Redirect de /register** | Confirmar que no existe página de registro — si existe, redirect a / | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 0.6 | Referencia visual del nuevo hero | Mockup o descripción |
| 0.7 | Secciones a quitar que pierdan sentido | ¿Alguna sección completa queda fuera de contexto? |

### Criterios de aceptación — Fase 0

**Landing:**
- [ ] Ningún CTA de "Crear cuenta" ni "Iniciar sesión" visible en ninguna sección (nav, hero, founder, brokers, CTA final, footer)
- [ ] CTA único disponible: scroll a sección de contacto
- [ ] Sección de contacto tiene email + LinkedIn de Marcos (WhatsApp opcional)
- [ ] Badge/tagline transmite "beta privada, no comercial, acceso por invitación"
- [ ] Paso 01 de PASOS dice "Recibí tu invitación", no "Creá tu cuenta"
- [ ] FAQs responden "¿Cómo accedo?" y "¿Por qué beta cerrada?"
- [ ] Footer auditado: sin links de registro
- [ ] SectionFounder y SectionBrokers auditados: sin CTAs de registro

**Pantallas de error:**
- [ ] `/login`: texto visible que explica que es beta cerrada + CTA para contactar a Marcos
- [ ] `/auth/callback` con token expirado: mensaje claro + CTA (no pantalla genérica de Supabase)
- [ ] Si existe `/register`: redirige a `/`

---

## Fase 1 — Backend beta applications

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 1.1 | **Email provider** | ¿Resend aprobado? | ⏳ Pendiente |
| 1.2 | **Cuenta Resend creada** | API key disponible antes de implementar | ⏳ Pendiente |
| 1.3 | **Dominio de envío** | buildfuture.app en trámite | ⏳ En trámite |
| 1.4 | **Copy email de aprobación** | Incluir link al Acuerdo de Beta + link al invite | ⏳ Pendiente |
| 1.5 | **Copy email de rechazo** | Tono, CTA "próxima apertura" | ⏳ Pendiente |
| 1.6 | **TTL del invite token** | Propuesta: 7 días | ⏳ Pendiente decisión |
| 1.7 | **Estrategia de re-invite** | Si token expira, ¿puede Marcos reenviar? | ⏳ Pendiente |
| 1.L1 | **Acuerdo de Beta redactado (L3)** | El email de aprobación lo referencia | ⏳ Depende de L3 |
| 1.L2 | **Campo `beta_agreement_accepted_at`** | Se setea en `POST /invite/register/:token` | ⏳ Decisión técnica |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 1.8 | Email automático al anotarse | Depende de decisión |
| 1.9 | `RESEND_API_KEY` en Railway secrets | Pre-configurar |
| 1.10 | Test en sandbox Resend antes de producción | No envía realmente en modo test |

### Criterios de aceptación

- [ ] `POST /waitlist/` acepta `{ email, name, context, source }` y persiste
- [ ] `POST /admin/beta/applications/{id}/approve` → genera token, setea expiración, envía email con link + acuerdo beta
- [ ] `POST /admin/beta/applications/{id}/reject` → cambia status, envía email de rechazo
- [ ] `GET /invite/validate/{token}` → `{ valid, email }` o `{ valid: false, reason }`
- [ ] `POST /invite/register/{token}` → setea `token_used_at` + `beta_agreement_accepted_at`
- [ ] Token de un solo uso, con expiración
- [ ] Endpoints admin protegidos (401 sin auth)
- [ ] Email de aprobación incluye link al Acuerdo de Beta

---

## Fase 2 — Backoffice admin

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 2.1 | **URL** | `/admin/beta` en mismo frontend | ⏳ Confirmar |
| 2.2 | **Email del admin** | `ADMIN_EMAIL` como env var | ⏳ Pendiente |
| 2.3 | **Motivo de rechazo visible para el usuario** | ¿Se incluye en el email o es solo interno? | ⏳ Decisión |
| 2.4 | **Tokens expirados** | ¿Indicador + botón reenviar en la tabla? | ⏳ Pendiente |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 2.5 | Notas internas por aplicación | Solo visibles para el admin |
| 2.6 | Orden por defecto | Propuesta: pendientes primero, luego fecha desc |
| 2.7 | Badge count de aplicaciones pendientes | Alerta visual |

### Criterios de aceptación

- [ ] Sin auth → redirect a `/login`
- [ ] Auth con email no-admin → redirect a landing
- [ ] Auth como admin → tabla con nombre, email, fecha, status, contexto
- [ ] Filtros funcionales sin reload
- [ ] Aprobar → confirmación → status cambia a aprobado + email enviado
- [ ] Rechazar → modal con motivo opcional → status cambia a rechazado + email enviado
- [ ] Aplicación ya procesada → botones deshabilitados

---

## Fase 3 — Registro por invitación

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 3.1 | **Impacto en usuarios existentes** | Deshabilitar signup NO afecta logins existentes — confirmar en docs Supabase | ⏳ Verificar |
| 3.2 | **Usuarios actuales en DB** | ¿Cuántos? ¿Todos son Marcos? Verificar en Supabase Auth → Users | ⏳ Pendiente |
| 3.3 | **Copy pantalla token expirado** | Mensaje + CTA para volver al contacto | ⏳ Pendiente |
| 3.4 | **Copy pantalla token ya usado** | Mensaje diferenciado del expirado | ⏳ Pendiente |
| 3.5 | **Post-registro redirect** | `/dashboard` directo (FTU existente) o pantalla de bienvenida | ⏳ Pendiente |
| 3.6 | **Copy error email no coincide** | Si el email del form ≠ email del token | ⏳ Pendiente |
| 3.L1 | **Checkbox explícito en `/invite/[token]`** | "Acepto el Acuerdo de Beta y los TyC" — no solo el botón | ⏳ Decisión UX |
| 3.L2 | **Acuerdo de Beta disponible online** | Link en `/invite/[token]` debe funcionar | ⏳ Depende de L3 |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 3.7 | Pantalla de bienvenida personalizada | "Bienvenido a la beta, [nombre]" |
| 3.8 | Nombre pre-completado en Supabase `user_metadata` | Del campo nombre del waitlist |

### Criterios de aceptación

- [ ] Token válido → form con email pre-completado + checkbox acuerdo de beta
- [ ] Token expirado → pantalla de error con copy definido + CTA a contacto
- [ ] Token ya usado → pantalla de error distinta al expirado
- [ ] Token inválido → 404
- [ ] Submit → Supabase signup → `POST /invite/register/{token}` → redirect
- [ ] Signup público directo bloqueado por Supabase setting
- [ ] `beta_agreement_accepted_at` guardado en DB
- [ ] Checkbox de acuerdo de beta requerido para submit

---

## Resumen ejecutivo — % de readiness

| Fase | Ready hoy | Principal cuello de botella |
|------|-----------|----------------------------|
| Fase L — Legal | 0% | AAIP (30 min), acuerdo beta (redacción), TyC v1.1 (dev) |
| Fase 0 — Landing + Errores | 30% | Copy hero, datos de contacto, copy pantallas de error |
| Fase 1 — Backend | 10% | Email provider, dominio, copy emails, acuerdo beta |
| Fase 2 — Backoffice | 30% | URL, email admin, decisión motivo rechazo |
| Fase 3 — Invite flow | 20% | Verificar usuarios existentes, pantallas de error, acuerdo beta |

**Decisiones que desbloquean Fase 0 (las más urgentes):**
1. Copy del hero — titular, subtítulo, tagline
2. Datos de contacto — email visible + LinkedIn + WhatsApp (opcional)
3. Copy de pantallas de error — /login sin acceso, token expirado

**Una vez que Marcos da esas decisiones → Fase 0 está 100% ready para implementar.**
