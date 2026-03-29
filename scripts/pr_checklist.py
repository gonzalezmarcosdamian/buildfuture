"""
PR Checklist — verifica reglas básicas de calidad sin LLM.
Corre en GitHub Actions, escribe pr_checklist_output.md.
"""

import os
import subprocess
import sys
from pathlib import Path

BASE_SHA = os.environ["BASE_SHA"]
HEAD_SHA = os.environ["HEAD_SHA"]


def get_changed_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", BASE_SHA, HEAD_SHA],
        capture_output=True, text=True, check=True
    )
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def check(label: str, passed: bool, detail: str = "") -> dict:
    return {"label": label, "passed": passed, "detail": detail}


def run_checks(changed: list[str]) -> list[dict]:
    results = []

    # 1. Tests cuando se tocan services o agents
    core_changed = any(
        f.startswith("backend/app/services/") or f.startswith("backend/app/agents/")
        for f in changed
    )
    test_changed = any(f.startswith("backend/tests/") for f in changed)
    if core_changed:
        results.append(check(
            "Tests incluidos para cambios en services/agents",
            test_changed,
            "Se modificó `services/` o `agents/` sin cambios en `tests/`" if not test_changed else ""
        ))

    # 2. CHANGELOG actualizado
    changelog_changed = "CHANGELOG.md" in changed
    results.append(check(
        "CHANGELOG.md actualizado",
        changelog_changed,
        "Todo PR debe tener una entrada en CHANGELOG.md" if not changelog_changed else ""
    ))

    # 3. CONTEXT.md si se cambia arquitectura
    arch_changed = any(
        f.startswith("backend/app/models/") or
        f.startswith("backend/app/services/") or
        f.startswith("frontend/app/")
        for f in changed
    )
    context_changed = "CONTEXT.md" in changed
    if arch_changed and not context_changed:
        results.append(check(
            "CONTEXT.md refleja los cambios",
            False,
            "Se modificaron modelos, services o rutas — ¿CONTEXT.md está actualizado?"
        ))
    elif arch_changed:
        results.append(check("CONTEXT.md refleja los cambios", True))

    # 4. Sin archivos .env commiteados
    env_files = [f for f in changed if ".env" in f and not f.endswith(".example")]
    results.append(check(
        "Sin archivos .env en el PR",
        len(env_files) == 0,
        f"Archivos problemáticos: {env_files}" if env_files else ""
    ))

    # 5. Sin credenciales hardcodeadas (pattern básico)
    suspicious = []
    for filepath in changed:
        if not Path(filepath).exists():
            continue
        content = Path(filepath).read_text(errors="ignore")
        for pattern in ["password=", "api_key=", "secret=", "Bearer sk-"]:
            if pattern.lower() in content.lower():
                suspicious.append(filepath)
                break
    results.append(check(
        "Sin credenciales hardcodeadas detectadas",
        len(suspicious) == 0,
        f"Revisar: {suspicious}" if suspicious else ""
    ))

    return results


def render_markdown(checks: list[dict], changed: list[str]) -> str:
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)
    all_ok = passed == total

    header = "## 🤖 Vibe Coding Supervisor — Checklist\n\n"
    summary = f"**{passed}/{total} checks pasados**\n\n" if not all_ok else "**✅ Todo OK — listo para review de Claude**\n\n"

    rows = ""
    for c in checks:
        icon = "✅" if c["passed"] else "❌"
        detail = f" — `{c['detail']}`" if c["detail"] else ""
        rows += f"- {icon} {c['label']}{detail}\n"

    files_section = "\n<details><summary>Archivos modificados</summary>\n\n"
    files_section += "\n".join(f"- `{f}`" for f in changed[:30])
    if len(changed) > 30:
        files_section += f"\n- _(y {len(changed) - 30} más)_"
    files_section += "\n</details>\n"

    return header + summary + rows + files_section


def main():
    changed = get_changed_files()
    checks = run_checks(changed)
    output = render_markdown(checks, changed)

    Path("pr_checklist_output.md").write_text(output)
    print(output)

    # Falla el job si hay checks críticos sin pasar
    critical_failed = [c for c in checks if not c["passed"] and "env" in c["label"].lower()]
    if critical_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
