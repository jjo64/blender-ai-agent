"""
Blender AI Agent - Extension Entry Point
========================================
Asistente y Agente de Inteligencia Artificial para Blender con soporte Multi-Provider,
streaming en tiempo real, registro declarativo de herramientas y compuertas de seguridad.
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

import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty, IntProperty, FloatProperty, PointerProperty
from bpy.types import Panel, Operator, PropertyGroup, AddonPreferences

# -------------------------------------------------------------------------
# Preferencias del Add-on (Almacenamiento seguro de API Keys y Ajustes)
# -------------------------------------------------------------------------
class AIAgentPreferences(AddonPreferences):
    bl_idname = __package__ or "blender-ai-agent"

    anthropic_api_key: StringProperty(
        name="Anthropic API Key",
        description="API Key para Claude (Anthropic)",
        default="",
        subtype='PASSWORD'
    )
    
    openai_api_key: StringProperty(
        name="OpenAI API Key",
        description="API Key para GPT (OpenAI)",
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
        description="Límite máximo de turnos en el ReAct Loop por comando del usuario",
        default=10,
        min=1,
        max=30
    )

    def draw(self, context):
        layout = self.layout
        
        box = layout.box()
        box.label(text="Configuración de Credenciales (API Keys)", icon='LOCKED')
        box.prop(self, "anthropic_api_key")
        box.prop(self, "openai_api_key")
        box.prop(self, "google_api_key")
        
        box_limits = layout.box()
        box_limits.label(text="Límites de Ejecución y Seguridad", icon='PREFERENCES')
        box_limits.prop(self, "max_iterations")


# -------------------------------------------------------------------------
# Estado de la Escena / Sesión para la UI
# -------------------------------------------------------------------------
class AIAgentSceneProperties(PropertyGroup):
    provider: EnumProperty(
        name="Proveedor",
        description="Proveedor de LLM a utilizar",
        items=[
            ('ANTHROPIC', "Anthropic (Claude)", "Modelos de Anthropic como Claude 3.7 Sonnet"),
            ('OPENAI', "OpenAI (GPT)", "Modelos de OpenAI como GPT-4o"),
            ('GOOGLE', "Google (Gemini)", "Modelos de Google como Gemini 2.0 Flash / 1.5 Pro"),
        ],
        default='ANTHROPIC'
    )
    
    user_prompt: StringProperty(
        name="Instrucción",
        description="Instrucción en lenguaje natural para el agente",
        default=""
    )
    
    auto_approve: BoolProperty(
        name="Auto-aprobar acciones",
        description="Si está activo, las herramientas de bajo/medio riesgo no requerirán confirmación manual",
        default=False
    )
    
    status_message: StringProperty(
        name="Estado",
        description="Estado actual del agente",
        default="Listo para recibir instrucciones."
    )
    
    is_running: BoolProperty(
        name="En ejecución",
        description="Indica si el worker thread está procesando una instrucción",
        default=False
    )


# -------------------------------------------------------------------------
# Operadores de Interacción Básica (Placeholder / Inicialización)
# -------------------------------------------------------------------------
class WM_OT_AIAgentSendMessage(Operator):
    bl_idname = "ai_agent.send_message"
    bl_label = "Enviar Instrucción"
    bl_description = "Envía la instrucción al agente de IA para iniciar el bucle de razonamiento"

    def execute(self, context):
        props = context.scene.ai_agent_props
        if not props.user_prompt.strip():
            self.report({'WARNING'}, "Por favor ingresa una instrucción antes de enviar.")
            return {'CANCELLED'}
        
        props.status_message = f"Procesando: {props.user_prompt}"
        # Aquí se integrará con el threading_model y el AgentLoop
        self.report({'INFO'}, f"Instrucción enviada a {props.provider}: {props.user_prompt}")
        props.user_prompt = ""
        return {'FINISHED'}


# -------------------------------------------------------------------------
# Panel en 3D Viewport (Sidebar N-Panel)
# -------------------------------------------------------------------------
class VIEW3D_PT_AIAgentMainPanel(Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AI Agent'
    bl_label = "🤖 Blender AI Agent"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_agent_props
        
        # Selector de Proveedor
        col = layout.column(align=True)
        col.prop(props, "provider", text="Proveedor")
        
        # Estado y Costos (Preview)
        box_status = layout.box()
        box_status.label(text=f"Estado: {props.status_message}", icon='INFO')
        
        # Input de Instrucciones
        col_input = layout.column(align=True)
        col_input.prop(props, "user_prompt", text="")
        
        row_actions = col_input.row(align=True)
        row_actions.operator("ai_agent.send_message", text="Enviar", icon='PLAY')
        row_actions.prop(props, "auto_approve", text="Auto-aprobar", toggle=True)


# -------------------------------------------------------------------------
# Registro y Desregistro
# -------------------------------------------------------------------------
classes = (
    AIAgentPreferences,
    AIAgentSceneProperties,
    WM_OT_AIAgentSendMessage,
    VIEW3D_PT_AIAgentMainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.ai_agent_props = PointerProperty(type=AIAgentSceneProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    if hasattr(bpy.types.Scene, "ai_agent_props"):
        del bpy.types.Scene.ai_agent_props

if __name__ == "__main__":
    register()
