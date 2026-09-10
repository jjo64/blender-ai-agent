"""
blender_integration/tools/mesh_ops.py
=====================================
Herramientas declarativas para la creación y manipulación de mallas en Blender.
Todas las operaciones están decoradas con @tool para auto-registro en el ToolRegistry.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

try:
    import bpy
    import mathutils
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

from core.tool_registry import tool

logger = logging.getLogger("BlenderAIAgent.MeshOps")


@tool(
    name="create_primitive",
    description="Crea una malla primitiva básica en la escena 3D (cube, uv_sphere, cylinder, cone, plane, torus, monkey).",
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "primitive_type": {
                "type": "string",
                "enum": ["cube", "uv_sphere", "ico_sphere", "cylinder", "cone", "plane", "torus", "monkey"],
                "description": "Tipo de primitiva geométrica a generar."
            },
            "name": {
                "type": "string",
                "description": "Nombre que se le asignará al objeto creado."
            },
            "location": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Coordenadas de posición [x, y, z] en metros. Por defecto [0, 0, 0]."
            },
            "scale": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Factores de escala [x, y, z]. Por defecto [1, 1, 1]."
            },
            "size": {
                "type": "number",
                "description": "Dimensión o radio inicial de la primitiva."
            }
        },
        "required": ["primitive_type"]
    }
)
def create_primitive(
    primitive_type: str,
    name: Optional[str] = None,
    location: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    size: float = 2.0
) -> str:
    loc = tuple(location) if location and len(location) == 3 else (0.0, 0.0, 0.0)
    sc = tuple(scale) if scale and len(scale) == 3 else (1.0, 1.0, 1.0)
    ptype = primitive_type.lower()

    if not BLENDER_AVAILABLE:
        return f"[MOCK] Primitiva '{ptype}' creada con nombre '{name or ptype}' en posición {loc}."

    # Mapeo a operadores nativos de Blender
    if ptype == "cube":
        bpy.ops.mesh.primitive_cube_add(size=size, location=loc, scale=sc)
    elif ptype == "uv_sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2.0, location=loc, scale=sc)
    elif ptype == "ico_sphere":
        bpy.ops.mesh.primitive_ico_sphere_add(radius=size / 2.0, location=loc, scale=sc)
    elif ptype == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(radius=size / 2.0, depth=size, location=loc, scale=sc)
    elif ptype == "cone":
        bpy.ops.mesh.primitive_cone_add(radius1=size / 2.0, depth=size, location=loc, scale=sc)
    elif ptype == "plane":
        bpy.ops.mesh.primitive_plane_add(size=size, location=loc, scale=sc)
    elif ptype == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=size / 2.0, minor_radius=size / 8.0, location=loc)
    elif ptype == "monkey":
        bpy.ops.mesh.primitive_monkey_add(size=size, location=loc, scale=sc)
    else:
        raise ValueError(f"Tipo de primitiva '{primitive_type}' no reconocido.")

    obj = bpy.context.active_object
    if name and obj:
        obj.name = name

    final_name = obj.name if obj else ptype
    return f"Objeto '{final_name}' ({ptype}) creado exitosamente en {loc} con escala {sc}."


@tool(
    name="apply_modifier",
    description="Agrega y configura un modificador en el objeto especificado (ej. SUBSURF, BEVEL, SOLIDIFY, DECIMATE, MIRROR).",
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Nombre del objeto en la escena al que se le aplicará el modificador."
            },
            "modifier_type": {
                "type": "string",
                "enum": ["SUBSURF", "BEVEL", "SOLIDIFY", "DECIMATE", "MIRROR", "BOOLEAN", "SMOOTH"],
                "description": "Tipo de modificador de Blender a agregar."
            },
            "properties": {
                "type": "object",
                "description": "Diccionario de propiedades (ej: {'levels': 2} para SUBSURF, o {'width': 0.1, 'segments': 3} para BEVEL)."
            }
        },
        "required": ["object_name", "modifier_type"]
    }
)
def apply_modifier(
    object_name: str,
    modifier_type: str,
    properties: Optional[Dict[str, Any]] = None
) -> str:
    mtype = modifier_type.upper()
    props = properties or {}

    if not BLENDER_AVAILABLE:
        return f"[MOCK] Modificador '{mtype}' aplicado en '{object_name}' con propiedades: {props}."

    obj = bpy.data.objects.get(object_name)
    if not obj:
        raise ValueError(f"No se encontró el objeto '{object_name}' en la escena actual.")

    mod_name = f"{mtype.lower()}_ai"
    mod = obj.modifiers.new(name=mod_name, type=mtype)

    # Configuración de propiedades conocidas
    for key, value in props.items():
        if hasattr(mod, key):
            try:
                setattr(mod, key, value)
            except Exception as e:
                logger.warning("No se pudo asignar propiedad '%s'=%s: %s", key, value, str(e))

    return f"Modificador '{mtype}' ({mod.name}) agregado exitosamente al objeto '{object_name}'."


@tool(
    name="transform_object",
    description="Modifica la posición (location), rotación (rotation en radianes) o escala (scale) de un objeto existente.",
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Nombre del objeto a transformar."
            },
            "location": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Nuevas coordenadas [x, y, z] en metros."
            },
            "rotation_euler": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Nueva rotación Euler [x, y, z] en radianes."
            },
            "scale": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Nuevos factores de escala [x, y, z]."
            }
        },
        "required": ["object_name"]
    }
)
def transform_object(
    object_name: str,
    location: Optional[List[float]] = None,
    rotation_euler: Optional[List[float]] = None,
    scale: Optional[List[float]] = None
) -> str:
    if not BLENDER_AVAILABLE:
        return f"[MOCK] Objeto '{object_name}' transformado (loc={location}, rot={rotation_euler}, scale={scale})."

    obj = bpy.data.objects.get(object_name)
    if not obj:
        raise ValueError(f"No se encontró el objeto '{object_name}' en la escena.")

    if location and len(location) == 3:
        obj.location = location
    if rotation_euler and len(rotation_euler) == 3:
        obj.rotation_euler = rotation_euler
    if scale and len(scale) == 3:
        obj.scale = scale

    return f"Transformaciones aplicadas a '{object_name}' exitosamente."


@tool(
    name="delete_object",
    description="Elimina permanentemente un objeto de la escena. REQUIERE AUTORIZACIÓN.",
    requires_approval=True,
    parameters={
        "type": "object",
        "properties": {
            "object_name": {
                "type": "string",
                "description": "Nombre del objeto a eliminar."
            }
        },
        "required": ["object_name"]
    }
)
def delete_object(object_name: str) -> str:
    if not BLENDER_AVAILABLE:
        return f"[MOCK] Objeto '{object_name}' eliminado de la escena."

    obj = bpy.data.objects.get(object_name)
    if not obj:
        raise ValueError(f"No se encontró el objeto '{object_name}' para eliminar.")

    bpy.data.objects.remove(obj, do_unlink=True)
    return f"Objeto '{object_name}' eliminado definitivamente de la escena."
