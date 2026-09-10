"""
blender_integration/tools/run_script.py
=======================================
Herramienta de ejecución de scripts de Python dinámicos en Blender.
Protegida con requires_approval=True y validada contra el Sandbox AST.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

try:
    import bpy
    import bmesh
    import mathutils
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

from core.security.sandbox import execute_sandboxed, validate_python_code
from core.tool_registry import tool

logger = logging.getLogger("BlenderAIAgent.RunScript")


@tool(
    name="run_python_script",
    description="Ejecuta un script de Python arbitrario en Blender. Usar solo cuando las herramientas específicas (mesh_ops, material_ops) no alcancen. REQUIERE APROBACIÓN DEL USUARIO.",
    requires_approval=True,
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Código fuente en Python a ejecutar. Debe usar únicamente bpy, bmesh, math, mathutils."
            }
        },
        "required": ["code"]
    }
)
def run_python_script(code: str) -> str:
    """Ejecuta el script bajo supervisión y validación de seguridad AST."""
    is_safe, error_msg = validate_python_code(code)
    if not is_safe:
        return f"Error de Seguridad: {error_msg}"

    if not BLENDER_AVAILABLE:
        return f"[MOCK] Script validado y ejecutado exitosamente:\n{code[:80]}..."

    globals_env: Dict[str, Any] = {
        "bpy": bpy,
        "bmesh": bmesh,
        "mathutils": mathutils,
        "__builtins__": __builtins__
    }

    try:
        execute_sandboxed(code, globals_dict=globals_env)
        return "Script de Python ejecutado correctamente en Blender."
    except Exception as e:
        logger.exception("Error durante la ejecución del script del agente: %s", str(e))
        return f"Error en tiempo de ejecución: {str(e)}"
