"""
core/tracker/cost_tracker.py
============================
Seguimiento y estimación de costos en USD y consumo de tokens de API.
Carga tarifas desde data/prices.json y registra métricas acumuladas por sesión.
"""

from __future__ import annotations
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BlenderAIAgent.CostTracker")


class CostTracker:
    """Administrador de métricas de consumo y cálculo de costes en USD."""

    def __init__(self, prices_file_path: Optional[str] = None):
        self.prices_file_path = prices_file_path or self._find_default_prices_path()
        self.pricing_data: Dict[str, Any] = {}
        self.last_updated: Optional[str] = None
        
        self.session_cost_usd: float = 0.0
        self.session_input_tokens: int = 0
        self.session_output_tokens: int = 0
        self.session_requests: List[Dict[str, Any]] = []

        self.load_prices()

    def _find_default_prices_path(self) -> str:
        """Determina la ruta absoluta hacia data/prices.json."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
        return os.path.join(root_dir, "data", "prices.json")

    def load_prices(self) -> None:
        """Carga el catálogo de precios desde el archivo JSON."""
        if os.path.exists(self.prices_file_path):
            try:
                with open(self.prices_file_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    self.pricing_data = data.get("models", {})
                    self.last_updated = data.get("last_updated")
                    logger.info("Tarifas cargadas exitosamente (Fecha: %s)", self.last_updated)
            except Exception as e:
                logger.error("Error al leer %s: %s", self.prices_file_path, str(e))
                self.pricing_data = {}
        else:
            logger.warning("No se encontró el archivo de precios en %s. Usando fallback.", self.prices_file_path)
            self.pricing_data = {}

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calcula el coste en USD para un volumen específico de tokens.
        Si el modelo exacto no existe, intenta matching por prefijo.
        """
        model_key = model.lower()
        model_info = self.pricing_data.get(model_key)

        # Fallback de matching por prefijo (ej: "gpt-4o-2024-08-06" -> "gpt-4o")
        if not model_info:
            for key, info in self.pricing_data.items():
                if key in model_key or model_key in key:
                    model_info = info
                    break

        if not model_info:
            # Tarifa de contingencia conservadora: $3.0 / $15.0 por 1M
            rate_in = 3.0
            rate_out = 15.0
        else:
            rate_in = model_info.get("input", 3.0)
            rate_out = model_info.get("output", 15.0)

        cost_in = (input_tokens / 1_000_000.0) * rate_in
        cost_out = (output_tokens / 1_000_000.0) * rate_out
        return round(cost_in + cost_out, 6)

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Registra el uso real extraído de una respuesta de API.
        Actualiza el acumulado de la sesión y retorna el costo del request actual.
        """
        cost = self.calculate_cost(model, input_tokens, output_tokens)
        
        self.session_cost_usd += cost
        self.session_input_tokens += input_tokens
        self.session_output_tokens += output_tokens
        
        self.session_requests.append({
            "timestamp": time.time(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost
        })

        return cost

    def check_prices_staleness(self, max_days: int = 60) -> Tuple[bool, Optional[str]]:
        """
        Verifica si el archivo de precios tiene más de max_days días de antigüedad.
        Retorna (is_stale, warning_message).
        """
        if not self.last_updated:
            return True, "No se pudo determinar la fecha de actualización de tarifas."

        try:
            updated_date = datetime.strptime(self.last_updated, "%Y-%m-%d")
            age_days = (datetime.now() - updated_date).days
            if age_days > max_days:
                return True, f"Las tarifas tienen {age_days} días de antigüedad. Considere actualizar prices.json desde el repositorio."
            return False, None
        except Exception:
            return False, None

    def reset_session(self) -> None:
        """Reinicia los contadores de la sesión activa."""
        self.session_cost_usd = 0.0
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_requests.clear()
