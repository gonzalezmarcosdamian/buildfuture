# Módulo Recomendados — Spec de referencia para Invest Advisor

> Removido del home en 2026-05-22 (commit b924660 frontend).
> Los componentes y endpoints siguen en el codebase — no se borraron.
> Esta doc preserva la lógica de negocio para cuando se construya el Invest Advisor.

---

## Por qué se quitó del home

El módulo de recomendados fue diseñado como una lista estática de "dónde invertir ahora"
basada en el comité de expertos (reglas hardcodeadas + señales de yield live).
Se reemplazará por un **Invest Advisor** conversacional/contextual que considera
el portafolio actual del usuario, sus metas y el contexto macro del momento.

---

## Arquitectura del módulo (estado al 2026-05-22)

### Frontend — componentes existentes

| Archivo | Descripción |
|---------|-------------|
| `components/recommendations/RecommendationList.tsx` | Componente principal. Dos secciones: "Renta" y "Capital". Cards con carousel horizontal. Modal de detalle educativo. |
| `components/recommendations/RecommendationCarousel.tsx` | Versión anterior (carousel simple). Deprecada, reemplazada por RecommendationList. |

### Backend — endpoints activos

| Endpoint | Descripción |
|----------|-------------|
| `GET /portfolio/recommendations/sections` | Devuelve `{ renta: Rec[], capital: Rec[], context_summary, generated_at }`. Es el que usaba RecommendationList. |
| `GET /portfolio/recommendations` | Versión anterior. Devuelve lista flat con `allocation_pct`. Usada por RecommendationCarousel. |

### Backend — servicios

| Servicio | Archivo | Descripción |
|----------|---------|-------------|
| `expert_committee.py` | `backend/app/services/expert_committee.py` | ~1400 líneas. Universo de instrumentos (`UNIVERSE`), scoring multi-agente, filtrado por perfil de riesgo y job (renta/capital). |
| `smart_recommendations.py` | `backend/app/services/smart_recommendations.py` | ~400 líneas. Capa de agregación y personalización. |
| `ai_recommendations.py` | `backend/app/services/ai_recommendations.py` | Wrapper Claude API para recomendaciones con IA. Se activa con `?use_ai=true`. |

---

## Lógica de negocio central

### Tipos de datos clave

```typescript
interface Rec {
  ticker: string;
  name: string;
  asset_type: string;          // "LETRA" | "CEDEAR" | "BOND" | "ON" | "FCI" | "CRYPTO" | "ETF"
  job: string;                 // "renta" | "capital" | "ambos"
  recommended_for: string[];   // ["conservador", "moderado", "agresivo"]
  logo_url: string;
  rationale: string;           // "¿Por qué este instrumento?"
  why_now: string;             // "¿Por qué ahora?"
  annual_yield_pct: number;
  yield_range_low?: number;    // Para instrumentos de capital (apreciación estimada)
  yield_range_high?: number;
  yield_label?: string;        // "retorno anual estimado USD"
  risk_level: string;          // "bajo" | "medio" | "alto"
  currency: string;            // "ARS" | "USD"
  amount_ars: number;          // Monto sugerido en ARS
  amount_usd: number;          // Monto sugerido en USD
  monthly_return_usd: number;  // Renta mensual estimada si es job=renta
  score: number;               // Score del comité (0-1)
  agents_agreed?: AgentSignal[]; // Señales de los agentes del comité
}
```

### Clasificación renta / capital

```
RENTA  → LETRA, FCI, BOND, ON  → generan flujo periódico en ARS o USD
CAPITAL → CEDEAR, ETF, CRYPTO   → crecimiento dolarizado, sin flujo
AMBOS  → BOND/ON que pagan cupón Y tienen apreciación de precio
```

### Secciones de la respuesta

```json
{
  "renta": [...],    // Top N instrumentos de renta ordenados por score
  "capital": [...],  // Top N instrumentos de capital ordenados por score
  "context_summary": "Texto libre con el contexto macro del momento",
  "generated_at": "2026-05-22T..."
}
```

### Textos educativos del modal (preservar para el Advisor)

```
¿Qué es cada tipo?
  LETRA:  "Letra del Tesoro Nacional. Deuda de corto plazo en pesos..."
  FCI:    "Fondo Común de Inversión. Vehículo colectivo de renta fija..."
  CEDEAR: "Certificado de Depósito Argentino. Acciones extranjeras en pesos..."
  ETF:    "Exchange Traded Fund cotizado como CEDEAR. Replica un índice..."
  BOND:   "Bono soberano argentino. El Estado emite deuda..."
  ON:     "Obligación Negociable. Deuda de empresas líderes en USD..."

¿Qué riesgo tiene?
  bajo:  "Riesgo controlado. Probabilidad baja de perder capital..."
  medio: "Riesgo moderado. Puede haber volatilidad de precio..."
  alto:  "Riesgo elevado. El precio puede oscilar significativamente..."
```

### UI/UX que funcionaba bien (mantener en Advisor)

- **Cards horizontales con carousel** — `w-[58vw] max-w-[210px]`, `snap-x snap-mandatory`
- **Modal bottom sheet** — `fixed inset-0 z-[999] items-end`, `rounded-t-2xl`
- **Yield range** para capital: `+15% – +35%` en lugar de un número puntual (más honesto)
- **Perfil pills**: `conservador` (verde), `moderado` (amarillo), `agresivo` (rojo)
- **Refresh manual** con icono `RefreshCw` animado
- **Contexto educativo fijo**: "Renta sube tu barra de libertad · Capital sube tu patrimonio"

### Parámetros del endpoint

```
GET /portfolio/recommendations/sections
  ?capital_ars=500000    # Capacidad de inversión en ARS (default: savingsARS o 500000)

GET /portfolio/recommendations
  ?capital_ars=500000
  ?risk_profile=moderado
  ?use_ai=true           # Usa Claude API (lento, más personalizado)
  ?force_refresh=true    # Ignora cache
```

---

## Qué necesita el Invest Advisor para reemplazarlo

1. **Contexto del usuario** — portafolio actual + metas + risk_profile + budget
2. **Contexto macro** — señales del mercado (MEP, tasa LECAP, bonos, etc.)
3. **Recomendación personalizada** — no "qué es bueno en general" sino "qué hace falta en tu portafolio"
4. **Modo conversacional** — el usuario puede preguntar "¿por qué no ON?" o "¿cuánto pongo en CEDEAR?"
5. **Reutilizar** `expert_committee.UNIVERSE` como base de instrumentos disponibles
6. **Reutilizar** los textos educativos del modal (ver arriba)
7. **Reutilizar** la UI de cards/carousel si aplica, o nueva UI tipo chat

---

## Archivos del codebase a revisar cuando se construya

```
Backend:
  backend/app/services/expert_committee.py      ← universo + scoring
  backend/app/services/smart_recommendations.py ← agregación
  backend/app/services/ai_recommendations.py    ← Claude API wrapper
  backend/app/routers/portfolio.py              ← endpoints /recommendations y /recommendations/sections

Frontend:
  frontend/components/recommendations/RecommendationList.tsx    ← UI más reciente
  frontend/components/recommendations/RecommendationCarousel.tsx ← UI anterior
```
