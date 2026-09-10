"""
core/tool_registry.py
=====================
Registro declarativo y agnóstico de herramientas (@tool) para el agente.
Permite registrar funciones con metadata de seguridad y convertirlas
automáticamente a esquemas compatibles con Anthropic, OpenAI y Google Gemini.
"""

from __future__ import annotations
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDefinition:
    """Definición formal de una herramienta ejecutable por el agente."""
    name: str
    description: str
    func: Callable[..., Any]
    parameters: Dict[str, Any]
    requires_approval: bool = False

    def execute(self, **kwargs) -> Any:
        """Ejecuta la función vinculada con los argumentos proporcionados."""
        return self.func(**kwargs)


class ToolRegistry:
    """Catálogo central de herramientas registradas para los LLMs."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        """Registra una nueva definición de herramienta."""
        self._tools[tool_def.name] = tool_def

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Obtiene una herramienta por su identificador único."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Retorna la lista de todas las herramientas registradas."""
        return list(self._tools.values())

    def clear(self) -> None:
        """Limpia el catálogo (útil para pruebas unitarias)."""
        self._tools.clear()

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        """Exporta las herramientas en el formato estándar de OpenAI (tools)."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            })
        return schemas

    def to_anthropic_schemas(self) -> List[Dict[str, Any]]:
        """Exporta las herramientas en el formato requerido por Claude (Anthropic)."""
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            })
        return schemas

    def to_gemini_schemas(self) -> List[Dict[str, Any]]:
        """Exporta las herramientas en el formato esperado por Google Gemini."""
        function_declarations = []
        for tool in self._tools.values():
            function_declarations.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            })
        return function_declarations


# Instancia singleton del registro de herramientas
registry = ToolRegistry()


def tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    requires_approval: bool = False,
    parameters: Optional[Dict[str, Any]] = None,
):
    """
    Decorador declarativo para registrar funciones como herramientas de IA.
    
    Ejemplo:
        @tool(
            name="create_cube",
            description="Crea un cubo en la escena de Blender.",
            requires_approval=False,
            parameters={
                "type": "object",
                "properties": {
                    "size": {"type": "number", "description": "Tamaño del cubo en metros"}
                },
                "required": ["size"]
            }
        )
        def create_cube(size: float = 2.0):
            ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__.strip() if func.__doc__ else "Sin descripción")
        
        # Parámetros por defecto si no se especifican
        tool_params = parameters or {
            "type": "object",
            "properties": {},
            "required": []
        }

        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            func=func,
            parameters=tool_params,
            requires_approval=requires_approval
        )
        registry.register(tool_def)
        return func

    return decorator
