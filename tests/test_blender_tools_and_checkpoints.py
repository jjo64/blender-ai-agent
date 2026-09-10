"""
tests/test_blender_tools_and_checkpoints.py
===========================================
Pruebas unitarias para las herramientas de Blender, Checkpoints y Persistencia.
"""

import os
import tempfile
import unittest
from blender_integration.tools.mesh_ops import create_primitive, apply_modifier, transform_object, delete_object
from blender_integration.tools.material_ops import create_and_apply_material
from blender_integration.tools.run_script import run_python_script
from blender_integration.state_manager.checkpoints import CheckpointManager
from state.history import HistoryPersistence
from state.session import SessionState
from core.tool_registry import registry


class TestBlenderToolsAndCheckpoints(unittest.TestCase):
    def test_mesh_ops_registered_and_mock_execution(self):
        # Verificar que las tools están en el registro global
        self.assertIsNotNone(registry.get("create_primitive"))
        self.assertIsNotNone(registry.get("apply_modifier"))
        self.assertIsNotNone(registry.get("transform_object"))
        self.assertIsNotNone(registry.get("delete_object"))
        self.assertTrue(registry.get("delete_object").requires_approval)

        res = create_primitive(primitive_type="cube", name="MyCube", size=3.0)
        self.assertIn("MyCube", res)

        res_mod = apply_modifier(object_name="MyCube", modifier_type="BEVEL", properties={"width": 0.1})
        self.assertIn("BEVEL", res_mod)

    def test_material_ops_mock_execution(self):
        self.assertIsNotNone(registry.get("create_and_apply_material"))
        res = create_and_apply_material(
            object_name="Cube",
            material_name="Gold",
            base_color=[1.0, 0.8, 0.0],
            metallic=1.0,
            roughness=0.1
        )
        self.assertIn("Gold", res)
        self.assertIn("metallic=1.0", res)

    def test_run_script_security_and_execution(self):
        self.assertIsNotNone(registry.get("run_python_script"))
        self.assertTrue(registry.get("run_python_script").requires_approval)

        # 1. Código seguro
        res_safe = run_python_script("x = 10 + 20")
        self.assertIn("exitosamente", res_safe)

        # 2. Código malicioso (intento de import os)
        res_unsafe = run_python_script("import os\nos.remove('file')")
        self.assertIn("Error de Seguridad", res_unsafe)

    def test_checkpoints_fifo_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mgr = CheckpointManager(storage_dir=temp_dir)
            mgr.MAX_CHECKPOINTS = 3

            # Crear 4 checkpoints para probar política FIFO
            for i in range(4):
                mgr.create_checkpoint(label=f"step_{i}")

            # Solo deben quedar 3
            self.assertEqual(len(mgr.list_checkpoints()), 3)
            self.assertEqual(mgr.list_checkpoints()[-1].label, "step_3")

            # Restaurar el último
            last_cp = mgr.list_checkpoints()[-1]
            self.assertTrue(mgr.restore_checkpoint(last_cp.id))

            # Limpieza total
            mgr.cleanup()
            self.assertEqual(len(mgr.list_checkpoints()), 0)

    def test_history_persistence(self):
        msgs = [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola! ¿En qué puedo ayudarte en Blender?"}
        ]
        test_session_name = "test_blend_project"
        
        HistoryPersistence.save(msgs, blend_name=test_session_name)
        loaded = HistoryPersistence.load(blend_name=test_session_name)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["content"], "Hola")

    def test_session_state_provider_initialization(self):
        session = SessionState()
        
        anthropic_prov = session.initialize_provider("ANTHROPIC", api_key="sk-ant")
        self.assertEqual(anthropic_prov.__class__.__name__, "AnthropicProvider")

        openai_prov = session.initialize_provider("OPENAI", api_key="sk-oai")
        self.assertEqual(openai_prov.__class__.__name__, "OpenAIProvider")

        gemini_prov = session.initialize_provider("GOOGLE", api_key="AIzaSy")
        self.assertEqual(gemini_prov.__class__.__name__, "GeminiProvider")


if __name__ == "__main__":
    unittest.main()
