"""
blender_integration/tools/material_ops.py
=========================================
Herramientas declarativas para crear, configurar y asignar materiales Principled BSDF en Blender.
"""

from __future__ import annotations
import logging
from typing import List, Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

from core.tool_registry import tool

logger = logging.getLogger("BlenderAIAgent.MaterialOps")


@tool(
    name="create_and_apply_material",
    description="Crea un material basado en Principled BSDF (con color base, rugosidad, metalicidad y emisión) y lo asigna al objeto indicado.",
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Nombre del objeto al cual aplicar el material."
            },
            "material_name": {
                "type": "string",
                "description": "Nombre que se le dará al material (ej. 'Gold_Metal', 'Glass_Blue')."
            },
            "base_color": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Color RGBA en rango [0.0 - 1.0] (ej. [1.0, 0.84, 0.0, 1.0] para dorado)."
            },
            "roughness": {
                "type": "number",
                "description": "Nivel de rugosidad entre 0.0 (espejo/brillante) y 1.0 (mate/áspero)."
            },
            "metallic": {
                "type": "number",
                "description": "Factor metálico entre 0.0 (dieléctrico/plástico) y 1.0 (metal puro)."
            },
            "emission_color": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Color de emisión RGBA [r, g, b, 1.0] si el material emite luz."
            },
            "emission_strength": {
                "type": "number",
                "description": "Intensidad de la emisión de luz."
            }
        },
        "required": ["object_name", "material_name"]
    }
)
def create_and_apply_material(
    object_name: str,
    material_name: str,
    base_color: Optional[List[float]] = None,
    roughness: float = 0.5,
    metallic: float = 0.0,
    emission_color: Optional[List[float]] = None,
    emission_strength: float = 0.0
) -> str:
    color_rgba = tuple(base_color) if base_color and len(base_color) >= 3 else (0.8, 0.8, 0.8, 1.0)
    if len(color_rgba) == 3:
        color_rgba = (color_rgba[0], color_rgba[1], color_rgba[2], 1.0)

    if not BLENDER_AVAILABLE:
        return (
            f"[MOCK] Material '{material_name}' aplicado a '{object_name}' "
            f"(color={color_rgba}, roughness={roughness}, metallic={metallic})."
        )

    obj = bpy.data.objects.get(object_name)
    if not obj:
        raise ValueError(f"No se encontró el objeto '{object_name}' en la escena para asignar el material.")

    # Crear o recuperar material existente
    mat = bpy.data.materials.get(material_name)
    if not mat:
        mat = bpy.data.materials.new(name=material_name)
        mat.use_nodes = True

    # Configurar nodos Principled BSDF
    nodes = mat.node_tree.nodes
    principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)

    if principled:
        # Base Color
        if "Base Color" in principled.inputs:
            principled.inputs["Base Color"].default_value = color_rgba

        # Roughness
        if "Roughness" in principled.inputs:
            principled.inputs["Roughness"].default_value = roughness

        # Metallic
        if "Metallic" in principled.inputs:
            principled.inputs["Metallic"].default_value = metallic

        # Emission
        if emission_strength > 0.0:
            if "Emission Color" in principled.inputs and emission_color:
                em_rgba = (emission_color[0], emission_color[1], emission_color[2], 1.0) if len(emission_color) == 3 else tuple(emission_color)
                principled.inputs["Emission Color"].default_value = em_rgba
            if "Emission Strength" in principled.inputs:
                principled.inputs["Emission Strength"].default_value = emission_strength

    # Asignar a la ranura de material del objeto
    if obj.data and hasattr(obj.data, "materials"):
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[0] = mat

    return f"Material '{mat.name}' configurado y asignado exitosamente al objeto '{object_name}'."
