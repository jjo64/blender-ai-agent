"""
ui/settings_panel.py
====================
Panel de configuración y preferencias del Add-on (API Keys, modelos y timeouts).
"""

from __future__ import annotations
try:
    import bpy
    from bpy.types import AddonPreferences
    from bpy.props import StringProperty, IntProperty
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False
    AddonPreferences = object


class AIAgentPreferences(AddonPreferences):
    """Preferencias persistidas en userpref.blend de Blender."""
    bl_idname = __package__.split('.')[0] if (__package__ and '.' in __package__) else (__package__ or "blender_ai_agent")

    anthropic_api_key: StringProperty(
        name="Anthropic API Key",
        description="API Key para Claude (Anthropic)",
        default="",
        subtype='PASSWORD'
    )

    openai_api_key: StringProperty(
        name="OpenAI API Key",
        description="API Key para GPT-4o (OpenAI)",
        default="",
        subtype='PASSWORD'
    )

    google_api_key: StringProperty(
        name="Google Gemini API Key",
        description="API Key para Gemini (Google)",
        default="",
        subtype='PASSWORD'
    )

    max_iterations: IntProperty(
        name="Iteraciones Máximas",
        description="Límite máximo de ciclos en el ReAct Loop por cada instrucción",
        default=10,
        min=1,
        max=30
    )

    def draw(self, context):
        layout = self.layout

        box_keys = layout.box()
        box_keys.label(text="Credenciales de Proveedores de IA (API Keys)", icon='LOCKED')
        box_keys.prop(self, "anthropic_api_key")
        box_keys.prop(self, "openai_api_key")
        box_keys.prop(self, "google_api_key")

        box_limits = layout.box()
        box_limits.label(text="Límites de Seguridad y Razonamiento", icon='PREFERENCES')
        box_limits.prop(self, "max_iterations")
