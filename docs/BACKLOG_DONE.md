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
