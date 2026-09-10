"""
core/providers/anthropic.py
===========================
Adaptador para la API de Anthropic (Claude 3.7 Sonnet, Claude 3.5 Haiku).
Implementado con la librería estándar urllib para no requerir dependencias externas en Blender.
Soporta streaming en tiempo real (SSE), buffering de Tool Calls y extracción precisa de tokens.
"""

from __future__ import annotations
import json
import logging
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, List, Optional

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

logger = logging.getLogger("BlenderAIAgent.Anthropic")


class AnthropicProvider(BaseProvider):
    """Adaptador REST nativo para Anthropic."""

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, default_model: str = "claude-3-7-sonnet"):
        super().__init__(api_key=api_key, default_model=default_model)
        self.cost_tracker = CostTracker()

    def get_available_models(self) -> List[str]:
        return ["claude-3-7-sonnet", "claude-3-5-haiku", "claude-3-opus"]

    def supports_vision(self) -> bool:
        return True

    def _prepare_payload(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Convierte los mensajes internos al formato de la API de Anthropic."""
        target_model = model or self.default_model or "claude-3-7-sonnet"
        system_prompt = ""
        api_messages = []

        for msg in messages:
            if msg.role == "system":
                system_prompt += f"{msg.content}\n"
            elif msg.role == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "tool_call_0",
                        "content": msg.content
                    }]
                })
            elif msg.role == "assistant" and msg.tool_calls:
                content_blocks = []
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments
                    })
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                # Mensaje estándar (user o assistant)
                content_blocks = []
                if msg.image_bytes:
                    import base64
                    b64_data = base64.b64encode(msg.image_bytes).decode("utf-8")
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": msg.image_mime_type or "image/png",
                            "data": b64_data
                        }
                    })
                if msg.content:
                    content_blocks.append({"type": "text", "text": msg.content})
                api_messages.append({"role": msg.role, "content": content_blocks or msg.content})

        payload = {
            "model": target_model,
            "max_tokens": 4096,
            "messages": api_messages,
            "stream": stream
        }

        if system_prompt.strip():
            payload["system"] = system_prompt.strip()

        if tools:
            payload["tools"] = tools

        return payload

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_key.strip():
            raise ProviderException(
                "La API Key de Anthropic está vacía. Configúrala en las preferencias del Add-on.",
                error_type=ErrorType.AUTHENTICATION,
                is_recoverable=False
            )
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key.strip(),
            "anthropic-version": self.API_VERSION
        }

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Ejecuta una petición bloqueante."""
        payload = self._prepare_payload(messages, tools=tools, model=model, stream=False)
        target_model = payload["model"]
        headers = self._get_headers()

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.API_URL, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            if e.code in (401, 403):
                raise ProviderException(f"Error de autenticación en Anthropic: {err_body}", ErrorType.AUTHENTICATION)
            elif e.code == 429:
                raise ProviderException(f"Límite de tasa excedido en Anthropic: {err_body}", ErrorType.RATE_LIMIT, is_recoverable=True)
            raise ProviderException(f"Error HTTP {e.code} en Anthropic: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de conexión con Anthropic: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        return self._parse_json_response(body, target_model)

    def complete_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        yield_chunk: Optional[Callable[[StreamChunk], None]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Ejecuta streaming con buffering seguro de argumentos JSON de herramientas."""
        payload = self._prepare_payload(messages, tools=tools, model=model, stream=True)
        target_model = payload["model"]
        headers = self._get_headers()

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.API_URL, data=data, headers=headers, method="POST")

        accumulated_text = []
        tool_calls: List[ToolCall] = []
        current_tool: Optional[Dict[str, Any]] = None
        input_tokens = 0
        output_tokens = 0
        stop_reason = StopReason.END_TURN

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                for line in response:
                    line_str = line.decode("utf-8").strip()
                    if not line_str.startswith("data:"):
                        continue
                    data_str = line_str[5:].strip()
                    if data_str == "[DONE]":
                        break
                    
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")

                    if event_type == "message_start":
                        msg_data = event.get("message", {})
                        usage = msg_data.get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)

                    elif event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool = {
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "json_buffer": ""
                            }

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type")

                        if delta_type == "text_delta":
                            text_piece = delta.get("text", "")
                            accumulated_text.append(text_piece)
                            if yield_chunk:
                                yield_chunk(StreamChunk(text=text_piece))

                        elif delta_type == "input_json_delta" and current_tool:
                            # Buffering estricto: no enviar fragmentos JSON rotos a la UI
                            current_tool["json_buffer"] += delta.get("partial_json", "")

                    elif event_type == "content_block_stop" and current_tool:
                        # Parsear el objeto JSON de la herramienta una vez completo
                        try:
                            args = json.loads(current_tool["json_buffer"]) if current_tool["json_buffer"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(
                            id=current_tool["id"] or f"tc_{len(tool_calls)}",
                            name=current_tool["name"] or "unknown_tool",
                            arguments=args
                        ))
                        current_tool = None

                    elif event_type == "message_delta":
                        delta = event.get("delta", {})
                        stop = delta.get("stop_reason")
                        if stop == "tool_use":
                            stop_reason = StopReason.TOOL_USE
                        elif stop == "max_tokens":
                            stop_reason = StopReason.MAX_TOKENS
                        usage = event.get("usage", {})
                        output_tokens += usage.get("output_tokens", 0)

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            raise ProviderException(f"Error HTTP en streaming de Anthropic: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de red en streaming de Anthropic: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        final_content = "".join(accumulated_text)
        cost = self.cost_tracker.calculate_cost(target_model, input_tokens, output_tokens)

        return LLMResponse(
            content=final_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=target_model,
            stop_reason=StopReason.TOOL_USE if tool_calls else stop_reason,
            tool_calls=tool_calls if tool_calls else None
        )

    def _parse_json_response(self, body: Dict[str, Any], model: str) -> LLMResponse:
        """Parsea una respuesta JSON completa de Anthropic."""
        content_blocks = body.get("content", [])
        text_parts = []
        tool_calls: List[ToolCall] = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {})
                ))

        usage = body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cost = self.cost_tracker.calculate_cost(model, input_tokens, output_tokens)

        raw_stop = body.get("stop_reason")
        stop_reason = StopReason.TOOL_USE if (tool_calls or raw_stop == "tool_use") else StopReason.END_TURN

        return LLMResponse(
            content="".join(text_parts),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
            stop_reason=stop_reason,
            tool_calls=tool_calls if tool_calls else None,
            raw_response=body
        )
