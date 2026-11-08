"""
Puerto del modelo de lenguaje (la «G» de RAG): redacta los recursos a partir de la evidencia recuperada.

Lo implementan GeminiLanguageModel (Gemini, Anthropic u OpenAI) y RuleBasedGenerator (respaldo sin IA);
language_model_factory elige cuál según las variables LLM_*.
"""

from __future__ import annotations

from typing import Any, Protocol


class ResourceGeneratorPort(Protocol):
    """Contrato del generador de recursos (LLM o generador determinista por reglas)."""

    description: str
    uses_ai: bool

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        """Recibe el contexto estructurado y devuelve {'resources': [...]}.

        Cada recurso contiene título, contenido, citas de fragmentos del contexto
        y alternativas justificadas.
        """
        ...