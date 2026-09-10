"""
blender_integration/threading_model.py
======================================
Modelo de concurrencia seguro para Blender.
Permite ejecutar llamadas de red y loops de agentes en un hilo de fondo (Worker)
y despachar resultados y chunks de streaming al hilo principal de Blender (Main Thread)
a través de una cola thread-safe (queue.Queue) y bpy.app.timers.
"""

from __future__ import annotations
import queue
import threading
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    import bpy
    BLENDER_AVAILABLE = True
except ImportError:
    BLENDER_AVAILABLE = False

try:
    from ..core.providers.base import ErrorType, LLMResponse, StreamChunk
except ImportError:
    from core.providers.base import ErrorType, LLMResponse, StreamChunk

logger = logging.getLogger("BlenderAIAgent.Threading")


@dataclass
class WorkerResult:
    """Contrato final enviado a la UI al concluir un proceso en segundo plano."""
    success: bool
    content: str
    error_type: Optional[ErrorType] = None
    is_recoverable: bool = False
    response: Optional[LLMResponse] = None


@dataclass
class PendingAction:
    """Acción que requiere confirmación explícita del usuario vía Auth Gate."""
    tool_name: str
    arguments: Dict[str, Any]
    description: str


@dataclass
class MainThreadExecutionRequest:
    """Solicitud de ejecución síncrona en el hilo principal de Blender."""
    func: Callable[..., Any]
    args: tuple
    kwargs: dict
    event: threading.Event
    result_holder: Dict[str, Any]


class TaskBridge:
    """
    Puente de comunicación bidireccional y seguro entre el Worker Thread y el Main Thread de Blender.
    """
    def __init__(self):
        self.message_queue: queue.Queue = queue.Queue()
        self.active_thread: Optional[threading.Thread] = None
        self._is_timer_registered = False
        self._on_chunk_callbacks: List[Callable[[StreamChunk], None]] = []
        self._on_result_callbacks: List[Callable[[WorkerResult], None]] = []
        self._on_pending_action_callbacks: List[Callable[[PendingAction], None]] = []

    def register_chunk_listener(self, callback: Callable[[StreamChunk], None]) -> None:
        """Registra un callback para procesar tokens entrantes de streaming."""
        self._on_chunk_callbacks.append(callback)

    def register_result_listener(self, callback: Callable[[WorkerResult], None]) -> None:
        """Registra un callback para procesar el resultado final de la ejecución."""
        self._on_result_callbacks.append(callback)

    def register_pending_action_listener(self, callback: Callable[[PendingAction], None]) -> None:
        """Registra un callback para notificar a la UI sobre una acción que requiere aprobación."""
        self._on_pending_action_callbacks.append(callback)

    def start_worker(self, target: Callable[..., Any], args: tuple = (), kwargs: Optional[dict] = None) -> None:
        """
        Inicia una tarea en un hilo demonio secundario y asegura que el timer de Blender esté activo.
        """
        if kwargs is None:
            kwargs = {}

        if self.is_running():
            logger.warning("Un worker ya está en ejecución. Esperando su finalización.")
            return

        self.active_thread = threading.Thread(
            target=self._run_wrapper,
            args=(target, args, kwargs),
            daemon=True,
            name="AIAgent_WorkerThread"
        )
        self.active_thread.start()

        self._ensure_timer_registered()

    def is_running(self) -> bool:
        """Retorna True si hay un hilo de fondo activo."""
        return self.active_thread is not None and self.active_thread.is_alive()

    def push_chunk(self, chunk: StreamChunk) -> None:
        """Método seguro llamado desde el Worker para encolar un fragmento de texto."""
        self.message_queue.put(chunk)

    def push_result(self, result: WorkerResult) -> None:
        """Método seguro llamado desde el Worker para encolar el resultado final."""
        self.message_queue.put(result)

    def push_pending_action(self, action: PendingAction) -> None:
        """Método seguro llamado desde el Worker para encolar una acción pendiente de aprobación."""
        self.message_queue.put(action)

    def run_in_main_thread(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Ejecuta una función en el hilo principal de Blender de manera síncrona y segura.
        Si se invoca desde el hilo principal o fuera de Blender, se ejecuta directamente.
        """
        if not BLENDER_AVAILABLE or threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)

        event = threading.Event()
        result_holder: Dict[str, Any] = {}
        req = MainThreadExecutionRequest(
            func=func,
            args=args,
            kwargs=kwargs,
            event=event,
            result_holder=result_holder
        )

        self.message_queue.put(req)
        self._ensure_timer_registered()

        # Esperar a que el Main Thread ejecute la función
        if not event.wait(timeout=120.0):
            raise TimeoutError("Tiempo de espera agotado esperando ejecución en el hilo principal de Blender.")

        if "error" in result_holder:
            raise result_holder["error"]

        return result_holder.get("result")

    def _run_wrapper(self, target: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        """Envoltorio de ejecución segura con captura de excepciones no controladas."""
        try:
            target(*args, **kwargs)
        except Exception as ex:
            logger.exception("Error crítico no capturado en el Worker Thread: %s", str(ex))
            self.push_result(WorkerResult(
                success=False,
                content=f"Error inesperado en worker thread: {str(ex)}",
                error_type=ErrorType.UNKNOWN,
                is_recoverable=False
            ))

    def _ensure_timer_registered(self) -> None:
        """Registra el temporizador en Blender si aún no está activo."""
        if BLENDER_AVAILABLE and not self._is_timer_registered:
            bpy.app.timers.register(self._timer_callback, persistent=True)
            self._is_timer_registered = True

    def _timer_callback(self) -> Optional[float]:
        """
        Se ejecuta periódicamente en el Main Thread de Blender para vaciar la cola.
        """
        has_updates = False

        while not self.message_queue.empty():
            try:
                item = self.message_queue.get_nowait()
            except queue.Empty:
                break

            has_updates = True

            if isinstance(item, MainThreadExecutionRequest):
                try:
                    res = item.func(*item.args, **item.kwargs)
                    item.result_holder["result"] = res
                except Exception as ex:
                    logger.exception("Error ejecutando función en Main Thread: %s", str(ex))
                    item.result_holder["error"] = ex
                finally:
                    item.event.set()
            elif isinstance(item, StreamChunk):
                for cb in self._on_chunk_callbacks:
                    cb(item)
            elif isinstance(item, WorkerResult):
                for cb in self._on_result_callbacks:
                    cb(item)
            elif isinstance(item, PendingAction):
                for cb in self._on_pending_action_callbacks:
                    cb(item)

        if has_updates and BLENDER_AVAILABLE:
            self._force_redraw()

        # Si el hilo terminó y la cola está vacía, podemos ralentizar o detener el timer
        if not self.is_running() and self.message_queue.empty():
            self._is_timer_registered = False
            return None  # Cancela el timer hasta el próximo start_worker

        return 0.01  # Re-evalúa cada 10ms para máxima fluidez y ejecución instantánea

    def _force_redraw(self) -> None:
        """Solicita el redibujado de todas las ventanas 3D y paneles en Blender."""
        if not BLENDER_AVAILABLE:
            return

        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'VIEW_3D', 'PROPERTIES'}:
                    area.tag_redraw()

    def cleanup(self) -> None:
        """Limpia los callbacks y detiene los timers al deshabilitar el add-on."""
        if BLENDER_AVAILABLE and self._is_timer_registered:
            try:
                if bpy.app.timers.is_registered(self._timer_callback):
                    bpy.app.timers.unregister(self._timer_callback)
            except Exception:
                pass
            self._is_timer_registered = False

        self._on_chunk_callbacks.clear()
        self._on_result_callbacks.clear()
        self._on_pending_action_callbacks.clear()


# Instancia global del puente para la sesión de Blender
task_bridge = TaskBridge()
