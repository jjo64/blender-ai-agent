"""
state/history.py
================
Persistencia temporal del historial de conversación para supervivencia a reinicios o crashes.
Almacena un archivo JSON en bpy.app.tempdir indexado por el nombre del archivo .blend activo.
"""

from __future__ import annotations
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

logger = logging.getLogger("BlenderAIAgent.History")


class HistoryPersistence:
    """Maneja el guardado y recuperación del historial en disco temporal."""

    @staticmethod
    def _get_history_filepath(blend_name: Optional[str] = None) -> str:
        """Determina la ruta del archivo JSON según el .blend activo."""
        temp_dir = bpy.app.tempdir if BLENDER_AVAILABLE and hasattr(bpy.app, "tempdir") else tempfile.gettempdir()
        
        if not blend_name:
            if BLENDER_AVAILABLE and bpy.data.filepath:
                blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
            else:
                blend_name = "untitled_session"

        clean_name = "".join(c for c in blend_name if c.isalnum() or c in ('_', '-'))
        filename = f"{clean_name}_agent_history.json"
        return os.path.join(temp_dir, filename)

    @classmethod
    def save(cls, messages: List[Dict[str, Any]], blend_name: Optional[str] = None) -> None:
        """Serializa la lista de mensajes en un archivo JSON en tempdir."""
        target_path = cls._get_history_filepath(blend_name)
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            logger.info("Historial persistido en: %s", target_path)
        except Exception as e:
            logger.error("No se pudo guardar el historial en %s: %s", target_path, str(e))

    @classmethod
    def load(cls, blend_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recupera el historial previo guardado si existe."""
        target_path = cls._get_history_filepath(blend_name)
        if not os.path.exists(target_path):
            return []

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info("Historial recuperado desde: %s (%d mensajes)", target_path, len(data))
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("Error al cargar historial desde %s: %s", target_path, str(e))
            return []
