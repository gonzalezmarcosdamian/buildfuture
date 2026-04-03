# DoR — Beta por Invitación
## Definition of Ready por fase (iter 2 — enfoque legal)

> Una fase está **Ready** cuando todos los ítems ✅ están resueltos.
> ⚠️ Bloqueante. 🟡 Deseable. 📋 Legal específico.
> Actualizado: 2026-04-03

---

## Fase L — Legal (transversal)

Esta fase no tiene código. Debe completarse parcialmente **antes** de arrancar cualquier otra.
Los ítems marcados con 🔴 bloquean el kickoff de marketing.

| # | Acción | Quién | Esfuerzo | Prioridad | Estado |
|---|--------|-------|----------|-----------|--------|
| L1 | Registrar base de datos en AAIP (rnbd.aaip.gob.ar) | Marcos | 30 min | 🔴 Antes kickoff | ⏳ Pendiente |
| L2 | Cláusula de transferencia internacional en TyC v1.1 | Dev | 1hs | 🔴 Antes kickoff | ⏳ Pendiente |
| L3 | Redactar Acuerdo de Beta | Marcos + Claude | 2hs | 🔴 Antes kickoff | ⏳ Pendiente |
| L4 | Disclaimer in-app en cada sugerencia visible | Dev | 1hs | 🔴 Antes kickoff | ⏳ Pendiente |
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

## Fase 0 — Story / Landing

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 0.1 | **Copy del nuevo hero** | Titular, subtítulo, tagline de la beta | ⏳ Pendiente |
| 0.2 | **CTA principal** | "Quiero estar en la beta" u otro texto | ⏳ Pendiente |
| 0.3 | **Qué pasa con /login** | ¿Desaparece de la LandingNav? Usuarios existentes necesitan acceder | ⏳ Pendiente |
| 0.4 | **Campos del form de waitlist** | Nombre (obligatorio) + Contexto (¿obligatorio?) + pregunta exacta | ⏳ Pendiente |
| 0.5 | **Copy post-submit** | Qué le decimos al usuario cuando se anota | ⏳ Pendiente |
| 0.6 | **Email de confirmación al anotarse** | ¿Se manda automáticamente? ¿O solo aprobación/rechazo? | ⏳ Pendiente |
| 0.L1 | **TyC v1.1 con transferencia internacional** | L2 debe estar hecha antes de este deploy | ⏳ Depende de L2 |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 0.7 | Referencia visual del nuevo hero | Mockup o descripción |
| 0.8 | Secciones a modificar/quitar | ¿Alguna pierde sentido con el nuevo posicionamiento? |

### Criterios de aceptación

- [ ] Visitante anónimo: sin CTA de "Crear cuenta" ni "Iniciar sesión" visible
- [ ] Única acción disponible: form de waitlist
- [ ] Usuario autenticado llega a `/` → redirect a `/dashboard`
- [ ] Form acepta nombre + email + contexto, da feedback de éxito/error
- [ ] Copy transmite "beta privada, no comercial, acceso por invitación"
- [ ] TyC v1.1 deployado con cláusula de transferencia internacional

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
| 1.8 | Email automático al anotarse | Depende de decisión 0.6 |
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
| 3.3 | **Pantalla de token expirado** | Copy del error, CTA para volver al waitlist | ⏳ Pendiente |
| 3.4 | **Post-registro redirect** | `/dashboard` directo (FTU existente) o pantalla de bienvenida | ⏳ Pendiente |
| 3.5 | **Copy error email no coincide** | Si el email del form ≠ email del token | ⏳ Pendiente |
| 3.L1 | **Checkbox explícito en `/invite/[token]`** | "Acepto el Acuerdo de Beta y los TyC" — no solo el botón | ⏳ Decisión UX |
| 3.L2 | **Acuerdo de Beta disponible online** | Link en `/invite/[token]` debe funcionar | ⏳ Depende de L3 |

### 🟡 Deseables

| # | Item | Nota |
|---|------|------|
| 3.6 | Pantalla de bienvenida personalizada | "Bienvenido a la beta, [nombre]" |
| 3.7 | Nombre pre-completado en Supabase `user_metadata` | Del campo nombre del waitlist |

### Criterios de aceptación

- [ ] Token válido → form con email pre-completado + checkbox acuerdo de beta
- [ ] Token expirado → pantalla de error con copy definido + CTA
- [ ] Token ya usado → pantalla de error distinta
- [ ] Token inválido → 404
- [ ] Submit → Supabase signup → `POST /invite/register/{token}` → redirect
- [ ] Signup público directo bloqueado por Supabase setting
- [ ] `beta_agreement_accepted_at` guardado en DB
- [ ] Checkbox de acuerdo de beta requerido para submit

---

## Fase 4 — Waitlist form actualizado

### ⚠️ Bloqueantes

| # | Item | Decisión requerida | Estado |
|---|------|--------------------|--------|
| 4.1 | **Texto del campo contexto** | Pregunta exacta que ve el usuario | ⏳ Pendiente |
| 4.2 | **¿Nombre obligatorio?** | Propuesta: sí | ⏳ Pendiente |
| 4.3 | **Email de confirmación automático** | Depende de 0.6 | ⏳ Pendiente |

### Criterios de aceptación

- [ ] Form: Nombre (obligatorio) · Email (obligatorio) · Contexto (según decisión 4.2)
- [ ] Validaciones inline por campo
- [ ] Email duplicado → responde OK (no revelar existencia)
- [ ] Post-submit → mensaje acordado
- [ ] Si hay email automático: llega en < 2 min

---

## Resumen ejecutivo — % de readiness

| Fase | Ready hoy | Principal cuello de botella |
|------|-----------|----------------------------|
| Fase L — Legal | 0% | AAIP (30 min), acuerdo beta (redacción), TyC v1.1 (dev) |
| Fase 0 — Landing | 20% | Copy del hero, campos del form |
| Fase 1 — Backend | 10% | Email provider, dominio, copy emails, acuerdo beta |
| Fase 2 — Backoffice | 30% | URL, email admin, decisión motivo rechazo |
| Fase 3 — Invite flow | 20% | Verificar usuarios existentes, pantallas de error, acuerdo beta |
| Fase 4 — Form | 50% | Copy del campo contexto |

**El único cuello de botella que no requiere decisión de Marcos hoy:**
- Registrar en AAIP → se puede hacer ahora mismo, sin esperar nada

**Los cuellos de botella que desbloquean todo lo demás:**
1. Dominio (en trámite) → desbloquea email
2. Copy del hero y emails → desbloquea Fases 0 y 1
3. Acuerdo de Beta redactado → desbloquea Fases 1 y 3
