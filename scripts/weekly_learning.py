"""
Weekly Learning Agent — resume la semana y actualiza docs/LEARNINGS.md.
Corre cada domingo via GitHub Actions.
"""

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import anthropic

LEARNINGS_PATH = Path("docs/LEARNINGS.md")
CONTEXT_PATH = Path("CONTEXT.md")


def get_week_commits() -> str:
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--pretty=format:%h %s", "--no-merges"],
        capture_output=True, text=True, check=True
    )
    return result.stdout.strip() or "_(sin commits esta semana)_"


def get_changed_files_this_week() -> list[str]:
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--name-only", "--pretty=format:", "--no-merges"],
        capture_output=True, text=True, check=True
    )
    files = {f.strip() for f in result.stdout.splitlines() if f.strip()}
    return sorted(files)


def get_current_learnings() -> str:
    if LEARNINGS_PATH.exists():
        return LEARNINGS_PATH.read_text()[:2000]
    return ""


def get_context_summary() -> str:
    if CONTEXT_PATH.exists():
        return CONTEXT_PATH.read_text()[:1500]
    return ""


SYSTEM_PROMPT = """Sos el Learning Agent de BuildFuture — una app de libertad financiera personal para Argentina.
Tu rol es revisar la actividad de la semana y extraer aprendizajes concretos para el equipo.

Un buen aprendizaje tiene:
- Qué pasó (contexto técnico específico)
- Por qué importa
- Qué cambiaríamos o haríamos diferente

Evitá generalidades. Si los commits son de docs o setup, decilo.
Si no hay nada nuevo que aprender esta semana, decilo también — no inventes aprendizajes.

Respondé SOLO con las entradas nuevas para agregar a LEARNINGS.md en el formato establecido.
No incluyas el header del archivo ni el contenido existente. Solo las entradas nuevas, si las hay."""


def generate_learnings(commits: str, files: list[str], existing: str, context: str) -> str:
    client = anthropic.Anthropic()

    today = datetime.now().strftime("%Y-%m-%d")
    files_str = "\n".join(f"- {f}" for f in files[:40])

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"""**Semana:** {today}

**Commits de la semana:**
{commits}

**Archivos modificados:**
{files_str or "_(ninguno)_"}

**Contexto del proyecto:**
{context}

**Aprendizajes ya registrados (no repetir):**
{existing}

¿Qué aprendizajes concretos deja esta semana?"""
        }]
    )

    return message.content[0].text.strip()


def append_learnings(new_content: str) -> bool:
    """Agrega las nuevas entradas al archivo. Retorna True si hubo cambios."""
    if not new_content or "no hay" in new_content.lower()[:50]:
        print("No hay aprendizajes nuevos esta semana.")
        return False

    current = LEARNINGS_PATH.read_text() if LEARNINGS_PATH.exists() else "# LEARNINGS — BuildFuture\n\n"

    # Insertar después del header
    header_end = current.find("\n\n") + 2
    updated = current[:header_end] + new_content + "\n\n---\n\n" + current[header_end:]

    LEARNINGS_PATH.write_text(updated)
    print(f"LEARNINGS.md actualizado con:\n{new_content}")
    return True


def main():
    print("=== Weekly Learning Agent ===")

    commits = get_week_commits()
    files = get_changed_files_this_week()
    existing = get_current_learnings()
    context = get_context_summary()

    print(f"Commits encontrados:\n{commits}\n")
    print(f"Archivos modificados: {len(files)}")

    new_learnings = generate_learnings(commits, files, existing, context)
    append_learnings(new_learnings)


if __name__ == "__main__":
    main()
