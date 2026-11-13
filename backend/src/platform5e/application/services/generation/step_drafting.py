"""
Redacción de un paso de generación (GEN-01 · T013): pide los recursos al generador principal o al de respaldo, aplica
el control de repetición de la secuencia, arma el recurso para la revisión docente y resume la verificación de anclaje.

Se extrajo de `generation_service.py` sin cambiar su comportamiento. Lo usa el caso de uso que ejecuta los pedidos en
segundo plano; el servicio síncrono se retiró en T046.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.services.generation.prompt_drafting import normalize_generated_resources
from platform5e.domain.generation.grounding import hallucination_rate
from platform5e.domain.generation.resource_formats import resource_format
from platform5e.domain.generation.sequence import SIMILARITY_THRESHOLD, most_similar, resource_text

OPTION_LETTERS: str = "abcdefghij"
REQUEST_PARAMETERS: tuple[str, ...] = (
    "resourceType",
    "stage",
    "outcomeId",
    "difficulty",
    "optionCount",
    "instructions",
    "audience",
    "competency",
    "modality",
    "topK",
    "evidenceThreshold",
)
NO_REPEAT_INSTRUCTION: str = (
    "Tu recurso anterior se parecía demasiado a otro de la secuencia: usa otros ejemplos, preguntas y enfoque."
)
SEQUENCE_PREVIEW_CHARS: int = 300
MIN_RETRIEVED_CHUNKS: int = 3
MAX_RETRIEVED_CHUNKS: int = 12
DEFAULT_RETRIEVED_CHUNKS: int = 8

logger = logging.getLogger("platform5e.generation")


@dataclass
class StepDraft:
    """Lo que redactó un paso: los recursos conservados (formato del generador), los rechazados por repetir otro
    recurso de la secuencia, el generador que respondió y el aviso si hubo respaldo."""

    kept: list[dict[str, Any]] = field(default_factory=list)
    repeated: list[dict[str, Any]] = field(default_factory=list)
    generator: ResourceGeneratorPort | None = None
    warning: str | None = None


def retrieval_limit(top_k: Any) -> int:
    """Fragmentos que se recuperan del material: el `topK` pedido, entre 3 y 12 (8 si no se indica)."""
    return max(MIN_RETRIEVED_CHUNKS, min(int(top_k or DEFAULT_RETRIEVED_CHUNKS), MAX_RETRIEVED_CHUNKS))


def evidence_query_text(unit_title: str, outcome_texts: list[str], instructions: str, competency: str) -> str:
    """Consulta de recuperación: título de la unidad, resultados elegidos, indicaciones y competencia."""
    return " ".join(filter(None, [unit_title, *outcome_texts, instructions, competency]))


def previous_sequence(accepted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resumen de lo que redactaron los agentes anteriores, para que el siguiente no lo repita (`secuenciaPrevia`)."""
    return [
        {
            "etapa": previous["etapa"],
            "titulo": previous["titulo"],
            "resumen": resource_text(previous)[:SEQUENCE_PREVIEW_CHARS],
        }
        for previous in accepted
    ]


def saved_parameters(request_data: dict[str, Any]) -> dict[str, Any]:
    """Parámetros congelados en el recurso; los usa la regeneración (GEN-R6). `modality` solo se guarda si el docente
    eligió una (HU-024)."""
    saved = {param: request_data.get(param) for param in REQUEST_PARAMETERS}
    if not saved["modality"]:
        del saved["modality"]
    return saved


def draft_resources(
    generation_context: dict[str, Any],
    primary_generator: ResourceGeneratorPort | None,
    fallback_generator: ResourceGeneratorPort | None,
    rejections: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], ResourceGeneratorPort | None, str | None]:
    """Pide la redacción al generador principal y, si no devuelve recursos válidos, al de respaldo.

    Los recursos rechazados por la verificación de anclaje (HU-016) o por sus distractores (HU-019) se agregan a
    `rejections` con su motivo y su `kind`.
    """
    resources: list[dict[str, Any]] = []
    active_generator: ResourceGeneratorPort | None = None
    warning_message: str | None = None

    if primary_generator is not None:
        try:
            raw_response = primary_generator.generate(generation_context)
            resources = normalize_generated_resources(raw_response, generation_context, rejections)
            active_generator = primary_generator
            if not resources:
                warning_message = (
                    f"{primary_generator.description} no devolvió recursos con citas válidas del material."
                )
        except Exception as exc:
            warning_message = f"{primary_generator.description} no respondió ({str(exc)[:160]})."

    if not resources and fallback_generator is not None and fallback_generator is not primary_generator:
        raw_response = fallback_generator.generate(generation_context)
        resources = normalize_generated_resources(raw_response, generation_context, rejections)
        active_generator = fallback_generator
        if warning_message:
            warning_message += " Se usó el generador por reglas."

    if warning_message:
        logger.warning("Generación con respaldo: %s", warning_message)
    return resources, active_generator, warning_message


def filter_repeated(
    drafted: list[dict[str, Any]], accepted: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separa los recursos nuevos de los que repiten contenido de otro recurso de la secuencia.

    Cada rechazo es `{title, reason, kind: "repetition"}`.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for resource in drafted:
        score, previous = most_similar(resource, accepted + kept)
        if previous is not None and score >= SIMILARITY_THRESHOLD:
            title = resource.get("titulo", "")
            rejected.append(
                {
                    "title": title,
                    "reason": f"«{title}» repetía «{previous.get('titulo', '')}» ({round(score * 100)} %).",
                    "kind": "repetition",
                }
            )
        else:
            kept.append(resource)
    return kept, rejected


def draft_step(
    context: dict[str, Any],
    accepted: list[dict[str, Any]],
    primary_generator: ResourceGeneratorPort | None,
    fallback_generator: ResourceGeneratorPort | None,
    rejections: list[dict[str, Any]],
) -> StepDraft:
    """HU-003: redacta un paso de la secuencia. Un recurso demasiado parecido a otro ya aceptado se pide de nuevo una
    vez con otra indicación y, si sigue repetido, se rechaza."""
    drafted, generator, warning = draft_resources(context, primary_generator, fallback_generator, rejections)
    kept, repeated = filter_repeated(drafted, accepted)
    if repeated and generator is not None:
        retry_request = {
            **context["solicitud"],
            "indicaciones": " ".join(filter(None, [context["solicitud"]["indicaciones"], NO_REPEAT_INSTRUCTION])),
        }
        retried, generator_retry, _ = draft_resources(
            {**context, "solicitud": retry_request}, primary_generator, fallback_generator, rejections
        )
        generator = generator_retry or generator
        kept_retry, repeated = filter_repeated(retried[: len(repeated)], accepted + kept)
        kept += kept_retry
    return StepDraft(kept=kept, repeated=repeated, generator=generator, warning=warning)


def build_resource_dict(
    resource_data: dict[str, Any],
    request_data: dict[str, Any],
    unit_id: str,
    outcome_id: str,
    generator_name: str,
    timestamp: str,
) -> dict[str, Any]:
    """Crea el diccionario con formato estándar para la API de revisión docente."""
    resource_id = f"rec-api-{uuid4()}"
    options_list = None

    if resource_data.get("alternativas"):
        alternatives = list(resource_data["alternativas"])
        random.Random(resource_id).shuffle(alternatives)
        options_list = [
            {
                "id": f"{resource_id}:{OPTION_LETTERS[idx]}",
                "text": alt["texto"],
                "isCorrect": alt["correcta"],
                "feedback": alt["retroalimentacion"],
                "sourceFragmentIds": alt["fragmentos"],
                "decision": "descartado" if alt.get("tambienCorrecto") else "pendiente",
                "discardReason": "tambien_correcto" if alt.get("tambienCorrecto") else None,
                "edited": False,
                "misconception": alt.get("errorConceptual"),
                "reliabilityWarning": alt.get("tambienCorrecto"),
            }
            for idx, alt in enumerate(alternatives)
        ]

    return {
        "exampleId": "material-docente",
        "unitId": unit_id,
        "outcomeId": outcome_id,
        "stage": request_data["stage"],
        "type": request_data["resourceType"],
        "format": resource_format(request_data["resourceType"]),
        "structure": resource_data.get("estructura"),
        "title": resource_data["titulo"],
        "body": resource_data["contenido"],
        "id": resource_id,
        "requestId": request_data["id"],
        "source": "rag",
        "generator": generator_name,
        "options": options_list,
        "citations": resource_data["citas"],
        "grounding": resource_data.get("verificacion"),
        "status": "pendiente",
        "edited": False,
        "discardReason": None,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "decidedAt": None,
    }


def build_grounding_report(
    resources: list[dict[str, Any]], rejections: list[dict[str, Any]]
) -> dict[str, Any]:
    """HU-016: resumen de la verificación de anclaje de un pedido, con el indicador I21 (tasa de alucinación).

    Cuenta las afirmaciones de los recursos conservados y de los rechazados. I21 = afirmaciones sin respaldo /
    afirmaciones verificadas. HU-049: también cuenta los párrafos de la explicación y del glosario quitados por no
    tener respaldo.
    """
    summaries = [r["grounding"] for r in resources if r.get("grounding")]
    summaries += [item["grounding"] for item in rejections if item.get("grounding")]
    checked = sum(s["checkedClaims"] for s in summaries)
    supported = sum(s["supportedClaims"] for s in summaries)
    return {
        "checkedClaims": checked,
        "supportedClaims": supported,
        "unsupportedClaims": checked - supported,
        "hallucinationRate": hallucination_rate(checked, checked - supported),
        "unsupportedParagraphs": sum(len(s.get("removedParagraphs") or []) for s in summaries),
        "rejectedResources": [{"title": item["title"], "reason": item["reason"]} for item in rejections],
    }
