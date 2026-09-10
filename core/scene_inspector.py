"""
core/scene_inspector.py
=======================
Inspección semántica y eficiente del estado actual de la escena de Blender.
Genera un SceneSnapshot con la información estrictamente necesaria para que el LLM
pueda actuar sin saturar el context window ni filtrar arrays masivos de vértices.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False


@dataclass
class SceneSnapshot:
    """Representación resumida y optimizada de la escena 3D."""
    active_object: Optional[str] = None
    selected_objects: List[str] = field(default_factory=list)
    object_count: int = 0
    mode: str = "OBJECT"
    active_mesh_stats: Optional[Dict[str, int]] = None
    active_materials: List[str] = field(default_factory=list)
    unit_system: str = "METRIC"

    def to_prompt_context(self) -> str:
        """
        Formatea el snapshot en un bloque de texto compacto listo para ser
        inyectado en el system prompt o en el mensaje de contexto del agente.
        """
        lines = ["[ESTADO ACTUAL DE LA ESCENA]"]
        lines.append(f"- Modo de interacción: {self.mode}")
        lines.append(f"- Objetos totales en la escena: {self.object_count}")
        lines.append(f"- Sistema de unidades: {self.unit_system}")
        
        if self.active_object:
            lines.append(f"- Objeto activo: '{self.active_object}'")
        else:
            lines.append("- Objeto activo: Ninguno")

        if self.selected_objects:
            lines.append(f"- Objetos seleccionados ({len(self.selected_objects)}): {', '.join(self.selected_objects[:10])}")
            if len(self.selected_objects) > 10:
                lines.append(f"  (...y {len(self.selected_objects) - 10} más)")
        else:
            lines.append("- Objetos seleccionados: Ninguno")

        if self.active_mesh_stats:
            stats = self.active_mesh_stats
            lines.append(
                f"- Topología de '{self.active_object}': "
                f"{stats.get('vertices', 0)} vértices, "
                f"{stats.get('faces', 0)} caras "
                f"({stats.get('ngons', 0)} n-gons)"
            )

        if self.active_materials:
            lines.append(f"- Materiales en objeto activo: {', '.join(self.active_materials)}")

        lines.append("[FIN DEL ESTADO]")
        return "\n".join(lines)


class SceneInspector:
    """Inspector encargado de extraer el SceneSnapshot desde bpy o generar mocks."""

    @staticmethod
    def capture() -> SceneSnapshot:
        """
        Captura el estado actual. 
        IMPORTANTE: En Blender, esta función debe ejecutarse en el Main Thread antes de iniciar el Worker.
        """
        if not BLENDER_AVAILABLE:
            return SceneSnapshot(
                active_object="MockCube",
                selected_objects=["MockCube"],
                object_count=1,
                mode="OBJECT",
                active_mesh_stats={"vertices": 8, "edges": 12, "faces": 6, "ngons": 0},
                active_materials=["DefaultMaterial"],
                unit_system="METRIC"
            )

        context = bpy.context
        active_obj = context.active_object
        selected_objs = [obj.name for obj in context.selected_objects]
        obj_count = len(context.scene.objects)
        mode = context.mode

        mesh_stats = None
        materials = []

        if active_obj:
            # Obtener nombres de materiales asignados
            materials = [slot.material.name for slot in active_obj.material_slots if slot.material]

            # Si es una malla, extraer estadísticas ligeras
            if active_obj.type == 'MESH' and active_obj.data:
                mesh = active_obj.data
                ngons = sum(1 for poly in mesh.polygons if len(poly.vertices) > 4)
                mesh_stats = {
                    "vertices": len(mesh.vertices),
                    "edges": len(mesh.edges),
                    "faces": len(mesh.polygons),
                    "ngons": ngons
                }

        unit_sys = context.scene.unit_settings.system if hasattr(context.scene, "unit_settings") else "METRIC"

        return SceneSnapshot(
            active_object=active_obj.name if active_obj else None,
            selected_objects=selected_objs,
            object_count=obj_count,
            mode=mode,
            active_mesh_stats=mesh_stats,
            active_materials=materials,
            unit_system=unit_sys
        )
