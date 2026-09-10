"""
core/security/auth_gate.py
==========================
Compuerta de autorización y supervisión humana para acciones riesgosas.
Utiliza threading.Event para suspender el Worker thread sin consumo de CPU
mientras el usuario confirma o rechaza una acción desde la UI de Blender.
"""

from __future__ import annotations
import threading
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("BlenderAIAgent.AuthGate")


@dataclass
class PendingApproval:
    """Información de la acción que requiere autorización."""
    action_id: str
    tool_name: str
    arguments: Dict[str, Any]
    description: str


class AuthGate:
    """
    Controlador de compuerta de seguridad interactivo.
    """

    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self._approval_event = threading.Event()
        self._approved: bool = False
        self._current_pending: Optional[PendingApproval] = None
        self._notification_callback: Optional[Callable[[PendingApproval], None]] = None

    def set_notification_callback(self, callback: Callable[[PendingApproval], None]) -> None:
        """Establece el callback utilizado para notificar a la UI sobre una acción pendiente."""
        self._notification_callback = callback

    def request_approval(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        description: str,
        timeout: float = 300.0
    ) -> bool:
        """
        Solicita aprobación para ejecutar una herramienta.
        Si auto_approve es True, aprueba inmediatamente.
        De lo contrario, suspende el hilo actual hasta que la UI invoque resolve() o expire el timeout.
        """
        if self.auto_approve:
            logger.info("Auto-aprobando acción '%s' (auto_approve activo).", tool_name)
            return True

        self._approval_event.clear()
        self._approved = False
        
        pending = PendingApproval(
            action_id=f"act_{id(arguments)}",
            tool_name=tool_name,
            arguments=arguments,
            description=description
        )
        self._current_pending = pending

        if self._notification_callback:
            self._notification_callback(pending)

        logger.info("Esperando autorización del usuario para '%s' (timeout: %ss)...", tool_name, timeout)
        was_signaled = self._approval_event.wait(timeout=timeout)

        if not was_signaled:
            logger.warning("Tiempo de espera agotado (timeout) para la acción '%s'. Rechazando por seguridad.", tool_name)
            self._approved = False

        self._current_pending = None
        return self._approved

    def resolve(self, approved: bool) -> None:
        """
        Método invocado por la UI (Main Thread) cuando el usuario pulsa Aprobar o Rechazar.
        Despierta inmediatamente al Worker thread suspendido.
        """
        self._approved = approved
        logger.info("Resolución de usuario recibida: %s", "APROBADO" if approved else "RECHAZADO")
        self._approval_event.set()

    @property
    def current_pending(self) -> Optional[PendingApproval]:
        """Retorna la acción actualmente pendiente de resolución, si existe."""
        return self._current_pending
