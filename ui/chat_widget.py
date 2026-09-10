"""
ui/chat_widget.py
=================
Operadores y lógica de interacción para el envío de mensajes, streaming en vivo,
resolución de aprobaciones (AuthGate) y gestión de checkpoints en Blender.
"""

from __future__ import annotations
import logging
import os
from typing import Optional

try:
    import bpy
    from bpy.types import Operator
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False
    Operator = object

from blender_integration.state_manager.checkpoints import checkpoint_manager
from blender_integration.threading_model import PendingAction, StreamChunk, WorkerResult, task_bridge
from blender_integration.viewport_capture import capture_viewport_png
from core.agent import AgentLoop, AgentResult
from core.scene_inspector import SceneInspector
from state.history import HistoryPersistence
from state.session import session_state

logger = logging.getLogger("BlenderAIAgent.UI")


class AI_AGENT_OT_send_message(Operator):
    """Envía la instrucción del usuario al agente de IA para iniciar el bucle ReAct."""
    bl_idname = "ai_agent.send_message"
    bl_label = "Enviar Instrucción"
    bl_description = "Inicia el procesamiento autónomo de la instrucción en segundo plano"

    def execute(self, context):
        props = context.scene.ai_agent_props
        prompt_text = props.user_prompt.strip()

        if not prompt_text:
            self.report({'WARNING'}, "Ingresa una instrucción antes de enviar.")
            return {'CANCELLED'}

        if props.is_running:
            self.report({'WARNING'}, "El agente ya está procesando una solicitud.")
            return {'CANCELLED'}

        # 1. Obtener preferencias y credenciales
        addon_prefs = context.preferences.addons[__package__.split('.')[0] if __package__ else "blender-ai-agent"].preferences
        provider_name = props.provider

        api_key = ""
        if provider_name == 'ANTHROPIC':
            api_key = addon_prefs.anthropic_api_key
        elif provider_name == 'OPENAI':
            api_key = addon_prefs.openai_api_key
        elif provider_name == 'GOOGLE':
            api_key = addon_prefs.google_api_key

        if not api_key:
            self.report({'ERROR'}, f"Configura la API Key para {provider_name} en las Preferencias del Add-on.")
            return {'CANCELLED'}

        # 2. Inicializar proveedor y estado
        try:
            provider = session_state.initialize_provider(provider_name, api_key)
        except Exception as ex:
            self.report({'ERROR'}, f"Error al inicializar proveedor: {str(ex)}")
            return {'CANCELLED'}

        session_state.auth_gate.auto_approve = props.auto_approve
        
        # 3. Capturar estado y crear checkpoint previo
        checkpoint_manager.create_checkpoint(label="pre_agent_action")
        scene_snapshot = SceneInspector.capture()

        # 4. Capturar viewport si multimodal está activo
        image_bytes = None
        if props.attach_viewport and provider.supports_vision():
            image_bytes = capture_viewport_png()

        props.is_running = True
        props.status_message = "Razonando..."
        props.streaming_response = ""
        props.last_user_message = prompt_text
        props.user_prompt = ""

        # 5. Función de trabajo en segundo plano
        def background_task():
            agent = AgentLoop(
                provider=provider,
                auth_gate=session_state.auth_gate,
                context_manager=session_state.context_manager,
                max_iterations=addon_prefs.max_iterations
            )

            # Notificación de acciones pendientes hacia el TaskBridge
            session_state.auth_gate.set_notification_callback(
                lambda pending: task_bridge.push_pending_action(PendingAction(
                    tool_name=pending.tool_name,
                    arguments=pending.arguments,
                    description=pending.description
                ))
            )

            def chunk_handler(chunk: StreamChunk):
                task_bridge.push_chunk(chunk)

            res: AgentResult = agent.run(
                user_prompt=prompt_text,
                image_bytes=image_bytes,
                scene_snapshot=scene_snapshot,
                yield_chunk=chunk_handler
            )

            # Registrar costo en el tracker de sesión
            if res.total_cost_usd > 0:
                props_cost = context.scene.ai_agent_props
                # Encolar resultado final
                task_bridge.push_result(WorkerResult(
                    success=res.success,
                    content=res.content,
                    error_type=res.error_type
                ))
            else:
                task_bridge.push_result(WorkerResult(
                    success=res.success,
                    content=res.content,
                    error_type=res.error_type
                ))

        # 6. Lanzar worker en TaskBridge
        task_bridge.start_worker(background_task)
        self.report({'INFO'}, "Instrucción despachada al agente de IA.")
        return {'FINISHED'}


class AI_AGENT_OT_resolve_approval(Operator):
    """Aprueba o rechaza una acción pausada por el Auth Gate."""
    bl_idname = "ai_agent.resolve_approval"
    bl_label = "Resolver Aprobación"
    bl_description = "Aprueba o cancela la acción pendiente requerida por el agente"

    approved: bpy.props.BoolProperty(name="Aprobado", default=True)

    def execute(self, context):
        props = context.scene.ai_agent_props
        session_state.auth_gate.resolve(self.approved)
        props.has_pending_action = False
        props.pending_action_desc = ""
        
        status_text = "Acción aprobada. Continuando..." if self.approved else "Acción rechazada."
        props.status_message = status_text
        self.report({'INFO'}, status_text)
        return {'FINISHED'}


class AI_AGENT_OT_restore_checkpoint(Operator):
    """Restaura la escena al último punto de control guardado."""
    bl_idname = "ai_agent.restore_checkpoint"
    bl_label = "Restaurar Checkpoint"
    bl_description = "Vuelve al estado de la escena previo a la última intervención"

    checkpoint_id: bpy.props.StringProperty(name="Checkpoint ID", default="")

    def execute(self, context):
        cps = checkpoint_manager.list_checkpoints()
        if not cps:
            self.report({'WARNING'}, "No hay checkpoints disponibles para restaurar.")
            return {'CANCELLED'}

        target_id = self.checkpoint_id or cps[-1].id
        success = checkpoint_manager.restore_checkpoint(target_id)
        
        if success:
            self.report({'INFO'}, "Escena restaurada exitosamente.")
        else:
            self.report({'ERROR'}, "Fallo al restaurar la escena.")
        return {'FINISHED'}


class AI_AGENT_OT_create_checkpoint(Operator):
    """Guarda manualmente un nuevo punto de restauración."""
    bl_idname = "ai_agent.create_checkpoint"
    bl_label = "Crear Checkpoint"
    bl_description = "Guarda una copia de seguridad instantánea de la escena"

    def execute(self, context):
        entry = checkpoint_manager.create_checkpoint(label="manual_snapshot")
        if entry:
            self.report({'INFO'}, f"Checkpoint creado: {entry.label}")
        else:
            self.report({'ERROR'}, "No se pudo crear el checkpoint.")
        return {'FINISHED'}


class AI_AGENT_OT_clear_chat(Operator):
    """Limpia el historial de conversación en la interfaz y en el gestor de contexto."""
    bl_idname = "ai_agent.clear_chat"
    bl_label = "Limpiar Chat"
    bl_description = "Reinicia la conversación manteniendo las decisiones técnicas fijas"

    def execute(self, context):
        props = context.scene.ai_agent_props
        session_state.reset()
        props.streaming_response = ""
        props.last_user_message = ""
        props.status_message = "Chat reiniciado. Listo."
        self.report({'INFO'}, "Historial reiniciado.")
        return {'FINISHED'}
