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


def get_addon_preferences(context):
    """Busca las preferencias del Addon/Extensión de forma segura en Blender."""
    pkg = __package__ or "blender_ai_agent"
    if pkg in context.preferences.addons:
        return context.preferences.addons[pkg].preferences
    for name, addon in context.preferences.addons.items():
        if "blender_ai_agent" in name or name.endswith("blender_ai_agent"):
            return addon.preferences
    for addon in context.preferences.addons.values():
        if hasattr(addon.preferences, "anthropic_api_key"):
            return addon.preferences
    return None


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
        addon_prefs = get_addon_preferences(context)
        if not addon_prefs:
            self.report({'ERROR'}, "No se pudieron cargar las Preferencias de Blender AI Agent.")
            return {'CANCELLED'}

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
        selected_model = props.model_selection if hasattr(props, "model_selection") and props.model_selection != 'default' else None
        try:
            provider = session_state.initialize_provider(provider_name, api_key, model_name=selected_model)
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


class AI_AGENT_OT_open_preferences(Operator):
    """Abre la ventana de Preferencias de Blender directamente en la configuración del Add-on."""
    bl_idname = "ai_agent.open_preferences"
    bl_label = "Configurar API Keys"
    bl_description = "Abre las preferencias de Blender para ingresar las claves de API"

    def execute(self, context):
        bpy.ops.screen.userpref_show('INVOKE_DEFAULT')
        context.preferences.active_section = 'ADDONS'
        return {'FINISHED'}


class AI_AGENT_OT_open_floating_dialog(Operator):
    """Abre una ventana flotante modal amplia para interactuar con el chat cómodamente."""
    bl_idname = "ai_agent.open_floating_dialog"
    bl_label = "🤖 Blender AI Agent - Consola Ampliada"
    bl_description = "Abre una ventana flotante más grande para ver el historial y chatear con comodidad"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=650)

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_agent_props
        tracker = session_state.cost_tracker

        # Cabecera con selector y costos
        row_top = layout.row(align=True)
        row_top.prop(props, "provider", text="Proveedor")
        row_top.prop(props, "model_selection", text="Modelo")
        row_top.label(text=f"💰 Sesión: ${tracker.session_cost_usd:.4f}", icon='FUND')

        # Vista de chat expandida
        box_chat = layout.box()
        box_chat.scale_y = 1.2
        if props.last_user_message:
            box_user = box_chat.box()
            box_user.label(text=f"Tú: {props.last_user_message}", icon='USER')
        
        if props.streaming_response or props.status_message:
            box_res = box_chat.box()
            if props.is_running:
                box_res.label(text=f"⏳ {props.status_message}", icon='SORTTIME')
            for line in (props.streaming_response or "").splitlines():
                box_res.label(text=line)

        # Entrada de texto
        col_in = layout.column(align=True)
        col_in.prop(props, "user_prompt", text="Instrucción", icon='CONSOLE')
        
        row_opts = col_in.row(align=True)
        row_opts.prop(props, "attach_viewport", text="Adjuntar Vista 3D", icon='CAMERA_DATA')
        row_opts.prop(props, "auto_approve", text="Auto-aprobar", icon='CHECKBOX_HLT')

        row_actions = col_in.row(align=True)
        row_actions.operator("ai_agent.send_message", text="Enviar Instrucción", icon='PLAY')
        row_actions.operator("ai_agent.clear_chat", text="Limpiar Historial", icon='TRASH')

    def execute(self, context):
        return {'FINISHED'}
