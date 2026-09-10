"""
blender_integration/state_manager/checkpoints.py
================================================
Gestor de puntos de restauración (Checkpoints) automáticos y manuales para Blender.
Almacena snapshots incrementales en bpy.app.tempdir aplicando una política FIFO de retención.
"""

from __future__ import annotations
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

logger = logging.getLogger("BlenderAIAgent.Checkpoints")


@dataclass
class CheckpointEntry:
    """Información de un snapshot registrado."""
    id: str
    filepath: str
    label: str
    timestamp: float


class CheckpointManager:
    """Administrador de copias de seguridad temporales de la escena de Blender."""

    MAX_CHECKPOINTS = 15

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir:
            self.storage_dir = storage_dir
        elif BLENDER_AVAILABLE and hasattr(bpy.app, "tempdir"):
            self.storage_dir = os.path.join(bpy.app.tempdir, "ai_agent_checkpoints")
        else:
            self.storage_dir = os.path.join(tempfile.gettempdir(), "blender_ai_agent_cp")

        os.makedirs(self.storage_dir, exist_ok=True)
        self.checkpoints: List[CheckpointEntry] = []

    def create_checkpoint(self, label: str = "auto") -> Optional[CheckpointEntry]:
        """
        Guarda un snapshot de la escena actual sin interferir con el archivo de trabajo principal.
        Aplica política FIFO eliminando el más antiguo si se supera MAX_CHECKPOINTS.
        """
        ts = int(time.time())
        clean_label = "".join(c for c in label if c.isalnum() or c in ('_', '-'))[:20]
        filename = f"agy_cp_{ts}_{clean_label}.blend"
        filepath = os.path.join(self.storage_dir, filename)

        if BLENDER_AVAILABLE:
            try:
                # Guardar copia exacta de la escena actual
                bpy.ops.wm.save_as_mainfile(filepath=filepath, copy=True)
            except Exception as e:
                logger.error("Error al guardar checkpoint en '%s': %s", filepath, str(e))
                return None
        else:
            # Creación de archivo mock para pruebas
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"MOCK_CHECKPOINT_{clean_label}")

        entry = CheckpointEntry(
            id=f"cp_{ts}",
            filepath=filepath,
            label=label,
            timestamp=time.time()
        )
        self.checkpoints.append(entry)

        # Aplicar política de retención FIFO
        while len(self.checkpoints) > self.MAX_CHECKPOINTS:
            oldest = self.checkpoints.pop(0)
            if os.path.exists(oldest.filepath):
                try:
                    os.remove(oldest.filepath)
                    logger.info("Checkpoint antiguo purgado: %s", oldest.filepath)
                except OSError:
                    pass

        logger.info("Checkpoint creado exitosamente: %s", entry.filepath)
        return entry

    def restore_checkpoint(self, checkpoint_id_or_path: str) -> bool:
        """Restaura la escena de Blender al estado guardado en el checkpoint."""
        target_path = None
        for cp in self.checkpoints:
            if cp.id == checkpoint_id_or_path or cp.filepath == checkpoint_id_or_path:
                target_path = cp.filepath
                break

        if not target_path and os.path.exists(checkpoint_id_or_path):
            target_path = checkpoint_id_or_path

        if not target_path or not os.path.exists(target_path):
            logger.error("No se encontró el archivo de checkpoint: %s", checkpoint_id_or_path)
            return False

        if BLENDER_AVAILABLE:
            try:
                bpy.ops.wm.open_mainfile(filepath=target_path)
                logger.info("Escena restaurada desde: %s", target_path)
                return True
            except Exception as e:
                logger.error("Error al restaurar checkpoint '%s': %s", target_path, str(e))
                return False
        else:
            logger.info("[MOCK] Escena restaurada desde: %s", target_path)
            return True

    def list_checkpoints(self) -> List[CheckpointEntry]:
        """Retorna la lista ordenada de snapshots disponibles."""
        return list(self.checkpoints)

    def cleanup(self) -> None:
        """Elimina todos los archivos temporales creados por el manager."""
        for cp in self.checkpoints:
            if os.path.exists(cp.filepath):
                try:
                    os.remove(cp.filepath)
                except OSError:
                    pass
        self.checkpoints.clear()


# Instancia global del gestor de checkpoints
checkpoint_manager = CheckpointManager()
