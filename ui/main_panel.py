"""
ui/main_panel.py
================
Panel principal del Agente de IA ubicado en el Sidebar (N-Panel) del 3D Viewport.
Renderiza el widget de costos, la conversación en streaming, las tarjetas de aprobación y los checkpoints.
"""

from __future__ import annotations
try:
    import bpy
    from bpy.types import Panel
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False
    Panel = object

from blender_integration.state_manager.checkpoints import checkpoint_manager
from state.session import session_state


class VIEW3D_PT_AIAgentMainPanel(Panel):
    """Panel lateral en el 3D Viewport para Blender AI Agent."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AI Agent'
    bl_label = "🤖 AI Agent (Producción)"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_agent_props
        tracker = session_state.cost_tracker

        # -------------------------------------------------------------
        # 1. Configuración de Proveedor y Modelo
        # -------------------------------------------------------------
        box_top = layout.box()
        row_prov = box_top.row(align=True)
        row_prov.prop(props, "provider", text="Proveedor")
        
        # -------------------------------------------------------------
        # 2. Widget de Costos en Tiempo Real
        # -------------------------------------------------------------
        box_cost = layout.box()
        row_cost = box_cost.row(align=True)
        row_cost.label(text=f"💰 Sesión: ${tracker.session_cost_usd:.4f}", icon='FUND')
        row_cost.label(text=f"Tokens: {tracker.session_input_tokens + tracker.session_output_tokens:,}")

        # Alerta de tarifas si están desactualizadas (>60 días)
        is_stale, warning_msg = tracker.check_prices_staleness(max_days=60)
        if is_stale and warning_msg:
            box_cost.label(text=warning_msg, icon='ERROR')

        # -------------------------------------------------------------
        # 3. Vista de Conversación y Streaming
        # -------------------------------------------------------------
        box_chat = layout.box()
        box_chat.label(text="Historial y Respuesta:", icon='TEXT')

        if props.last_user_message:
            box_user = box_chat.box()
            box_user.label(text=f"Tú: {props.last_user_message}", icon='USER')

        if props.streaming_response or props.status_message:
            box_agent = box_chat.box()
            # Mostrar estado actual o texto de streaming
            if props.is_running:
                box_agent.label(text=f"⏳ {props.status_message}", icon='SORTTIME')
            
            if props.streaming_response:
                for line in props.streaming_response.splitlines()[-10:]:
                    box_agent.label(text=line)

        # -------------------------------------------------------------
        # 4. Tarjeta de Aprobación de Acciones (Auth Gate)
        # -------------------------------------------------------------
        if props.has_pending_action:
            box_auth = layout.box()
            box_auth.alert = True
            box_auth.label(text="⚠️ Acción requerida:", icon='QUESTION')
            box_auth.label(text=props.pending_action_desc)
            
            row_btns = box_auth.row(align=True)
            op_app = row_btns.operator("ai_agent.resolve_approval", text="Aprobar", icon='CHECKMARK')
            op_app.approved = True
            op_rej = row_btns.operator("ai_agent.resolve_approval", text="Rechazar", icon='CANCEL')
            op_rej.approved = False

        # -------------------------------------------------------------
        # 5. Entrada de Texto y Acciones
        # -------------------------------------------------------------
        col_input = layout.column(align=True)
        col_input.prop(props, "user_prompt", text="", icon='CONSOLE')

        row_toggles = col_input.row(align=True)
        row_toggles.prop(props, "attach_viewport", text="Adjuntar Vista 3D", icon='CAMERA_DATA')
        row_toggles.prop(props, "auto_approve", text="Auto-aprobar", icon='CHECKBOX_HLT')

        row_send = col_input.row(align=True)
        row_send.enabled = not props.is_running
        row_send.operator("ai_agent.send_message", text="Enviar Instrucción", icon='PLAY')
        row_send.operator("ai_agent.clear_chat", text="Limpiar", icon='TRASH')

        # -------------------------------------------------------------
        # 6. Checkpoints de Seguridad (Rollback)
        # -------------------------------------------------------------
        box_cp = layout.box()
        cps = checkpoint_manager.list_checkpoints()
        row_cp_header = box_cp.row(align=True)
        row_cp_header.label(text=f"Checkpoints ({len(cps)})", icon='FILE_BACKUP')
        
        row_cp_actions = box_cp.row(align=True)
        row_cp_actions.operator("ai_agent.create_checkpoint", text="Guardar", icon='ADD')
        if cps:
            row_cp_actions.operator("ai_agent.restore_checkpoint", text="Restaurar Último", icon='LOOP_BACK')
