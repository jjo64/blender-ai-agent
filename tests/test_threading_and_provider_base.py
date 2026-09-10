"""
tests/test_threading_and_provider_base.py
=========================================
Pruebas unitarias para los contratos de providers y el TaskBridge concurrente.
"""

import threading
import time
import unittest
from core.providers.base import (
    BaseProvider,
    ErrorType,
    LLMResponse,
    Message,
    StopReason,
    StreamChunk,
    ToolCall,
)
from blender_integration.threading_model import TaskBridge, WorkerResult, PendingAction


class MockProvider(BaseProvider):
    def complete(self, messages, tools=None, model=None) -> LLMResponse:
        return LLMResponse(
            content="Respuesta mock",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            model=model or "mock-model",
            stop_reason=StopReason.END_TURN
        )

    def complete_stream(self, messages, tools=None, yield_chunk=None, model=None) -> LLMResponse:
        if yield_chunk:
            yield_chunk(StreamChunk(text="Hola "))
            yield_chunk(StreamChunk(text="Mundo"))
        return LLMResponse(
            content="Hola Mundo",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
            model=model or "mock-model",
            stop_reason=StopReason.END_TURN
        )

    def supports_vision(self) -> bool:
        return True

    def get_available_models(self) -> list[str]:
        return ["mock-v1"]


class TestProviderBaseAndThreading(unittest.TestCase):
    def test_mock_provider_complete(self):
        provider = MockProvider(api_key="sk-test")
        messages = [Message(role="user", content="Hola")]
        res = provider.complete(messages)

        self.assertEqual(res.content, "Respuesta mock")
        self.assertEqual(res.stop_reason, StopReason.END_TURN)
        self.assertEqual(res.input_tokens, 100)

    def test_mock_provider_streaming(self):
        provider = MockProvider(api_key="sk-test")
        messages = [Message(role="user", content="Hola")]
        chunks = []

        res = provider.complete_stream(messages, yield_chunk=lambda c: chunks.append(c.text))

        self.assertEqual(res.content, "Hola Mundo")
        self.assertEqual("".join(chunks), "Hola Mundo")

    def test_task_bridge_concurrency_and_dispatch(self):
        bridge = TaskBridge()
        received_chunks = []
        received_results = []

        bridge.register_chunk_listener(lambda c: received_chunks.append(c.text))
        bridge.register_result_listener(lambda r: received_results.append(r))

        def background_work():
            bridge.push_chunk(StreamChunk(text="token1 "))
            bridge.push_chunk(StreamChunk(text="token2"))
            bridge.push_result(WorkerResult(success=True, content="Tarea completada"))

        bridge.start_worker(background_work)

        # Esperar a que el worker termine
        if bridge.active_thread:
            bridge.active_thread.join(timeout=2.0)

        # Simular ciclo de timer
        bridge._timer_callback()

        self.assertEqual(received_chunks, ["token1 ", "token2"])
        self.assertEqual(len(received_results), 1)
        self.assertTrue(received_results[0].success)
        self.assertEqual(received_results[0].content, "Tarea completada")

    def test_run_in_main_thread_direct_fallback(self):
        bridge = TaskBridge()
        def add(a, b):
            return a + b
        res = bridge.run_in_main_thread(add, 10, 20)
        self.assertEqual(res, 30)

    def test_run_in_main_thread_worker_dispatch(self):
        bridge = TaskBridge()
        worker_res = []

        def background_caller():
            # Llamada síncrona que simula requerir el Main Thread
            val = bridge.run_in_main_thread(lambda x: x * 3, 7)
            worker_res.append(val)

        # En entorno sin bpy, BLENDER_AVAILABLE es False, por lo que run_in_main_thread corre de inmediato de forma segura
        t = threading.Thread(target=background_caller)
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(worker_res, [21])


if __name__ == "__main__":
    unittest.main()
