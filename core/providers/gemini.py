"""
core/providers/gemini.py
========================
Adaptador para la API de Google Gemini (Gemini 2.0 Flash, Gemini 1.5 Pro).
Implementado con urllib nativo, soporta Function Calling, streaming SSE y visión.
"""

from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, List, Optional

try:
    from .base import (
        BaseProvider,
        ErrorType,
        LLMResponse,
        Message,
        ProviderException,
        StopReason,
        StreamChunk,
        ToolCall,
    )
    from ..tracker.cost_tracker import CostTracker
except ImportError:
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
    from core.tracker.cost_tracker import CostTracker

logger = logging.getLogger("BlenderAIAgent.Gemini")


class GeminiProvider(BaseProvider):
    """Adaptador REST nativo para Google Gemini."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, default_model: str = "gemini-2.0-flash"):
        super().__init__(api_key=api_key, default_model=default_model)
        self.cost_tracker = CostTracker()

    def get_available_models(self) -> List[str]:
        return ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

    def supports_vision(self) -> bool:
        return True

    def _prepare_payload(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Convierte los mensajes internos al formato de Gemini."""
        system_instructions = []
        contents = []

        for msg in messages:
            if msg.role == "system":
                system_instructions.append(msg.content)
            elif msg.role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.tool_call_id or "tool_result",
                            "response": {"output": msg.content}
                        }
                    }]
                })
            elif msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append({"text": msg.content})
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments
                        }
                    })
                contents.append({"role": "model", "parts": parts})
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = []
                if msg.image_bytes:
                    import base64
                    b64_data = base64.b64encode(msg.image_bytes).decode("utf-8")
                    parts.append({
                        "inline_data": {
                            "mime_type": msg.image_mime_type or "image/png",
                            "data": b64_data
                        }
                    })
                if msg.content:
                    parts.append({"text": msg.content})
                contents.append({"role": role, "parts": parts})

        payload: Dict[str, Any] = {"contents": contents}

        if system_instructions:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n".join(system_instructions)}]
            }

        if tools:
            # En Gemini las tools se agrupan dentro de functionDeclarations
            payload["tools"] = [{"functionDeclarations": tools}]

        return payload

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Petición síncrona completa a Gemini."""
        target_model = model or self.default_model or "gemini-2.0-flash"
        if not self.api_key or not self.api_key.strip():
            raise ProviderException("API Key de Google Gemini ausente.", ErrorType.AUTHENTICATION)

        url = f"{self.BASE_URL}/{target_model}:generateContent?key={self.api_key.strip()}"
        payload = self._prepare_payload(messages, tools=tools)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            if e.code in (400, 401, 403):
                raise ProviderException(f"Error de autenticación/solicitud en Gemini: {err_body}", ErrorType.AUTHENTICATION)
            elif e.code == 429:
                raise ProviderException(f"Límite de tasa en Gemini: {err_body}", ErrorType.RATE_LIMIT, is_recoverable=True)
            raise ProviderException(f"Error HTTP {e.code} en Gemini: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de conexión con Gemini: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        return self._parse_json_response(body, target_model)

    def complete_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        yield_chunk: Optional[Callable[[StreamChunk], None]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Streaming con SSE a la API de Gemini."""
        target_model = model or self.default_model or "gemini-2.0-flash"
        if not self.api_key or not self.api_key.strip():
            raise ProviderException("API Key de Google Gemini ausente.", ErrorType.AUTHENTICATION)

        url = f"{self.BASE_URL}/{target_model}:streamGenerateContent?alt=sse&key={self.api_key.strip()}"
        payload = self._prepare_payload(messages, tools=tools)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

        accumulated_text = []
        tool_calls: List[ToolCall] = []
        input_tokens = 0
        output_tokens = 0

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for line in response:
                    line_str = line.decode("utf-8").strip()
                    if not line_str.startswith("data:"):
                        continue
                    data_str = line_str[5:].strip()
                    if not data_str:
                        continue

                    try:
                        chunk_json = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    usage = chunk_json.get("usageMetadata", {})
                    if usage:
                        input_tokens = usage.get("promptTokenCount", input_tokens)
                        output_tokens = usage.get("candidatesTokenCount", output_tokens)

                    candidates = chunk_json.get("candidates", [])
                    if not candidates:
                        continue

                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])

                    for part in parts:
                        if "text" in part:
                            text_piece = part["text"]
                            accumulated_text.append(text_piece)
                            if yield_chunk:
                                yield_chunk(StreamChunk(text=text_piece))
                        elif "functionCall" in part:
                            fn = part["functionCall"]
                            tool_calls.append(ToolCall(
                                id=f"gemini_call_{len(tool_calls)}",
                                name=fn.get("name", "unknown"),
                                arguments=fn.get("args", {})
                            ))

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            raise ProviderException(f"Error HTTP en streaming de Gemini: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de conexión con Gemini: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        final_content = "".join(accumulated_text)
        cost = self.cost_tracker.calculate_cost(target_model, input_tokens, output_tokens)

        return LLMResponse(
            content=final_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=target_model,
            stop_reason=StopReason.TOOL_USE if tool_calls else StopReason.END_TURN,
            tool_calls=tool_calls if tool_calls else None
        )

    def _parse_json_response(self, body: Dict[str, Any], model: str) -> LLMResponse:
        """Parsea la respuesta JSON síncrona de Gemini."""
        candidates = body.get("candidates", [])
        if not candidates:
            raise ProviderException("Gemini no devolvió candidatos válidos.", ErrorType.PARSING)

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        text_parts = []
        tool_calls: List[ToolCall] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fn = part["functionCall"]
                tool_calls.append(ToolCall(
                    id=f"gemini_call_{len(tool_calls)}",
                    name=fn.get("name", ""),
                    arguments=fn.get("args", {})
                ))

        usage = body.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        cost = self.cost_tracker.calculate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content="".join(text_parts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
            stop_reason=StopReason.TOOL_USE if tool_calls else StopReason.END_TURN,
            tool_calls=tool_calls if tool_calls else None,
            raw_response=body
        )
