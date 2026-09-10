"""
blender_integration/viewport_capture.py
=======================================
Captura visual del 3D Viewport para soporte Multimodal (VLM).
Genera un buffer en memoria con la imagen en formato PNG para enviar a GPT-4o / Gemini / Claude.
"""

from __future__ import annotations
import logging
import os
import tempfile
from typing import Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

logger = logging.getLogger("BlenderAIAgent.ViewportCapture")


def capture_viewport_png() -> Optional[bytes]:
    """
    Captura una captura de pantalla del Viewport 3D activo y retorna sus bytes en PNG.
    Debe invocarse desde el Main Thread de Blender antes de iniciar el Worker de IA.
    """
    if not BLENDER_AVAILABLE:
        # Mock de 1x1 PNG transparente para pruebas
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    temp_path = os.path.join(tempfile.gettempdir(), f"agy_view_{os.getpid()}.png")

    try:
        # Encontrar área 3D Viewport
        area_3d = None
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area_3d = area
                    break
            if area_3d:
                break

        # Ejecutar screenshot de la ventana
        bpy.ops.screen.screenshot(filepath=temp_path, check_existing=False)

        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                img_data = f.read()
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return img_data
        else:
            logger.warning("No se pudo generar la captura en %s", temp_path)
            return None

    except Exception as e:
        logger.error("Error al capturar el viewport de Blender: %s", str(e))
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return None
