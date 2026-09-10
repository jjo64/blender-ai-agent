"""
core/agent.py
=============
Bucle principal de razonamiento del Agente (ReAct Loop: Reason + Act).
Orquesta la obtención del contexto de la escena, la consulta al LLM Provider,
la compuerta de aprobación (AuthGate) y la ejecución de herramientas del ToolRegistry.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from .context_manager import ContextManager
    from .providers.base import (
        BaseProvider,
        ErrorType,
        LLMResponse,
        Message,
        ProviderException,
        StopReason,
        StreamChunk,
        ToolCall,
    )
    from .scene_inspector import SceneInspector, SceneSnapshot
    from .security.auth_gate import AuthGate
    from .tool_registry import ToolRegistry, registry as default_registry
except ImportError:
    from core.context_manager import ContextManager
    from core.providers.base import (
        BaseProvider,
        ErrorType,
        LLMResponse,
        Message,
        ProviderException,
        StopReason,
        StreamChunk,
        ToolCall,
    )
    from core.scene_inspector import SceneInspector, SceneSnapshot
    from core.security.auth_gate import AuthGate
    from core.tool_registry import ToolRegistry, registry as default_registry

logger = logging.getLogger("BlenderAIAgent.Agent")


@dataclass
class AgentResult:
    """Resultado final de una sesión de ejecución del agente."""
    success: bool
    content: str
    iterations: int = 0
    total_cost_usd: float = 0.0
    error_type: Optional[ErrorType] = None
    is_max_iterations: bool = False


class AgentLoop:
    """Máquina de estados y bucle de razonamiento autónomo."""

    def __init__(
        self,
        provider: BaseProvider,
        tool_registry: Optional[ToolRegistry] = None,
        auth_gate: Optional[AuthGate] = None,
        context_manager: Optional[ContextManager] = None,
        max_iterations: int = 10
    ):
        self.provider = provider
        self.tool_registry = tool_registry or default_registry
        self.auth_gate = auth_gate or AuthGate(auto_approve=False)
        self.context_manager = context_manager or ContextManager()
        self.max_iterations = max_iterations

    def _get_provider_tools_schema(self) -> List[Dict[str, Any]]:
        """Selecciona el formato de schema de herramientas correspondiente al proveedor."""
        provider_name = self.provider.__class__.__name__.lower()
        if "anthropic" in provider_name:
            return self.tool_registry.to_anthropic_schemas()
        elif "gemini" in provider_name:
            return self.tool_registry.to_gemini_schemas()
        else:
            return self.tool_registry.to_openai_schemas()

    def run(
        self,
        user_prompt: str,
        image_bytes: Optional[bytes] = None,
        scene_snapshot: Optional[SceneSnapshot] = None,
        yield_chunk: Optional[Callable[[StreamChunk], None]] = None
    ) -> AgentResult:
        """
        Ejecuta el bucle ReAct hasta que el LLM finaliza la tarea (end_turn)
        o se alcanza el límite de iteraciones configurado.
        """
        # 1. Obtener snapshot del estado actual de la escena
        snapshot = scene_snapshot or SceneInspector.capture()
        scene_context_str = snapshot.to_prompt_context()

        # 2. Agregar el mensaje del usuario al contexto
        self.context_manager.add_message(Message(
            role="user",
            content=user_prompt,
            image_bytes=image_bytes
        ))

        total_session_cost = 0.0
        tools_schema = self._get_provider_tools_schema()

        for iteration in range(1, self.max_iterations + 1):
            logger.info("Iteración del Agente [%d/%d]", iteration, self.max_iterations)

            # Preparar contexto con ventana deslizante y prompt del sistema
            prepared_messages = self.context_manager.get_prepared_messages(scene_context=scene_context_str)

            try:
                # Consulta al LLM Provider con soporte de streaming
                response: LLMResponse = self.provider.complete_stream(
                    messages=prepared_messages,
                    tools=tools_schema if tools_schema else None,
                    yield_chunk=yield_chunk
                )
            except ProviderException as pe:
                logger.error("Error en Provider durante la iteración %d: %s", iteration, pe.message)
                return AgentResult(
                    success=False,
                    content=f"Error del Proveedor de IA: {pe.message}",
                    iterations=iteration,
                    error_type=pe.error_type
                )
            except Exception as e:
                logger.exception("Error inesperado en consulta al LLM: %s", str(e))
                return AgentResult(
                    success=False,
                    content=f"Error inesperado al conectar con el modelo: {str(e)}",
                    iterations=iteration,
                    error_type=ErrorType.UNKNOWN
                )

            total_session_cost += response.cost_usd

            # Registrar la respuesta del asistente en el contexto
            self.context_manager.add_message(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls
            ))

            # Si el modelo terminó de hablar y no solicitó herramientas, retornamos éxito
            if response.stop_reason == StopReason.END_TURN or not response.tool_calls:
                return AgentResult(
                    success=True,
                    content=response.content or "Instrucción completada exitosamente.",
                    iterations=iteration,
                    total_cost_usd=total_session_cost
                )

            # Si el modelo invocó herramientas, procesar cada una pasando por el AuthGate
            if response.stop_reason == StopReason.TOOL_USE and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_def = self.tool_registry.get(tool_call.name)
                    
                    if not tool_def:
                        error_msg = f"Herramienta '{tool_call.name}' no encontrada en el registro."
                        logger.warning(error_msg)
                        self.context_manager.add_message(Message(
                            role="tool",
                            content=error_msg,
                            tool_call_id=tool_call.id
                        ))
                        continue

                    # Verificar si la herramienta requiere aprobación del usuario
                    is_approved = True
                    if tool_def.requires_approval:
                        args_preview = json.dumps(tool_call.arguments, ensure_ascii=False)
                        description = f"Ejecutar herramienta '{tool_def.name}' con argumentos: {args_preview}"
                        is_approved = self.auth_gate.request_approval(
                            tool_name=tool_def.name,
                            arguments=tool_call.arguments,
                            description=description
                        )

                    if not is_approved:
                        rejection_msg = f"La ejecución de la herramienta '{tool_def.name}' fue RECHAZADA por el usuario."
                        logger.info(rejection_msg)
                        self.context_manager.add_message(Message(
                            role="tool",
                            content=rejection_msg,
                            tool_call_id=tool_call.id
                        ))
                        continue

                    # Ejecutar la herramienta en Blender
                    try:
                        logger.info("Ejecutando herramienta '%s' con argumentos %s", tool_def.name, tool_call.arguments)
                        raw_result = tool_def.execute(**tool_call.arguments)
                        result_str = str(raw_result) if raw_result is not None else "Acción completada con éxito."
                    except Exception as ex:
                        logger.exception("Fallo al ejecutar herramienta '%s': %s", tool_def.name, str(ex))
                        result_str = f"Error al ejecutar '{tool_def.name}': {str(ex)}. Por favor corrige los parámetros e intenta nuevamente."

                    # Registrar el resultado de la herramienta para el siguiente turno
                    self.context_manager.add_message(Message(
                        role="tool",
                        content=result_str,
                        tool_call_id=tool_call.id
                    ))

        # Si se agotaron las iteraciones sin StopReason.END_TURN
        limit_msg = f"Se ha alcanzado el límite máximo de {self.max_iterations} iteraciones del agente."
        logger.warning(limit_msg)
        return AgentResult(
            success=False,
            content=limit_msg,
            iterations=self.max_iterations,
            total_cost_usd=total_session_cost,
            is_max_iterations=True
        )
