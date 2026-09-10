"""
core/security/sandbox.py
========================
Analizador estático de código Python (AST Validator) y ejecutor seguro.
Impide la ejecución de scripts que intenten acceder al sistema de archivos,
abrir sockets de red o invocar subprocess/eval/exec en la máquina del usuario.
"""

from __future__ import annotations
import ast
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("BlenderAIAgent.Sandbox")

# Módulos explícitamente bloqueados por motivos de seguridad
DISALLOWED_MODULES: Set[str] = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "socket",
    "http",
    "urllib",
    "requests",
    "multiprocessing",
    "threading",
    "ctypes",
    "builtins",
    "importlib",
    "pty",
    "webbrowser",
    "pickle",
}

# Funciones y atributos potencialmente destructivos
DISALLOWED_CALLS: Set[str] = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "open",
}


class SecurityASTVisitor(ast.NodeVisitor):
    """Recorre el árbol de sintaxis abstracta (AST) detectando patrones inseguros."""

    def __init__(self):
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split('.')[0]
            if root_module in DISALLOWED_MODULES:
                self.violations.append(f"Importación prohibida del módulo '{alias.name}' (Línea {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_module = node.module.split('.')[0]
            if root_module in DISALLOWED_MODULES:
                self.violations.append(f"Importación prohibida desde el módulo '{node.module}' (Línea {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Detectar llamadas directas a funciones bloqueadas (ej. eval(), exec())
        if isinstance(node.func, ast.Name):
            if node.func.id in DISALLOWED_CALLS:
                self.violations.append(f"Llamada prohibida a la función del sistema '{node.func.id}()' (Línea {node.lineno})")
        
        # Detectar accesos a atributos peligrosos (ej. __subclasses__)
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in {"__subclasses__", "__bases__", "__globals__"}:
                self.violations.append(f"Acceso prohibido a introspección crítica '{node.func.attr}' (Línea {node.lineno})")
                
        self.generic_visit(node)


def validate_python_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Valida un script de Python mediante análisis estático de AST.
    Retorna (True, None) si el código es seguro, o (False, mensaje_error) si viola las reglas.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Error de sintaxis en el código generado: {e.msg} (Línea {e.lineno})"

    visitor = SecurityASTVisitor()
    visitor.visit(tree)

    if visitor.violations:
        error_msg = "Código rechazado por el Sandbox de Seguridad:\n - " + "\n - ".join(visitor.violations)
        logger.warning(error_msg)
        return False, error_msg

    return True, None


def execute_sandboxed(code: str, globals_dict: Optional[Dict[str, Any]] = None, locals_dict: Optional[Dict[str, Any]] = None) -> Any:
    """
    Valida y ejecuta un script de Python en un entorno controlado si pasa las verificaciones de AST.
    """
    is_safe, error_message = validate_python_code(code)
    if not is_safe:
        raise PermissionError(error_message)

    if globals_dict is None:
        globals_dict = {}
    if locals_dict is None:
        locals_dict = {}

    # Restringir __builtins__ para deshabilitar open/eval/exec en tiempo de ejecución
    safe_builtins = globals_dict.get("__builtins__", {})
    if isinstance(safe_builtins, dict):
        for blocked in DISALLOWED_CALLS:
            safe_builtins.pop(blocked, None)

    compiled_code = compile(code, "<agent_script>", "exec")
    return exec(compiled_code, globals_dict, locals_dict)
