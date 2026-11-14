"""
Caso de uso TA-010 (T062): evidencia recuperada de un pedido de generación, para la evaluación RAG (research R12).

Devuelve todo lo que el pedido recuperó del material y entregó al modelo, en el orden de la recuperación, no solo los
fragmentos que citan los recursos. Un pedido ajeno y uno inexistente dan la misma respuesta (GEN-C5). Solo depende del
puerto del repositorio y del dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.application.services.generation.step_drafting import retrieval_limit
from platform5e.application.use_cases.generation.get_generation_request import REQUEST_NOT_FOUND_MESSAGE
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode

# La fecha de la recuperación es la misma para todos los fragmentos: va una sola vez, en el nivel superior.
RETRIEVED_AT_KEY: str = "retrievedAt"


@dataclass(frozen=True)
class GenerationEvidence:
    """Lo que recuperó el pedido. `fragments` está vacío mientras el pedido espera en cola o si la recuperación falló."""

    request_id: str
    retrieval_mode: str | None
    limit: int
    retrieved_at: str | None
    fragments: tuple[dict[str, Any], ...]


class GetGenerationEvidence:
    """Consulta de la evidencia recuperada de un pedido del docente."""

    def __init__(self, repository: GenerationRequestRepositoryPort) -> None:
        self._repository = repository

    def execute(self, teacher_id: str, request_id: str) -> GenerationEvidence:
        request = self._repository.get(teacher_id, request_id)
        if request is None:
            raise GenerationError(GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND, REQUEST_NOT_FOUND_MESSAGE)
        stored = [fragment for fragment in request.evidence if isinstance(fragment, dict)]
        return GenerationEvidence(
            request_id=request.id,
            retrieval_mode=request.retrieval_mode,
            # El límite con que se recuperó: el `topK` del pedido, acotado como en la ejecución (de 3 a 12).
            limit=retrieval_limit(request.parameters.top_k),
            retrieved_at=next((f.get(RETRIEVED_AT_KEY) for f in stored if f.get(RETRIEVED_AT_KEY)), None),
            fragments=tuple(
                {key: value for key, value in fragment.items() if key != RETRIEVED_AT_KEY} for fragment in stored
            ),
        )
