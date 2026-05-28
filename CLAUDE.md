# BuildFuture — Reglas de trabajo (Claude Code)

## REGLA ABSOLUTA — LEER ANTES DE CUALQUIER ACCIÓN

**NUNCA** hacer ninguna de estas acciones sin que el usuario diga explícitamente "mandá a prod", "deployá", "mergea", "push a main/master":

- Push a `main` (backend) o `master` (frontend submodule)
- `railway up` o cualquier deploy a Railway
- Mergear PRs
- `npx vercel` o cualquier comando que dispare Vercel

Esto incluye: fixes de una línea, bugfixes urgentes, "es solo un cambio pequeño". **Sin excepción.**

### El submodule frontend es especialmente peligroso
El directorio `frontend/` es un submodule que apunta a `buildfuture-frontend` en GitHub.
Cualquier `git push` dentro de `frontend/` a `master` **dispara Vercel automáticamente**.
Por eso: **todo trabajo en frontend va en una branch**, nunca directo en `master` del submodule.

### Flujo correcto para cada iteración
1. `git checkout -b feat/nombre` — tanto en el repo principal como en el submodule si aplica
2. Hacer cambios y commits en la branch
3. `gh pr create` → compartir URL al usuario
4. Esperar "ok mergea" antes de mergear
5. Esperar "deployá a Railway" antes de disparar deploy del backend

---

## Flujo obligatorio

### Nunca hacer directamente
- ❌ Push a `main` (backend) o `master` (frontend)
- ❌ Deployar a Railway sin autorización explícita
- ❌ Mergear PRs sin aprobación del usuario

### Siempre hacer
- ✅ Crear feature branch antes de cualquier cambio
- ✅ Abrir PR y compartir el link para revisión
- ✅ Esperar "ok mergea" o "deployá" antes de ejecutar

---

## Branches

| Repo | Producción | Naming branches |
|------|-----------|-----------------|
| `buildfuture` (backend) | `main` | `feat/`, `fix/`, `chore/` |
| `buildfuture-frontend` | `master` | `feat/`, `fix/`, `chore/` |

---

## Ciclo de vida de un cambio

```
1. git checkout -b feat/nombre-feature
2. Commits en la branch
3. Correr tests localmente ANTES del PR:
   - Backend: cd backend && python -m pytest tests/ -q (si existen tests)
   - Frontend: cd frontend && npx playwright test (E2E críticos)
   - Frontend types: cd frontend && npx tsc --noEmit
4. gh pr create → compartir URL al usuario
5. CI corre automáticamente (lint, types, build)
6. Usuario revisa y dice "ok mergea"
7. Mergear PR → Vercel auto-deploya el frontend
8. Usuario dice "deployá a Railway" → disparar deploy manual del backend
```

---

## Deploy a Railway

Solo ejecutar cuando el usuario diga explícitamente:
- "deployá a prod" / "mandá a Railway" / "ok deployá"

Comando (usar Railway CLI, **no** la GraphQL API):
```bash
cd buildfuture/
RAILWAY_TOKEN=<ver memoria del proyecto> railway up --service 4ff0cd5e-e9b6-4b36-8a71-9e165c4ef959 --detach
```

Verificar con `curl https://api-production-7ddd6.up.railway.app/health` — debe devolver la versión nueva.

---

## CI automático (GitHub Actions)

En cada PR se ejecutan:

**Backend** (`buildfuture` repo):
- `ruff check` + `ruff format --check` — lint y formato
- `bandit -r backend/app` — seguridad
- Import check — no imports rotos

**Frontend** (`buildfuture-frontend` repo):
- `tsc --noEmit` — tipos TypeScript
- `eslint` — lint
- `npm run build` — build completo de Next.js

Un PR no debería mergearse si alguno de estos falla.

---

## Code review por Claude

Cuando el usuario pide "revisá el PR #N":
1. `gh pr view N --json files,diff` — leer el diff completo
2. Analizar: bugs, lógica, breaking changes, seguridad
3. `gh pr comment N --body "..."` — postear el review en GitHub

---

## Testeado localmente antes de PR

Antes de abrir un PR, verificar que corre localmente:
- Backend: `uvicorn app.main:app --reload` sin errores de startup
- Frontend: `npm run dev` sin errores de compilación

---

## Contexto del proyecto

Ver `docs/PRODUCTO.md` para features implementadas y pendientes.
Ver `docs/BITACORA.md` para historial de sesiones.
Backend en Railway, frontend en Vercel. Auth via Supabase JWT ES256.
