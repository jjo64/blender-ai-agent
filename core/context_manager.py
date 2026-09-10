"""
core/context_manager.py
=======================
Gestor de ventana de contexto (Context Window Management) para el Agente.
Implementa una estrategia de Ventana Deslizante (Sliding Window), recorte
de outputs excesivos de herramientas (Tool Trimming) y preservación estricta
de Decisiones Técnicas Inmutables (Pinned Decisions).
"""

from __future__ import annotations
from typing import List, Optional
from core.providers.base import Message


class ContextManager:
    """Administra el ensamblado del contexto enviado a los LLMs."""

    def __init__(
        self,
        system_prompt: str = "Eres Blender AI Agent, un asistente experto en Blender y Python 3D.",
        max_messages_window: int = 12,
        max_tool_output_chars: int = 1200
    ):
        self.system_prompt = system_prompt
        self.max_messages_window = max_messages_window
        self.max_tool_output_chars = max_tool_output_chars
        
        self.pinned_decisions: List[str] = []
        self.history: List[Message] = []

    def add_pinned_decision(self, decision: str) -> None:
        """
        Registra una decisión técnica inmutable (ej: 'Utilizar escala métrica en centímetros').
        Estas decisiones se inyectan siempre en el bloque del sistema y nunca son eliminadas.
        """
        clean_dec = decision.strip()
        if clean_dec and clean_dec not in self.pinned_decisions:
            self.pinned_decisions.append(clean_dec)

    def add_message(self, message: Message) -> None:
        """Agrega un mensaje al historial en memoria."""
        self.history.append(message)

    def _format_system_block(self, extra_context: Optional[str] = None) -> str:
        """Ensambla el System Prompt combinando directivas base, decisiones y contexto dinámico."""
        blocks = [self.system_prompt]

        if self.pinned_decisions:
            blocks.append("\n[DECISIONES TÉCNICAS INMUTABLES]")
            for dec in self.pinned_decisions:
                blocks.append(f" - {dec}")
            blocks.append("[FIN DE DECISIONES]")

        if extra_context:
            blocks.append(f"\n{extra_context}")

        return "\n".join(blocks)

    def get_prepared_messages(self, scene_context: Optional[str] = None) -> List[Message]:
        """
        Retorna la lista final y optimizada de mensajes para enviar al LLM:
        1. Mensaje de Sistema enriquecido (System Prompt + Pinned Decisions + SceneSnapshot).
        2. Ventana deslizante de los últimos N mensajes, recortando respuestas masivas de tools.
        """
        prepared: List[Message] = []

        # 1. Mensaje del sistema unificado
        system_content = self._format_system_block(extra_context=scene_context)
        prepared.append(Message(role="system", content=system_content))

        # 2. Ventana deslizante de mensajes recientes
        recent_history = self.history[-self.max_messages_window:] if self.history else []

        for msg in recent_history:
            content = msg.content

            # Recortar outputs gigantes de herramientas para no agotar tokens
            if msg.role == "tool" and len(content) > self.max_tool_output_chars:
                truncated_chars = len(content) - self.max_tool_output_chars
                content = (
                    content[:self.max_tool_output_chars]
                    + f"\n... [Respuesta recortada: {truncated_chars} caracteres omitidos por eficiencia]"
                )

            prepared.append(Message(
                role=msg.role,
                content=content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                image_bytes=msg.image_bytes,
                image_mime_type=msg.image_mime_type
            ))

        return prepared

    def clear(self) -> None:
        """Reinicia el historial de mensajes manteniendo las decisiones fijadas."""
        self.history.clear()
