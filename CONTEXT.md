# BuildFuture — Contexto del Proyecto

> Documentación viva. Prioridad 0. Todo lo que se itera se documenta.
> Este archivo es el contrato entre el equipo y Claude. Mantenerlo actualizado es más importante que cualquier otra doc.

---

## Concepto

**Freedom Bar** — una barra de progreso que muestra qué % de tus gastos mensuales están cubiertos por el rendimiento de tu portafolio. No es solo renta pasiva: es dinámico, incluye apreciación de capital y rendimientos reales.

```
LIBERTAD FINANCIERA
████████░░░░░░░░░░░░  42%

Tu portafolio genera USD 420/mes
Tus gastos son        USD 1.000/mes
```

El portafolio **compite con tus gastos**. Cuando la barra llega al 100%, sos financieramente libre.

**Visión a futuro:** Plataforma multi-usuario. Cualquier persona con cuenta en una ALYC argentina o exchange crypto puede conectar su portafolio y trackear su libertad financiera.

---

## Usuarios

### Usuario inicial (Marcos)
- PM senior fintech (Ualá — Category Lead Wealth)
- Conocimiento financiero alto: FCI, CEDEARs, dólar MEP, bonos, letras, crypto
- Ahorro mensual: USD 1.000–1.500
- Estado actual: 100% líquido
- Cuentas: IOL, Nexo, Bitso

### Visión multi-usuario
- Amigos, clientes, cualquier persona con cuenta en ALYC argentina o exchange crypto
- Sin conocimiento financiero avanzado requerido
- La app interpreta, simplifica y proyecta

---

## Milestones de Libertad

| Milestone | Cobertura | Capital requerido (~5% anual) |
|---|---|---|
| M1 | 25% | ~USD 120.000 |
| M2 | 50% | ~USD 240.000 |
| M3 | 75% | ~USD 360.000 |
| M4 — Libertad total | 100% | ~USD 480.000 |

---

## Stack Técnico

### Frontend
- **Framework:** Next.js 14 (App Router)
- **Estilos:** Tailwind CSS + shadcn/ui
- **Charts:** Recharts
- **Estado global:** Zustand
- **Data fetching:** TanStack Query
- **Forms:** React Hook Form + Zod
- **Auth:** Supabase Auth (SDK `@supabase/auth-helpers-nextjs`)

### Backend
- **Framework:** FastAPI (Python)
- **Scheduler:** APScheduler (in-process)
- **HTTP client:** httpx (async)
- **ORM:** SQLAlchemy 2.0 async + asyncpg
- **Auth middleware:** JWT validation (Supabase tokens)
- **Encryption:** Python `cryptography` (Fernet/AES-256)

### Base de datos
- **DB:** PostgreSQL via Supabase
- **Migrations:** Alembic
- **RLS:** Supabase Row Level Security — cada usuario solo ve sus datos
- **Auth:** Supabase Auth (email/password + magic link + Google OAuth)

### Hosting
- **Railway.app** — frontend + backend, auto-deploy en `git push main`
- **DB:** Supabase
- **Secrets:** Railway environment variables (nunca en código)

---

## Autenticación y Sesiones

**Supabase Auth** — la elección natural dado que ya usamos Supabase como DB.

### Flujos soportados
- Email + password
- Magic link (passwordless)
- Google OAuth (futuro)

### Flujo de sesión
```
1. Usuario se registra / loguea → Supabase emite JWT
2. Frontend almacena token en cookie httpOnly (manejado por @supabase/auth-helpers)
3. Cada request al backend incluye JWT en Authorization header
4. FastAPI middleware valida el JWT contra Supabase public key
5. user_id se extrae del JWT — nunca del body del request
```

### Row Level Security (Supabase)
Todas las tablas tienen políticas RLS:
```sql
-- Ejemplo: un usuario solo lee sus propias posiciones
CREATE POLICY "users_own_positions" ON positions
  FOR ALL USING (auth.uid() = user_id);
```

---

## Seguridad de Credenciales de Brokers

Este es el punto más crítico del sistema. Los usuarios nos confían sus credenciales de ALYC y exchange.

### Modelo: Envelope Encryption (AES-256)

```
┌─────────────────────────────────────────────┐
│  MASTER KEK (Key Encryption Key)             │
│  → Railway environment variable              │
│  → Nunca en DB, nunca en código              │
└──────────────────┬──────────────────────────┘
                   │ cifra/descifra
┌──────────────────▼──────────────────────────┐
│  DEK por usuario (Data Encryption Key)       │
│  → Generado aleatoriamente al registrarse    │
│  → Almacenado cifrado en DB (tabla user_keys)│
└──────────────────┬──────────────────────────┘
                   │ cifra/descifra
┌──────────────────▼──────────────────────────┐
│  Credenciales del broker                     │
│  → username, password, api_key, api_secret   │
│  → Almacenados cifrados en DB                │
└─────────────────────────────────────────────┘
```

**¿Por qué este modelo?**
- Si la DB se filtra: el atacante tiene credenciales cifradas + DEKs cifradas → inútil sin el KEK
- Si el KEK se compromete: se rota el KEK y se re-cifran todos los DEKs (sin re-pedir credenciales a los usuarios)
- Los agentes background pueden operar sin intervención del usuario

### Flujo cuando el usuario conecta una cuenta
```
1. Usuario ingresa credenciales en el frontend (formulario)
2. Request HTTPS al backend (credenciales en body, nunca en URL ni headers)
3. Backend: carga DEK del usuario (descifra con KEK)
4. Backend: cifra credenciales con DEK → guarda en DB
5. Backend: testea conexión con broker → confirma o rechaza
6. Credenciales nunca se loguean, nunca se devuelven al frontend
```

### Reglas absolutas
- Nunca loguear tokens, passwords, api_keys
- Nunca devolver credenciales al frontend (ni cifradas)
- Nunca almacenar credenciales en variables de entorno del usuario
- Siempre HTTPS para cualquier request con credenciales
- Rotar el KEK cada 90 días (Railway secret rotation)

---

## Modelo Multi-ALYC

### Abstracción del broker (Protocol)

```python
# services/brokers/base.py
class BrokerClient(Protocol):
    broker_name: str

    async def authenticate(self) -> None: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_cash_balance(self) -> dict[str, Decimal]: ...
    async def get_operations(self, from_date: date) -> list[Operation]: ...

# Implementaciones
class IOLClient(BrokerClient):      # InvertirOnline
class BalanzClient(BrokerClient):   # Balanz (futuro)
class CocosClient(BrokerClient):    # Cocos Capital (futuro)
class PrimaryClient(BrokerClient):  # Primary/BYMA (futuro)
```

### ALYCs planificadas

| ALYC | Estado | Auth | Notas |
|---|---|---|---|
| IOL (InvertirOnline) | **v1** | OAuth2 password grant | API pública documentada, lib PyPI disponible |
| Balanz | v2 | API key | API privada, requiere acuerdo |
| Cocos Capital | v2 | API key | API moderna, developer-friendly |
| Primary/BYMA | v3 | OAuth2 | Mercado directo, más complejo |

---

## Modelo Multi-Crypto

### Abstracción del exchange (Protocol)

```python
# services/crypto/base.py
class CryptoClient(Protocol):
    exchange_name: str

    async def get_balances(self) -> dict[str, Decimal]: ...
    async def get_transactions(self, from_date: date) -> list[Transaction]: ...
    async def get_yield_earned(self) -> dict[str, Decimal]: ...  # Para Nexo

# Implementaciones
class NexoClient(CryptoClient):    # Nexo — yield en crypto
class BitsoClient(CryptoClient):   # Bitso — HMAC auth
class BinanceClient(CryptoClient): # Binance (futuro)
class LetsbitClient(CryptoClient): # Letsbit AR (futuro)
```

### Exchanges planificados

| Exchange | Estado | Auth | Notas |
|---|---|---|---|
| Nexo | **v1** | API key + secret | Yield tracking incluido |
| Bitso | **v1** | HMAC (key + secret) | Opera ARS ↔ crypto |
| Binance | v2 | API key + secret | Mayor volumen global |
| Letsbit | v3 | API key | Exchange AR con P2P |

---

## Arquitectura de Agentes

| Agente | Trigger | Función |
|---|---|---|
| **PortfolioSyncAgent** | Lunes 9am ART (por usuario) | Pull todas las fuentes → snapshot → recalcula freedom score → detecta milestones |
| **BudgetReviewAgent** | 1ro de mes 8am ART | Actualiza presupuesto por drift de FX |
| **MarketContextAgent** | Domingo 7pm ART | Brief macro con Claude (compartido para todos los usuarios) |
| **AdvisorAgent** | Real-time (chat) | Streaming con contexto del usuario específico |

Los agentes corren **por usuario**: el scheduler itera sobre todos los usuarios activos.

---

## Estructura del Proyecto

```
buildfuture/
├── frontend/                    # Next.js 14
│   ├── app/
│   │   ├── (auth)/
│   │   │   ├── login/
│   │   │   └── register/
│   │   ├── (app)/               # Rutas protegidas
│   │   │   ├── dashboard/       # Freedom Bar + resumen
│   │   │   ├── portfolio/       # Posiciones consolidadas
│   │   │   ├── budget/          # Categorías por porcentaje
│   │   │   ├── goals/           # Milestones + proyecciones
│   │   │   ├── advisor/         # Chat con Claude
│   │   │   └── settings/
│   │   │       └── integrations/ # Conectar IOL, Nexo, etc.
│   ├── components/
│   │   ├── ui/                  # shadcn/ui primitives
│   │   ├── freedom-bar/
│   │   ├── portfolio/
│   │   ├── budget/
│   │   ├── goals/
│   │   ├── advisor/
│   │   └── integrations/        # Cards por broker/exchange
│   ├── hooks/
│   ├── lib/
│   │   ├── api.ts
│   │   ├── supabase.ts          # Supabase client
│   │   └── formatters.ts
│   └── types/
│
├── backend/                     # FastAPI
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── auth.py              # JWT middleware
│   │   ├── encryption.py        # Envelope encryption (KEK + DEK)
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── user_key.py      # DEK cifrado por usuario
│   │   │   ├── integration.py   # Credenciales cifradas por broker
│   │   │   ├── portfolio.py
│   │   │   ├── position.py
│   │   │   ├── budget.py
│   │   │   ├── goal.py
│   │   │   └── snapshot.py
│   │   ├── schemas/
│   │   ├── routers/
│   │   │   ├── integrations.py  # CRUD de conexiones de brokers
│   │   │   ├── portfolio.py
│   │   │   ├── budget.py
│   │   │   ├── goals.py
│   │   │   ├── sync.py
│   │   │   └── advisor.py
│   │   ├── services/
│   │   │   ├── brokers/
│   │   │   │   ├── base.py      # BrokerClient Protocol
│   │   │   │   ├── iol.py
│   │   │   │   └── balanz.py    # (futuro)
│   │   │   ├── crypto/
│   │   │   │   ├── base.py      # CryptoClient Protocol
│   │   │   │   ├── nexo.py
│   │   │   │   └── bitso.py
│   │   │   ├── fx_service.py
│   │   │   ├── freedom_calculator.py
│   │   │   ├── projection_engine.py
│   │   │   └── claude_service.py
│   │   └── agents/
│   │       ├── scheduler.py
│   │       ├── portfolio_sync_agent.py
│   │       ├── budget_review_agent.py
│   │       └── market_context_agent.py
│   ├── migrations/
│   └── tests/
│       ├── services/
│       ├── agents/
│       └── routers/
│
├── docs/
│   ├── ARCHITECTURE.md          # ADRs
│   ├── INTEGRATIONS.md          # Guías de integración
│   ├── AGENTS.md                # Documentación de agentes
│   └── LEARNINGS.md             # Aprendizajes iterativos
│
├── .github/
│   └── workflows/
│       └── ci.yml               # Tests + lint en cada PR
│
├── CHANGELOG.md
├── CONTEXT.md                   # Este archivo
├── .gitignore
├── railway.toml
└── README.md
```

---

## Modelos de Datos Clave

### Seguridad

```python
class UserKey(Base):
    # DEK cifrado con el KEK maestro
    user_id: UUID
    encrypted_dek: bytes          # Fernet(KEK).encrypt(dek_raw)
    created_at: datetime
    rotated_at: datetime

class Integration(Base):
    # Credenciales cifradas con el DEK del usuario
    user_id: UUID
    provider: Enum                # IOL | BALANZ | COCOS | NEXO | BITSO | BINANCE
    provider_type: Enum           # ALYC | CRYPTO
    encrypted_credentials: bytes  # Fernet(DEK).encrypt(json_credentials)
    is_active: bool
    last_synced_at: datetime
    last_error: str               # Para mostrar en UI si falla
```

### Core

```python
class Position(Base):
    user_id: UUID
    integration_id: UUID          # Qué cuenta/broker
    ticker: str
    asset_type: Enum              # CEDEAR | BOND | FCI | LETRA | STOCK | CRYPTO | CASH
    source: Enum                  # IOL | NEXO | BITSO | BALANZ | ...
    quantity: Decimal
    avg_purchase_price_usd: Decimal
    current_price_usd: Decimal
    current_value_usd: Decimal
    current_value_ars: Decimal
    performance_pct: Decimal
    snapshot_date: date

class FreedomScore(Base):
    user_id: UUID
    calculated_at: datetime
    portfolio_total_usd: Decimal
    portfolio_monthly_return_usd: Decimal
    monthly_expenses_usd: Decimal
    freedom_pct: Decimal          # EL NÚMERO CENTRAL
    fx_rate_used: Decimal
```

---

## Ingeniería y Buenas Prácticas

### Versionado
- **SemVer:** `MAJOR.MINOR.PATCH`
- **Git flow:** `main` (prod) → `develop` → `feature/nombre`, `fix/nombre`
- **Commits:** Conventional Commits — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Tags en cada release:** `v0.1.0`, `v0.2.0`, etc.
- **PRs:** una feature por PR, con descripción de qué y por qué

### Testing
- **Backend:** pytest + pytest-asyncio
- **Integration tests:** IOL sandbox para el cliente IOL
- **Frontend:** Vitest + React Testing Library
- **Cobertura mínima:** 80% en `services/` y `agents/`
- **Regla:** ningún feature merge sin tests

### CI/CD
```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  backend-test:
    - pip install -r requirements.txt
    - pytest tests/ --cov=app
    - black --check . && flake8
  frontend-test:
    - npm ci && npm run type-check
    - npm run lint && npm run test
```
Railway auto-deploya en merge a `main`.

### Seguridad de código
- Nunca hardcodear secrets (banear con `detect-secrets` pre-commit)
- `.gitignore` incluye: `.env`, `*.key`, `credentials/`, `__pycache__`
- Dependabot habilitado en GitHub para alertas de vulnerabilidades
- HTTPS obligatorio — Railway lo provee por defecto

### Code Quality
- **Python:** black + flake8 + mypy (strict)
- **TypeScript:** ESLint + Prettier + strict mode
- **Pre-commit:** detect-secrets + black + eslint

---

## Documentación — Prioridad 0

### Qué documentar siempre
| Evento | Dónde |
|---|---|
| Decisión de arquitectura | `docs/ARCHITECTURE.md` como ADR |
| Nueva integración (broker/exchange) | `docs/INTEGRATIONS.md` |
| Nuevo agente o cambio de comportamiento | `docs/AGENTS.md` |
| Cualquier release | `CHANGELOG.md` |
| Error raro resuelto / decisión de diseño / lección aprendida | `docs/LEARNINGS.md` |

### Formato ADR
```markdown
## ADR-00N: Título
**Fecha:** YYYY-MM-DD  **Estado:** Accepted
**Contexto:** Por qué surgió.
**Decisión:** Qué decidimos.
**Consecuencias:** Trade-offs.
```

---

## Vibe Coding — Guía Completa

### Los 12 principios

**1. CONTEXT.md es el contrato.**
Antes de pedirle algo a Claude, este archivo debe reflejar el estado actual. Claude trabaja dentro de lo que describe. Si está desactualizado, el output va a divergir.

**2. Scope acotado, siempre.**
"Implementá el IOL client con auth y refresh de token, con tests" — no "armá el backend". Cuanto más acotado, más preciso y reutilizable el output.

**3. Tests + docs en el mismo prompt.**
"Implementá X, incluí tests y actualizá CHANGELOG y LEARNINGS." Si los separás, nunca llegan.

**4. Leé el diff completo antes de aceptar.**
Claude puede introducir cambios no pedidos, especialmente en archivos críticos. Revisá siempre `freedom_calculator.py`, `encryption.py` y los modelos de DB.

**5. Rubber duck antes de pedir código.**
Describí en texto plano lo que querés construir. Si no podés explicarlo en un párrafo, el scope no está claro. Clarificá antes de codear.

**6. Plan Mode para cambios grandes.**
Antes de refactors, cambios de modelo de datos o nuevas integraciones, usá `/plan` o pedile a Claude que describa el approach antes de ejecutarlo. Aprobá el plan, luego ejecutá.

**7. Commit después de cada iteración funcional.**
No acumulés cambios. Commits pequeños y frecuentes = fácil rollback. La regla: si el feature funciona, se commitea.

**8. Branch por feature, siempre.**
Aunque seas el único developer. `feature/iol-client`, `feature/freedom-bar`. Protege `main`.

**9. "Explicá este código" antes de modificarlo.**
Si vas a pedirle a Claude que modifique código existente, pedile primero que lo explique. Evita que rompa algo que no entendía.

**10. El modelo de datos es sagrado.**
Antes de cualquier cambio de schema: migración Alembic + ADR en `docs/ARCHITECTURE.md`. Nunca cambiar el schema sin migración.

**11. Errors de integración → LEARNINGS.md.**
IOL, Nexo y Bitso van a fallar de maneras inesperadas (rate limits, tokens expirados, schemas que cambian). Documentá cada error raro con su solución.

**12. La seguridad no se negocia en favor de velocidad.**
Si Claude propone guardar credenciales en texto plano "por ahora para simplificar" — rechazalo. El modelo de encryption se implementa desde el día 1.

### Anti-patrones a evitar
- ❌ "Hacé todo el proyecto en un solo prompt"
- ❌ Aceptar código sin leerlo porque "Claude es bueno"
- ❌ Commitear a `main` directamente
- ❌ Saltear tests "porque es solo un prototipo"
- ❌ Pedir features nuevos con bugs abiertos en el backlog
- ❌ Dejar CONTEXT.md desactualizado más de una sesión

---

## CHANGELOG

Ver [CHANGELOG.md](CHANGELOG.md)

## Aprendizajes

Ver [docs/LEARNINGS.md](docs/LEARNINGS.md)

## Arquitectura (ADRs)

Ver [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

*Última actualización: 2026-03-29*
