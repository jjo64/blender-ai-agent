"""
core/providers/base.py
======================
Contratos abstractos e interfaces universales para proveedores de LLMs.
Agnóstico a Blender (100% testeable sin entorno bpy).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union


class StopReason(str, Enum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    ERROR = "error"


class ErrorType(str, Enum):
    AUTHENTICATION = "authentication"  # API key inválida o ausente
    RATE_LIMIT = "rate_limit"          # Exceso de cuota o RPM/TPM
    NETWORK = "network"                # Timeout o error de conexión
    PARSING = "parsing"                # Error al parsear JSON/argumentos
    UNKNOWN = "unknown"


@dataclass
class ToolCall:
    """Representación unificada de una llamada a herramienta."""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    """Fragmento de texto emitido durante el streaming para la interfaz."""
    text: str
    is_final: bool = False


@dataclass
class LLMResponse:
    """Respuesta normalizada de cualquier proveedor de LLM."""
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    stop_reason: StopReason = StopReason.END_TURN
    tool_calls: Optional[List[ToolCall]] = None
    raw_response: Optional[Any] = None


@dataclass
class Message:
    """Mensaje estándar dentro del historial de conversación."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    image_bytes: Optional[bytes] = None
    image_mime_type: Optional[str] = "image/png"


class ProviderException(Exception):
    """Excepción base para errores ocurridos dentro de adaptadores de LLM."""
    def __init__(self, message: str, error_type: ErrorType = ErrorType.UNKNOWN, is_recoverable: bool = False):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.is_recoverable = is_recoverable


class BaseProvider(ABC):
    """
    Clase base abstracta que todo adaptador (Anthropic, OpenAI, Gemini) debe implementar.
    El AgentLoop interactúa exclusivamente a través de esta interfaz.
    """

    def __init__(self, api_key: str, default_model: Optional[str] = None):
        self.api_key = api_key
        self.default_model = default_model

    @abstractmethod
    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """
        Ejecución síncrona/bloqueante que retorna la respuesta completa y tipada.
        """
        pass

    @abstractmethod
    def complete_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        yield_chunk: Optional[Callable[[StreamChunk], None]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """
        Ejecución con streaming:
        - Si el modelo emite texto para el usuario, invoca yield_chunk(StreamChunk(texto)).
        - Si el modelo emite llamadas a herramientas (JSON), las acumula internamente
          hasta parsear el ToolCall completo antes de retornar LLMResponse.
        """
        pass

    @abstractmethod
    def supports_vision(self) -> bool:
        """Indica si el proveedor/modelo actual admite adjuntar imágenes del viewport."""
        pass

    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Lista de identificadores de modelos soportados por este adaptador."""
        pass
