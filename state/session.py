"""
state/session.py
================
Estado de la sesión activa en Blender.
Centraliza las instancias del ContextManager, CostTracker, CheckpointManager y AuthGate.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional

from core.context_manager import ContextManager
from core.providers.anthropic import AnthropicProvider
from core.providers.base import BaseProvider
from core.providers.gemini import GeminiProvider
from core.providers.openai import OpenAIProvider
from core.security.auth_gate import AuthGate
from core.tracker.cost_tracker import CostTracker
from blender_integration.state_manager.checkpoints import CheckpointManager


class SessionState:
    """Contenedor de estado para la sesión de trabajo activa en Blender."""

    def __init__(self):
        self.auth_gate = AuthGate(auto_approve=False)
        self.context_manager = ContextManager()
        self.cost_tracker = CostTracker()
        self.checkpoint_manager = CheckpointManager()
        self.active_provider: Optional[BaseProvider] = None

    def initialize_provider(
        self,
        provider_name: str,
        api_key: str,
        model_name: Optional[str] = None
    ) -> BaseProvider:
        """Instancia y configura el adaptador de LLM seleccionado."""
        p_name = provider_name.upper()
        
        if p_name == "ANTHROPIC":
            self.active_provider = AnthropicProvider(
                api_key=api_key,
                default_model=model_name or "claude-3-7-sonnet"
            )
        elif p_name == "OPENAI":
            self.active_provider = OpenAIProvider(
                api_key=api_key,
                default_model=model_name or "gpt-4o"
            )
        elif p_name == "GOOGLE" or p_name == "GEMINI":
            self.active_provider = GeminiProvider(
                api_key=api_key,
                default_model=model_name or "gemini-2.0-flash"
            )
        else:
            raise ValueError(f"Proveedor desconocido: {provider_name}")

        return self.active_provider

    def reset(self) -> None:
        """Reinicia la conversación y los contadores de la sesión."""
        self.context_manager.clear()
        self.cost_tracker.reset_session()


# Singleton de sesión
session_state = SessionState()
