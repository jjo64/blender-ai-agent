"""
core/providers/openai.py
========================
Adaptador para la API de OpenAI (GPT-4o, GPT-4o-mini).
Implementado con la librería estándar urllib para compatibilidad nativa en Blender.
Soporta streaming Server-Sent Events (SSE), buffering de Function Calling y visión multimodal.
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

logger = logging.getLogger("BlenderAIAgent.OpenAI")


class OpenAIProvider(BaseProvider):
    """Adaptador REST nativo para OpenAI."""

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, default_model: str = "gpt-5.6-luna"):
        super().__init__(api_key=api_key, default_model=default_model)
        self.cost_tracker = CostTracker()

    def get_available_models(self) -> List[str]:
        return [
            "gpt-5.6-luna",
            "gpt-5.4-mini",
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-6-astra",
            "gpt-4o",
            "gpt-4o-mini",
        ]

    def supports_vision(self) -> bool:
        return True

    def _prepare_payload(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Convierte los mensajes al formato de Chat Completions de OpenAI."""
        target_model = model or self.default_model or "gpt-4o"
        api_messages = []

        for msg in messages:
            if msg.role == "tool":
                api_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "tool_call_0",
                    "content": msg.content
                })
            elif msg.role == "assistant" and msg.tool_calls:
                tc_list = []
                for tc in msg.tool_calls:
                    tc_list.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments)
                        }
                    })
                api_messages.append({
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": tc_list
                })
            else:
                if msg.image_bytes:
                    import base64
                    b64_data = base64.b64encode(msg.image_bytes).decode("utf-8")
                    mime = msg.image_mime_type or "image/png"
                    content_parts = [
                        {"type": "text", "text": msg.content or ""},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                        }
                    ]
                    api_messages.append({"role": msg.role, "content": content_parts})
                else:
                    api_messages.append({"role": msg.role, "content": msg.content})

        payload = {
            "model": target_model,
            "messages": api_messages,
            "stream": stream
        }

        if stream:
            payload["stream_options"] = {"include_usage": True}

        if tools:
            payload["tools"] = tools

        return payload

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_key.strip():
            raise ProviderException(
                "La API Key de OpenAI está vacía. Configúrala en las preferencias del Add-on.",
                error_type=ErrorType.AUTHENTICATION,
                is_recoverable=False
            )
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key.strip()}"
        }

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Petición síncrona completa a OpenAI."""
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
                raise ProviderException(f"Error de autenticación en OpenAI: {err_body}", ErrorType.AUTHENTICATION)
            elif e.code == 429:
                raise ProviderException(f"Límite de cuota o tasa excedido en OpenAI: {err_body}", ErrorType.RATE_LIMIT, is_recoverable=True)
            raise ProviderException(f"Error HTTP {e.code} en OpenAI: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de conexión con OpenAI: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        return self._parse_json_response(body, target_model)

    def complete_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        yield_chunk: Optional[Callable[[StreamChunk], None]] = None,
        model: Optional[str] = None
    ) -> LLMResponse:
        """Streaming con buffering y reensamblado de tool_calls fragmentados."""
        payload = self._prepare_payload(messages, tools=tools, model=model, stream=True)
        target_model = payload["model"]
        headers = self._get_headers()

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.API_URL, data=data, headers=headers, method="POST")

        accumulated_text = []
        raw_tool_buffers: Dict[int, Dict[str, Any]] = {}
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
                        chunk_json = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Capturar uso de tokens reportado al final del stream
                    if "usage" in chunk_json and chunk_json["usage"]:
                        u = chunk_json["usage"]
                        input_tokens = u.get("prompt_tokens", 0)
                        output_tokens = u.get("completion_tokens", 0)

                    choices = chunk_json.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta", {})

                    # 1. Contenido de texto
                    if "content" in delta and delta["content"]:
                        text_piece = delta["content"]
                        accumulated_text.append(text_piece)
                        if yield_chunk:
                            yield_chunk(StreamChunk(text=text_piece))

                    # 2. Fragmentos de tool_calls
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc_chunk in delta["tool_calls"]:
                            idx = tc_chunk.get("index", 0)
                            if idx not in raw_tool_buffers:
                                raw_tool_buffers[idx] = {
                                    "id": tc_chunk.get("id", ""),
                                    "name": "",
                                    "arguments": ""
                                }
                            if tc_chunk.get("id"):
                                raw_tool_buffers[idx]["id"] = tc_chunk["id"]
                            if "function" in tc_chunk:
                                fn = tc_chunk["function"]
                                if fn.get("name"):
                                    raw_tool_buffers[idx]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    raw_tool_buffers[idx]["arguments"] += fn["arguments"]

                    if choice.get("finish_reason") == "tool_calls":
                        stop_reason = StopReason.TOOL_USE

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else str(e)
            raise ProviderException(f"Error HTTP en streaming de OpenAI: {err_body}", ErrorType.NETWORK, is_recoverable=True)
        except urllib.error.URLError as e:
            raise ProviderException(f"Error de red en streaming de OpenAI: {e.reason}", ErrorType.NETWORK, is_recoverable=True)

        # Reensamblar y parsear tool_calls acumulados
        final_tool_calls: List[ToolCall] = []
        for idx in sorted(raw_tool_buffers.keys()):
            tb = raw_tool_buffers[idx]
            try:
                args = json.loads(tb["arguments"]) if tb["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            final_tool_calls.append(ToolCall(
                id=tb["id"] or f"call_{idx}",
                name=tb["name"] or "unknown_func",
                arguments=args
            ))

        final_content = "".join(accumulated_text)
        cost = self.cost_tracker.calculate_cost(target_model, input_tokens, output_tokens)

        return LLMResponse(
            content=final_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=target_model,
            stop_reason=StopReason.TOOL_USE if final_tool_calls else stop_reason,
            tool_calls=final_tool_calls if final_tool_calls else None
        )

    def _parse_json_response(self, body: Dict[str, Any], model: str) -> LLMResponse:
        """Parsea una respuesta JSON no-streaming de OpenAI."""
        choices = body.get("choices", [])
        if not choices:
            raise ProviderException("Respuesta vacía de OpenAI", ErrorType.PARSING)

        choice = choices[0]
        message_data = choice.get("message", {})
        content = message_data.get("content") or ""

        tool_calls: List[ToolCall] = []
        if "tool_calls" in message_data and message_data["tool_calls"]:
            for tc in message_data["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args
                ))

        usage = body.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        cost = self.cost_tracker.calculate_cost(model, input_tokens, output_tokens)

        stop_reason = StopReason.TOOL_USE if tool_calls else StopReason.END_TURN

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
            stop_reason=stop_reason,
            tool_calls=tool_calls if tool_calls else None,
            raw_response=body
        )
