"""
PR Review con Claude — análisis profundo del diff.
Corre en GitHub Actions, escribe pr_review_output.md.
"""

import os
import subprocess
from pathlib import Path
import anthropic

BASE_SHA = os.environ["BASE_SHA"]
HEAD_SHA = os.environ["HEAD_SHA"]
PR_TITLE = os.environ.get("PR_TITLE", "")
PR_BODY = os.environ.get("PR_BODY", "")

# Archivos a excluir del diff (ruido)
EXCLUDE_PATTERNS = [
    "package-lock.json", "*.lock", "*.min.js",
    "node_modules/", "__pycache__/", "dist/", ".next/"
]

MAX_DIFF_CHARS = 12_000  # Límite para no exceder el context window


def get_diff() -> str:
    result = subprocess.run(
        ["git", "diff", BASE_SHA, HEAD_SHA, "--", ".", *[f":!{p}" for p in EXCLUDE_PATTERNS]],
        capture_output=True, text=True, check=True
    )
    diff = result.stdout
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... [diff truncado por longitud]"
    return diff


def get_context() -> str:
    context_path = Path("CONTEXT.md")
    if context_path.exists():
        content = context_path.read_text()
        return content[:3000]  # Solo el inicio es suficiente para el review
    return ""


SYSTEM_PROMPT = """Sos el Tech Lead de BuildFuture — una app de libertad financiera personal para Argentina.
Tu rol es revisar Pull Requests desde la perspectiva de un senior engineer con foco en:

1. **Seguridad**: credenciales, encryption, RLS, inputs del usuario
2. **Correctitud**: lógica del freedom calculator, integraciones con brokers/exchanges
3. **Calidad**: legibilidad, naming, duplicación innecesaria
4. **Documentación**: ¿el código es auto-explicativo? ¿falta algo en LEARNINGS o CONTEXT?
5. **Vibe coding**: ¿Claude introdujo algo que no fue pedido? ¿hay over-engineering?

Respondé en español. Sé directo y concreto — señalá líneas específicas si es relevante.
Formato: usa ✅ para lo bueno, ⚠️ para sugerencias, ❌ para problemas que deben corregirse antes del merge."""


def run_review(diff: str, context: str) -> str:
    client = anthropic.Anthropic()

    user_message = f"""**PR:** {PR_TITLE}
**Descripción:** {PR_BODY or "_(sin descripción)_"}

**Contexto del proyecto (extracto):**
```
{context}
```

**Diff:**
```diff
{diff}
```

Revisá este PR y dá tu análisis."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    return message.content[0].text


def main():
    diff = get_diff()
    context = get_context()

    if not diff.strip():
        output = "## 🤖 Claude Review\n\nNo hay cambios de código para revisar."
    else:
        review = run_review(diff, context)
        output = f"## 🤖 Claude Review — Tech Lead\n\n{review}"

    Path("pr_review_output.md").write_text(output)
    print(output)


if __name__ == "__main__":
    main()
