"""
GEN-P1: puerto del modelo que arma el plan en una sola llamada (specs/006-plan-de-generacion/research.md R4).

Lo implementa el adaptador de Gemini (`GeminiLanguageModel.draft_plan`), con el tiempo límite de QA-06. Sin IA no hay
adaptador y el plan lo arma el planificador por reglas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PlanPrompt:
    system: str
    user: str
    schema: dict[str, Any]


class PlanDrafterPort(Protocol):
    description: str
    uses_ai: bool

    def draft_plan(self, prompt: PlanPrompt) -> Any:
        """La respuesta JSON del modelo, sin validar. Lanza un error con `public_reason` si no responde."""
        ...
