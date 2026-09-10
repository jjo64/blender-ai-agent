"""
tests/test_tools_and_security.py
================================
Pruebas unitarias para ToolRegistry, AuthGate y Sandbox AST.
"""

import threading
import time
import unittest
from core.tool_registry import ToolRegistry, ToolDefinition, tool
import core.tool_registry as tr_module
from core.security.auth_gate import AuthGate
from core.security.sandbox import validate_python_code, execute_sandboxed


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        tr_module.registry.clear()

    def test_decorator_registration(self):
        @tool(
            name="test_primitive",
            description="Crea una primitiva de prueba.",
            requires_approval=True,
            parameters={
                "type": "object",
                "properties": {"radius": {"type": "number"}},
                "required": ["radius"]
            }
        )
        def create_primitive(radius: float):
            return f"Created with radius {radius}"

        reg_tool = tr_module.registry.get("test_primitive")
        self.assertIsNotNone(reg_tool)
        self.assertEqual(reg_tool.name, "test_primitive")
        self.assertTrue(reg_tool.requires_approval)
        self.assertEqual(reg_tool.execute(radius=5.0), "Created with radius 5.0")

    def test_schema_exports(self):
        @tool(name="simple_op", description="Op simple")
        def simple_op():
            pass

        openai_schemas = tr_module.registry.to_openai_schemas()
        anthropic_schemas = tr_module.registry.to_anthropic_schemas()
        gemini_schemas = tr_module.registry.to_gemini_schemas()

        self.assertEqual(len(openai_schemas), 1)
        self.assertEqual(openai_schemas[0]["type"], "function")
        self.assertEqual(openai_schemas[0]["function"]["name"], "simple_op")

        self.assertEqual(len(anthropic_schemas), 1)
        self.assertEqual(anthropic_schemas[0]["name"], "simple_op")
        self.assertIn("input_schema", anthropic_schemas[0])

        self.assertEqual(len(gemini_schemas), 1)
        self.assertEqual(gemini_schemas[0]["name"], "simple_op")


class TestAuthGate(unittest.TestCase):
    def test_auto_approve(self):
        gate = AuthGate(auto_approve=True)
        approved = gate.request_approval("delete_all", {}, "Borrar todo")
        self.assertTrue(approved)

    def test_interactive_approval(self):
        gate = AuthGate(auto_approve=False)
        resolved_actions = []

        def background_thread():
            approved = gate.request_approval("bevel_mesh", {"amount": 0.2}, "Aplicar bisel")
            resolved_actions.append(approved)

        t = threading.Thread(target=background_thread)
        t.start()

        # Simular que el usuario aprueba tras 50ms
        time.sleep(0.05)
        self.assertIsNotNone(gate.current_pending)
        self.assertEqual(gate.current_pending.tool_name, "bevel_mesh")
        
        gate.resolve(approved=True)
        t.join(timeout=1.0)

        self.assertEqual(resolved_actions, [True])

    def test_interactive_rejection(self):
        gate = AuthGate(auto_approve=False)
        resolved_actions = []

        def background_thread():
            approved = gate.request_approval("dangerous_op", {}, "Peligroso")
            resolved_actions.append(approved)

        t = threading.Thread(target=background_thread)
        t.start()

        time.sleep(0.05)
        gate.resolve(approved=False)
        t.join(timeout=1.0)

        self.assertEqual(resolved_actions, [False])


class TestSandbox(unittest.TestCase):
    def test_safe_code(self):
        safe_code = """
import math
import mathutils

def calculate_coords():
    return math.sin(3.14) * 2
result = calculate_coords()
"""
        is_safe, error = validate_python_code(safe_code)
        self.assertTrue(is_safe)
        self.assertIsNone(error)

    def test_block_os_import(self):
        malicious_code = "import os\nos.system('calc.exe')"
        is_safe, error = validate_python_code(malicious_code)
        self.assertFalse(is_safe)
        self.assertIn("Importación prohibida del módulo 'os'", error)

    def test_block_subprocess(self):
        malicious_code = "from subprocess import Popen"
        is_safe, error = validate_python_code(malicious_code)
        self.assertFalse(is_safe)
        self.assertIn("Importación prohibida desde el módulo 'subprocess'", error)

    def test_block_eval_and_exec(self):
        eval_code = "eval('2 + 2')"
        is_safe, error = validate_python_code(eval_code)
        self.assertFalse(is_safe)
        self.assertIn("Llamada prohibida a la función del sistema 'eval()'", error)

    def test_execute_sandboxed_raises_permission_error(self):
        with self.assertRaises(PermissionError):
            execute_sandboxed("import socket")


if __name__ == "__main__":
    unittest.main()
