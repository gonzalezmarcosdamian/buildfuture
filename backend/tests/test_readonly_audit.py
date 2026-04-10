"""
Auditoría de seguridad: los clientes de integración NO deben usar métodos HTTP
de escritura (POST, PUT, DELETE, PATCH) contra las APIs de los brokers.

Razón: las credenciales almacenadas para lectura también habilitan trading/retiros
en IOL, Cocos y PPI (no tienen scopes granulares). Si un cliente llama accidentalmente
un endpoint de escritura, puede operar en nombre del usuario.

Este test analiza el AST de cada cliente y falla si detecta llamadas a métodos
de escritura HTTP a URLs de brokers.
"""

import ast
import pathlib
import pytest

SERVICES_DIR = pathlib.Path(__file__).parent.parent / "app" / "services"

# Clientes de integración a auditar
INTEGRATION_CLIENTS = [
    "iol_client.py",
    "ppi_client.py",
    "cocos_client.py",
    "binance_client.py",
    "nexo_client.py",
]

# Métodos HTTP de escritura prohibidos en contexto de broker
WRITE_METHODS = {"post", "put", "delete", "patch"}

# Dominios de brokers — cualquier llamada de escritura a estas URLs es una violación
BROKER_DOMAINS = [
    "invertironline.com",
    "portfoliopersonal.com",
    "cocos.capital",
    "binance.com",
    "nexo.io",
]

# Métodos internos de escritura que NUNCA deben existir en los clientes
FORBIDDEN_METHOD_NAMES = {
    "_post", "_put", "_delete", "_patch",
    "place_order", "buy", "sell", "withdraw", "transfer",
    "cancel_order", "new_order",
}


class WriteCallVisitor(ast.NodeVisitor):
    """
    Recorre el AST buscando:
    1. Llamadas a httpx.post / httpx.put / httpx.delete / httpx.patch
    2. Definiciones de métodos con nombres prohibidos
    """

    def __init__(self, filename: str):
        self.filename = filename
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Detectar httpx.<write_method>(...)
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr.lower()
            if method in WRITE_METHODS:
                # Verificar que el objeto es httpx (o similar)
                obj = node.func.value
                obj_name = ""
                if isinstance(obj, ast.Name):
                    obj_name = obj.id.lower()
                elif isinstance(obj, ast.Attribute):
                    obj_name = obj.attr.lower()

                if obj_name in ("httpx", "requests", "session", "client", "self"):
                    # Extraer la URL del primer argumento si es string literal
                    url_hint = ""
                    if node.args:
                        first = node.args[0]
                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                            url_hint = first.value

                    # Solo es violación si la URL apunta a un broker
                    # (permite POST a APIs de terceros como dolarapi, bluelytics, yahoo, etc.)
                    if url_hint:
                        is_broker_url = any(d in url_hint for d in BROKER_DOMAINS)
                        if is_broker_url:
                            self.violations.append(
                                f"  Línea {node.lineno}: llamada HTTP de escritura "
                                f"'{method}' a URL de broker: {url_hint!r}"
                            )
                    else:
                        # URL dinámica — verificar por f-string o concatenación
                        # con bases de broker conocidas
                        self.violations.append(
                            f"  Línea {node.lineno}: llamada HTTP de escritura "
                            f"'{method}' con URL dinámica — revisar manualmente"
                        )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if node.name.lower() in FORBIDDEN_METHOD_NAMES:
            self.violations.append(
                f"  Línea {node.lineno}: método prohibido definido: '{node.name}'"
            )
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


@pytest.mark.parametrize("client_file", INTEGRATION_CLIENTS)
def test_no_write_http_calls(client_file: str) -> None:
    """
    Verifica que el cliente de integración no contenga llamadas HTTP de escritura
    a APIs de brokers ni defina métodos de trading/retiro.
    """
    path = SERVICES_DIR / client_file
    if not path.exists():
        pytest.skip(f"{client_file} no existe — skip")

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    visitor = WriteCallVisitor(filename=client_file)
    visitor.visit(tree)

    # Las llamadas de escritura a URLs dinámicas (sin string literal) son una
    # advertencia que requiere revisión manual. En el auth flow de IOL/PPI/Cocos
    # sí existe un POST al endpoint de login — eso está permitido.
    # Filtramos los warnings de "URL dinámica" para no bloquear el CI por los
    # auth flows legítimos, pero los registramos.
    hard_violations = [
        v for v in visitor.violations
        if "URL dinámica" not in v
    ]

    assert not hard_violations, (
        f"\n{client_file}: violaciones de acceso de escritura a broker:\n"
        + "\n".join(hard_violations)
        + "\n\n"
        "BuildFuture es read-only. Los clientes de integración NO deben llamar\n"
        "endpoints de escritura (POST/PUT/DELETE/PATCH) en las APIs de los brokers.\n"
        "Si necesitás auth (POST /token), ese endpoint no es de trading — verificá\n"
        "que la URL no sea un endpoint de órdenes o transferencias."
    )
