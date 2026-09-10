"""
tests/test_context_scene_and_cost.py
====================================
Pruebas unitarias para SceneInspector, CostTracker y ContextManager.
"""

import unittest
from core.scene_inspector import SceneSnapshot, SceneInspector
from core.tracker.cost_tracker import CostTracker
from core.context_manager import ContextManager
from core.providers.base import Message


class TestSceneInspector(unittest.TestCase):
    def test_snapshot_formatting(self):
        snapshot = SceneSnapshot(
            active_object="HeroMesh",
            selected_objects=["HeroMesh", "Light_01"],
            object_count=5,
            mode="EDIT",
            active_mesh_stats={"vertices": 120, "faces": 118, "ngons": 2},
            active_materials=["Metal_Rough", "Gold_Trim"],
            unit_system="METRIC"
        )
        ctx_str = snapshot.to_prompt_context()

        self.assertIn("HeroMesh", ctx_str)
        self.assertIn("Modo de interacción: EDIT", ctx_str)
        self.assertIn("120 vértices", ctx_str)
        self.assertIn("2 n-gons", ctx_str)
        self.assertIn("Metal_Rough", ctx_str)

    def test_inspector_mock_capture(self):
        # Fuera de Blender debe retornar un snapshot mock válido
        snapshot = SceneInspector.capture()
        self.assertIsNotNone(snapshot.active_object)
        self.assertTrue(len(snapshot.to_prompt_context()) > 20)


class TestCostTracker(unittest.TestCase):
    def test_pricing_calculation(self):
        tracker = CostTracker()
        
        # Test con modelo estándar del catálogo (ej. gpt-4o: in=2.5, out=10.0 per 1M)
        # 1,000,000 in = $2.5, 100,000 out = $1.0 -> Total: $3.50
        cost = tracker.calculate_cost("gpt-4o", 1_000_000, 100_000)
        self.assertAlmostEqual(cost, 3.50, places=2)

    def test_session_accumulation(self):
        tracker = CostTracker()
        tracker.reset_session()

        tracker.record_usage("claude-3-7-sonnet", 10_000, 2_000)
        tracker.record_usage("claude-3-7-sonnet", 5_000, 1_000)

        self.assertEqual(tracker.session_input_tokens, 15_000)
        self.assertEqual(tracker.session_output_tokens, 3_000)
        self.assertEqual(len(tracker.session_requests), 2)
        self.assertTrue(tracker.session_cost_usd > 0.0)


class TestContextManager(unittest.TestCase):
    def test_pinned_decisions_immutability(self):
        ctx = ContextManager(system_prompt="Base prompt", max_messages_window=2)
        ctx.add_pinned_decision("Convención: Nombres de objetos siempre en snake_case")

        # Agregar 4 mensajes para forzar desborde de ventana
        ctx.add_message(Message(role="user", content="msg 1"))
        ctx.add_message(Message(role="assistant", content="msg 2"))
        ctx.add_message(Message(role="user", content="msg 3"))
        ctx.add_message(Message(role="assistant", content="msg 4"))

        prepared = ctx.get_prepared_messages()

        # Debe contener el system prompt enriquecido + 2 mensajes recientes
        self.assertEqual(len(prepared), 3)
        self.assertEqual(prepared[0].role, "system")
        self.assertIn("snake_case", prepared[0].content)
        self.assertEqual(prepared[1].content, "msg 3")
        self.assertEqual(prepared[2].content, "msg 4")

    def test_tool_output_trimming(self):
        ctx = ContextManager(max_tool_output_chars=50)
        huge_tool_output = "V" * 200
        ctx.add_message(Message(role="tool", content=huge_tool_output))

        prepared = ctx.get_prepared_messages()
        tool_msg = prepared[1]

        self.assertTrue(len(tool_msg.content) < 200)
        self.assertIn("Respuesta recortada", tool_msg.content)


if __name__ == "__main__":
    unittest.main()
