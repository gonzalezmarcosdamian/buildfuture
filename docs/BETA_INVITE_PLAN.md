# Beta por Invitación — Plan de Producto

> Documento vivo. Creado: 2026-04-03. Actualizado: 2026-04-03 (iter 2 — enfoque legal).
> Estado: **EN PLANIFICACIÓN — sin implementación iniciada**
> Objetivo declarado: 0 problemas legales en el peor de los casos.

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

## Mapa de riesgo legal — peor caso

Antes de planificar las fases técnicas, hay que entender a qué exposición se enfrenta el proyecto
en el peor escenario. Esto define las prioridades del plan.

### Riesgo 1 — Usuario pierde dinero y demanda ⚠️ Alto

**Escenario:** Usuario sigue una sugerencia algorítmica, pierde capital y alega asesoramiento financiero.

**Marco legal:** Ley 26.831 Art. 2 — "Asesor de Inversiones" requiere registro CNV.

**Mitigación actual:** "sugerencias" en lugar de "recomendaciones", disclaimer CNV en /legal.

**Mitigación adicional necesaria:**
- Cláusula de limitación de responsabilidad específica para beta
- Disclaimer en cada sugerencia visible en la app (no solo en /legal)
- Registro explícito de que el usuario entendió y aceptó en la firma del acuerdo de beta

**Probabilidad de acción legal real:** Baja (montos pequeños, sin actividad comercial).
**Impacto si ocurre:** Medio (no hay dinero gestionado, solo lectura).

---

### Riesgo 2 — Brecha de seguridad expone credenciales de broker ⚠️ Muy Alto

**Escenario:** Hack, leak o error de código expone credenciales IOL/PPI/Cocos de un usuario.
El atacante ejecuta órdenes en nombre del usuario.

**Marco legal:** Ley 25.326 (responsabilidad del titular del banco de datos), potencial civil.

**Mitigación actual:** AES-256 declarado en TyC, sin acceso en plaintext.

**Mitigación adicional necesaria:**
- Documentar internamente el proceso de cifrado (qué librería, cómo se gestiona la clave)
- `ENCRYPTION_KEY` en Railway secrets, nunca en código
- Consent específico y separado para el guardado de credenciales de terceros
- Política de breach notification (qué hace Marcos si detecta una brecha)
- Recomendarle al usuario crear credenciales de solo lectura cuando el broker lo permite (IOL sí)

**Probabilidad:** Baja (proyecto pequeño, bajo perfil).
**Impacto si ocurre:** Muy alto (credenciales financieras de terceros).

---

### Riesgo 3 — Broker demanda por uso de su API ⚠️ Medio

**Escenario:** IOL, PPI o Cocos alegan que BuildFuture viola sus T&C al guardar credenciales de usuarios.

**Marco legal:** Derecho contractual (T&C del broker con el usuario), no regulatorio.

**Mitigación:**
- El usuario entrega sus propias credenciales voluntariamente
- BuildFuture no es parte del contrato entre usuario y broker
- Acknowledgment explícito: usuario declara conocer y aceptar los T&C de su broker

**Riesgo real:** Los brokers tienen incentivo en que más gente use sus plataformas, no en litigar.
**Probabilidad:** Muy baja.

---

### Riesgo 4 — AAIP investiga por Ley 25.326 🟡 Medio-Bajo

**Escenario:** AAIP (Agencia de Acceso a la Información Pública) detecta que BuildFuture
procesa datos personales sin registrar la base de datos.

**Marco legal:** Ley 25.326 Art. 21 — toda base de datos con información personal debe
registrarse en el Registro Nacional de Bases de Datos (RNBD) de AAIP.

**Estado actual:** No registrado.

**Mitigación:** Registrar la base en AAIP — es **gratuito, online y tarda 30 minutos**.
Hacerlo muestra buena fe ante cualquier investigación.
URL: rnbd.aaip.gob.ar

**Probabilidad de investigación proactiva:** Muy baja (AAIP investiga por denuncias).
**Pero:** Si hay una denuncia por cualquier otra causa, no estar registrado agrava la situación.

---

### Riesgo 5 — CNV investiga por asesoramiento no registrado 🟡 Bajo

**Escenario:** CNV interpreta las "sugerencias" como asesoramiento de inversión regulado.

**Marco legal:** Ley 26.831, RG CNV 906/2021.

**Por qué el riesgo es bajo:**
- No hay cobro — la beta es gratuita
- No hay ejecución de órdenes — solo lectura
- Las sugerencias son explícitamente algorítmicas y orientativas
- El proyecto no tiene escala ni visibilidad comercial todavía

**Mitigación:** El disclaimer en cada sugerencia visible + el lenguaje de TyC + la no-comercialidad.

---

### Riesgo 6 — Transferencia internacional de datos sin consentimiento 🟡 Medio

**Escenario:** Usuario argentino alega que sus datos personales fueron transferidos a servidores en EE.UU.
sin consentimiento explícito.

**Marco legal:** Ley 25.326 Art. 12 — transferencia a países sin "nivel adecuado de protección"
requiere consentimiento explícito del titular.

**Estado:** EE.UU. **no tiene** nivel adecuado reconocido por Argentina para datos financieros.
Supabase (US-East), Railway (US), Vercel (CDN global) → todos en territorio no reconocido.

**Mitigación necesaria:**
- Cláusula explícita en TyC: "Al usar BuildFuture, consentís que tus datos sean procesados
  en servidores ubicados en Estados Unidos (Supabase, Railway, Vercel)"
- Esta cláusula ya debe estar presente **antes del primer registro** — la aceptación del TyC
  en el modal de primer login la cubre, pero debe mencionarlo textualmente

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
- **Solo lectura** — BuildFuture nunca ejecuta órdenes, nunca mueve fondos

### Por qué el modelo de invitación reduce el riesgo legal

El invite flow no es solo un mecanismo de acceso — es una **herramienta legal**:

1. **Screening de usuarios**: Marcos puede verificar que son adultos, argentinos, inversores activos
2. **Relación contractual documentada**: la aprobación explícita crea un vínculo más fuerte que un signup público
3. **Audit trail**: timestamp de aprobación, versión de TyC aceptada, IP (opcional)
4. **No-comercialidad creíble**: un invite personal hace imposible argumentar que es un servicio comercial masivo
5. **Acuerdo de beta específico**: en el email de aprobación se puede incluir el acuerdo de beta que el usuario acepta al registrarse

---

## Fases de implementación (iteradas)

### Fase L — Legal (transversal, no técnica)
Precede y acompaña todas las fases técnicas. Sin costo de desarrollo.

**Acciones concretas:**

**L1 — Registrar base de datos en AAIP** *(~30 min, gratuito)*
- URL: rnbd.aaip.gob.ar
- Nombre del fichero: "BuildFuture — Datos de usuarios beta"
- Finalidad: "Gestión de acceso a plataforma de seguimiento de portafolio personal"
- Responsable: Marcos Damián González
- Datos: email, credenciales de broker (cifradas), posiciones de portafolio, presupuesto personal

**L2 — Actualizar TyC con cláusula de transferencia internacional**
- Agregar en sección Privacidad: consentimiento explícito para datos en servidores US
- Agregar en sección Credenciales: consent específico para guardado de credenciales de broker
- Versionar como TyC v1.1 (trigger re-aceptación de usuarios existentes vía TosGate)

**L3 — Acuerdo de beta separado**
- Documento más corto y específico que el TyC general
- Contenido: naturaleza no comercial, limitación de responsabilidad beta, confidencialidad opcional,
  qué pasa cuando deje de ser beta (aviso 30 días, opción de eliminar cuenta)
- Se incluye en el email de aprobación como PDF o link
- El usuario lo acepta implícitamente al registrarse con el invite link

**L4 — Disclaimer en cada sugerencia (in-app)**
- Texto corto bajo cada sugerencia visible: "Sugerencia algorítmica · No es asesoramiento financiero · Ley 26.831"
- No solo en /legal — tiene que estar en el momento de consumo

**L5 — Política de breach notification (interna)**
- Documento interno (no público): qué hace Marcos si detecta una brecha
- Pasos: 1) revocar tokens de DB, 2) notificar usuarios afectados en 72hs, 3) reportar a AAIP
- No es código — es un checklist en docs/

**L6 — Documentar el proceso de cifrado de credenciales**
- En ARCHITECTURE.md: qué librería, cómo se gestiona `ENCRYPTION_KEY`, quién tiene acceso
- Esto es evidencia de buenas prácticas si hay una investigación

---

### Fase 0 — Story / Landing
Sin cambios vs plan anterior. Ver DoR.

---

### Fase 1 — Backend beta applications
**Adiciones vs plan anterior:**

- Al aprobar un usuario, el email de aprobación incluye:
  - Link al Acuerdo de Beta (Fase L3)
  - La aceptación del invite link = aceptación del Acuerdo de Beta (documentado en DB)
- Nuevo campo en `waitlist_entries`: `beta_agreement_accepted_at` — se setea en `POST /invite/register/:token`
- El `TosGate` existente ya maneja el TyC general — el acuerdo de beta es un segundo consent más específico

---

### Fase 2 — Backoffice admin
Sin cambios vs plan anterior. Ver DoR.

---

### Fase 3 — Registro por invitación
**Adiciones vs plan anterior:**

- La pantalla `/invite/[token]` muestra explícitamente:
  - "Al registrarte aceptás el Acuerdo de Beta y los Términos y Condiciones"
  - Link al Acuerdo de Beta
  - Link al TyC
  - Checkbox explícito (no suficiente con el botón de submit)
- Separar el consent de credenciales de broker del TyC general:
  - En Settings → integración IOL/PPI/Cocos: checkbox específico "Entiendo que BuildFuture guardará
    mis credenciales cifradas con AES-256 y acepto los términos de uso de mi broker"
  - Solo se muestra al conectar por primera vez

---

### Fase 4 — Waitlist form actualizado
Sin cambios vs plan anterior. Ver DoR.

---

## Recomendaciones priorizadas

### Prioridad 1 — Hacer AHORA (sin fecha de kickoff)

| # | Acción | Esfuerzo | Impacto legal |
|---|--------|----------|---------------|
| R1 | Registrar base en AAIP | 30 min | Elimina riesgo Ley 25.326 Art. 21 |
| R2 | Agregar cláusula transferencia internacional en TyC | 1hs dev | Cubre Riesgo 6 |
| R3 | Documentar cifrado en ARCHITECTURE.md | 30 min | Evidencia de buenas prácticas |

### Prioridad 2 — Antes del kickoff

| # | Acción | Esfuerzo | Impacto legal |
|---|--------|----------|---------------|
| R4 | Acuerdo de beta redactado | 2hs redacción | Cubre Riesgos 1 y 2 |
| R5 | Disclaimer in-app en sugerencias | 1hs dev | Cubre Riesgo 5 (CNV) |
| R6 | Checkbox consent credenciales de broker | 2hs dev | Cubre Riesgo 2 |

### Prioridad 3 — Antes de ir comercial (sin urgencia ahora)

| # | Acción | Esfuerzo | Impacto |
|---|--------|----------|---------|
| R7 | Audit de seguridad básico (penetration test) | Externo | Riesgo 2 |
| R8 | Opinión legal formal de abogado CNV/datos personales | Externo ~$200USD | Todos los riesgos |
| R9 | Seguro de responsabilidad profesional | Externo | Riesgo 1 |

---

## Preguntas abiertas (actualizadas)

1. **Dominio** — en trámite ✅
2. **Email provider** — ¿Resend aprobado?
3. **Fecha kickoff MKT** — sin fecha aún
4. **Volumen esperado** — ¿cuántas aplicaciones estimás?
5. **Copy emails** — ¿Marcos escribe o lo definimos juntos?
6. **TTL invite** — propuesta: 7 días
7. **AAIP** — ¿querés que guiemos el proceso de registro?
8. **Acuerdo de beta** — ¿querés redactarlo en el próximo paso?
9. **Abogado externo** — ¿tenés contacto o necesitás referencias?

---

## Diagrama de estados (sin cambios)

```
       submit form
           ↓
       [pending]
       /       \
 [approved]  [rejected]
      ↓            ↓
  email         email
  con link      rechazo
  + acuerdo beta
      ↓
  [link_sent]
      ↓
  [registered]  ← beta_agreement_accepted_at seteado
```

---

## Dependencias técnicas (actualizadas)

| Necesidad | Solución | Estado |
|-----------|----------|--------|
| Email transaccional | Resend | ⏳ Pendiente cuenta |
| Dominio de envío | buildfuture.app | ⏳ En trámite |
| Deshabilitar signup público | Supabase dashboard | ⏳ Pendiente |
| Token seguro | `secrets.token_urlsafe(32)` | ✅ Built-in Python |
| Auth backoffice | Supabase + env var ADMIN_EMAIL | ✅ Disponible |
| Tabla waitlist existente | `waitlist_entries` | ✅ Existe |
| Registro AAIP | Manual en rnbd.aaip.gob.ar | ⏳ Pendiente — HACER YA |
| TyC v1.1 con transferencia int'l | Dev frontend | ⏳ Pendiente |
| Acuerdo de Beta | Redacción + PDF | ⏳ Pendiente |
