"""
Blender AI Agent - Extension Entry Point
========================================
Asistente y Agente de Inteligencia Artificial para Blender con arquitectura ReAct,
soporte Multi-Provider (Anthropic, OpenAI, Gemini), streaming en vivo,
registro declarativo de herramientas y compuertas de seguridad.
"""

bl_info = {
    "name": "Blender AI Agent",
    "author": "jjo64",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > AI Agent",
    "description": "Agente autónomo de IA con ejecución segura, checkpoints y soporte multimodal.",
    "warning": "",
    "doc_url": "https://github.com/jjo64/blender-ai-agent",
    "category": "3D View",
}

import sys
import os

# Asegurar que el directorio raíz de la extensión esté en sys.path
_addon_dir = os.path.dirname(os.path.abspath(__file__))
if _addon_dir not in sys.path:
    sys.path.insert(0, _addon_dir)

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, PointerProperty
from bpy.types import PropertyGroup

# Importar herramientas para forzar el auto-registro en el ToolRegistry
import blender_integration.tools.mesh_ops
import blender_integration.tools.material_ops
import blender_integration.tools.run_script

from blender_integration.threading_model import task_bridge, StreamChunk, WorkerResult, PendingAction
from ui.settings_panel import AIAgentPreferences
from ui.chat_widget import (
    AI_AGENT_OT_send_message,
    AI_AGENT_OT_resolve_approval,
    AI_AGENT_OT_restore_checkpoint,
    AI_AGENT_OT_create_checkpoint,
    AI_AGENT_OT_clear_chat,
)
from ui.main_panel import VIEW3D_PT_AIAgentMainPanel


# -------------------------------------------------------------------------
# Propiedades de Escena / UI
# -------------------------------------------------------------------------
class AIAgentSceneProperties(PropertyGroup):
    provider: EnumProperty(
        name="Proveedor",
        description="Proveedor de LLM a utilizar",
        items=[
            ('ANTHROPIC', "Anthropic (Claude 3.7)", "Claude 3.7 Sonnet con razonamiento y tool use"),
            ('OPENAI', "OpenAI (GPT-4o)", "GPT-4o con soporte multimodal"),
            ('GOOGLE', "Google (Gemini 2.0)", "Gemini 2.0 Flash / 1.5 Pro"),
        ],
        default='ANTHROPIC'
    )

    user_prompt: StringProperty(
        name="Instrucción",
        description="Instrucción en lenguaje natural para el agente",
        default=""
    )

    last_user_message: StringProperty(
        name="Último mensaje",
        default=""
    )

    streaming_response: StringProperty(
        name="Respuesta actual",
        default=""
    )

    status_message: StringProperty(
        name="Estado",
        default="Listo para recibir instrucciones."
    )

    auto_approve: BoolProperty(
        name="Auto-aprobar",
        description="Omite confirmación manual para herramientas de bajo riesgo",
        default=False
    )

    attach_viewport: BoolProperty(
        name="Adjuntar captura",
        description="Captura el 3D Viewport para análisis multimodal",
        default=False
    )

    is_running: BoolProperty(
        name="En ejecución",
        default=False
    )

    has_pending_action: BoolProperty(
        name="Acción pendiente",
        default=False
    )

    pending_action_desc: StringProperty(
        name="Descripción de acción pendiente",
        default=""
    )


# -------------------------------------------------------------------------
# Handlers del TaskBridge (Main Thread Callbacks)
# -------------------------------------------------------------------------
def on_stream_chunk_received(chunk: StreamChunk):
    if bpy.context and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "ai_agent_props"):
        props = bpy.context.scene.ai_agent_props
        props.streaming_response += chunk.text


def on_worker_result_received(result: WorkerResult):
    if bpy.context and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "ai_agent_props"):
        props = bpy.context.scene.ai_agent_props
        props.is_running = False
        if not result.success:
            props.status_message = f"Error: {result.content}"
        else:
            props.status_message = "Listo."
        if not props.streaming_response:
            props.streaming_response = result.content


def on_pending_action_received(action: PendingAction):
    if bpy.context and hasattr(bpy.context, "scene") and hasattr(bpy.context.scene, "ai_agent_props"):
        props = bpy.context.scene.ai_agent_props
        props.has_pending_action = True
        props.pending_action_desc = f"{action.tool_name}: {action.description}"


# -------------------------------------------------------------------------
# Registro y Desregistro
# -------------------------------------------------------------------------
classes = (
    AIAgentPreferences,
    AIAgentSceneProperties,
    AI_AGENT_OT_send_message,
    AI_AGENT_OT_resolve_approval,
    AI_AGENT_OT_restore_checkpoint,
    AI_AGENT_OT_create_checkpoint,
    AI_AGENT_OT_clear_chat,
    VIEW3D_PT_AIAgentMainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.ai_agent_props = PointerProperty(type=AIAgentSceneProperties)

    # Conectar listeners de streaming y resultados con el TaskBridge
    task_bridge.register_chunk_listener(on_stream_chunk_received)
    task_bridge.register_result_listener(on_worker_result_received)
    task_bridge.register_pending_action_listener(on_pending_action_received)


def unregister():
    task_bridge.cleanup()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, "ai_agent_props"):
        del bpy.types.Scene.ai_agent_props


if __name__ == "__main__":
    register()
