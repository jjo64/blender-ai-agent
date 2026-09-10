"""
tests/test_agent_and_providers.py
=================================
Pruebas unitarias para los adaptadores de proveedores (Anthropic, OpenAI, Gemini)
y el bucle principal de razonamiento AgentLoop.
"""

import unittest
from core.agent import AgentLoop, AgentResult
from core.context_manager import ContextManager
from core.providers.base import (
    BaseProvider,
    ErrorType,
    LLMResponse,
    Message,
    StopReason,
    StreamChunk,
    ToolCall,
)
from core.providers.anthropic import AnthropicProvider
from core.providers.openai import OpenAIProvider
from core.providers.gemini import GeminiProvider
from core.security.auth_gate import AuthGate
from core.tool_registry import ToolRegistry, ToolDefinition


class MockScriptedProvider(BaseProvider):
    """Proveedor mock que retorna una secuencia predefinida de respuestas para testear el ReAct loop."""
    def __init__(self, responses: list[LLMResponse]):
        super().__init__(api_key="sk-mock")
        self.responses = list(responses)
        self.call_count = 0

    def complete(self, messages, tools=None, model=None) -> LLMResponse:
        return self.complete_stream(messages, tools, None, model)

    def complete_stream(self, messages, tools=None, yield_chunk=None, model=None) -> LLMResponse:
        resp = self.responses[self.call_count]
        self.call_count += 1
        if yield_chunk and resp.content:
            yield_chunk(StreamChunk(text=resp.content))
        return resp

    def supports_vision(self) -> bool:
        return True

    def get_available_models(self) -> list[str]:
        return ["mock-v1"]


class TestAgentAndProviders(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_anthropic_payload_preparation(self):
        prov = AnthropicProvider(api_key="sk-ant-test")
        messages = [
            Message(role="system", content="Actua como experto."),
            Message(role="user", content="Hola", image_bytes=b"fake_image"),
            Message(role="tool", content="Resultado 42", tool_call_id="call_123")
        ]
        tools = [{"name": "test_tool", "description": "desc", "input_schema": {}}]

        payload = prov._prepare_payload(messages, tools=tools)

        self.assertEqual(payload["model"], "claude-3-7-sonnet")
        self.assertIn("Actua como experto.", payload["system"])
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["tools"], tools)

    def test_openai_payload_preparation(self):
        prov = OpenAIProvider(api_key="sk-openai-test")
        messages = [
            Message(role="user", content="Crea un cubo"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_99", name="create_cube", arguments={"size": 2})]
            )
        ]
        payload = prov._prepare_payload(messages, stream=True)

        self.assertEqual(payload["model"], "gpt-4o")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["function"]["name"], "create_cube")

    def test_gemini_payload_preparation(self):
        prov = GeminiProvider(api_key="AIzaSyMock")
        messages = [
            Message(role="system", content="Instruccion"),
            Message(role="user", content="Pregunta")
        ]
        tools = [{"name": "tool_gem", "description": "desc", "parameters": {}}]

        payload = prov._prepare_payload(messages, tools=tools)
        self.assertIn("systemInstruction", payload)
        self.assertEqual(len(payload["contents"]), 1)
        self.assertIn("functionDeclarations", payload["tools"][0])

    def test_agent_react_loop_successful_execution(self):
        # 1. Definir una herramienta en el registro
        executed_args = []
        def add_cube(size: float):
            executed_args.append(size)
            return f"Cubo creado con tamaño {size}m"

        self.registry.register(ToolDefinition(
            name="add_cube",
            description="Crea un cubo",
            func=add_cube,
            parameters={"type": "object", "properties": {"size": {"type": "number"}}}
        ))

        # 2. Configurar respuestas simuladas del LLM (Turno 1: pide tool, Turno 2: responde end_turn)
        responses = [
            LLMResponse(
                content="",
                input_tokens=100,
                output_tokens=30,
                cost_usd=0.0005,
                model="mock-v1",
                stop_reason=StopReason.TOOL_USE,
                tool_calls=[ToolCall(id="call_1", name="add_cube", arguments={"size": 3.5})]
            ),
            LLMResponse(
                content="Listo, el cubo de 3.5m ha sido creado con éxito.",
                input_tokens=150,
                output_tokens=40,
                cost_usd=0.0006,
                model="mock-v1",
                stop_reason=StopReason.END_TURN
            )
        ]

        provider = MockScriptedProvider(responses)
        auth_gate = AuthGate(auto_approve=True)
        agent = AgentLoop(
            provider=provider,
            tool_registry=self.registry,
            auth_gate=auth_gate,
            max_iterations=5
        )

        streamed_chunks = []
        result: AgentResult = agent.run(
            user_prompt="Crea un cubo de 3.5m",
            yield_chunk=lambda c: streamed_chunks.append(c.text)
        )

        self.assertTrue(result.success)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(executed_args, [3.5])
        self.assertIn("ha sido creado con éxito", result.content)
        self.assertEqual("".join(streamed_chunks), "Listo, el cubo de 3.5m ha sido creado con éxito.")

    def test_agent_react_loop_handles_rejection(self):
        def risky_op():
            return "Borrado"

        self.registry.register(ToolDefinition(
            name="risky_op",
            description="Peligroso",
            func=risky_op,
            parameters={},
            requires_approval=True
        ))

        responses = [
            LLMResponse(
                content="",
                input_tokens=50,
                output_tokens=20,
                cost_usd=0.0002,
                model="mock-v1",
                stop_reason=StopReason.TOOL_USE,
                tool_calls=[ToolCall(id="call_risk", name="risky_op", arguments={})]
            ),
            LLMResponse(
                content="Entendido, no ejecuté la acción porque fue cancelada.",
                input_tokens=80,
                output_tokens=30,
                cost_usd=0.0003,
                model="mock-v1",
                stop_reason=StopReason.END_TURN
            )
        ]

        provider = MockScriptedProvider(responses)
        # AuthGate en modo rechazo manual inmediato
        auth_gate = AuthGate(auto_approve=False)
        auth_gate.request_approval = lambda *args, **kwargs: False

        agent = AgentLoop(
            provider=provider,
            tool_registry=self.registry,
            auth_gate=auth_gate,
            max_iterations=5
        )

        result = agent.run("Ejecuta accion peligrosa")
        self.assertTrue(result.success)
        self.assertEqual(result.iterations, 2)
        self.assertIn("fue cancelada", result.content)


if __name__ == "__main__":
    unittest.main()
