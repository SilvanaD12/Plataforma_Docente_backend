"""
Módulo de contratos de salida para la etapa pedagógica Evaluar (Evaluate).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from platform5e.infrastructure.http.schemas.citation import FragmentCitationModel


class ItemOptionModel(BaseModel):
    """
    Representa una opción de respuesta (clave correcta o distractor funcional).
    """

    id: Literal["a", "b", "c", "d", "e"] = Field(
        ...,
        description="Identificador correlativo de la alternativa dentro del ítem.",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Contenido textual de la alternativa de respuesta.",
    )
    is_correct: bool = Field(
        ...,
        description="Determina si la opción corresponde a la clave válida de la pregunta.",
    )
    feedback: str = Field(
        ...,
        min_length=5,
        description="Explicación formativa que orienta al estudiante sobre el acierto o el error.",
    )
    source_fragment_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Lista de identificadores de fragmentos documentales que respaldan la alternativa.",
    )
    reliability_warning: str | None = Field(
        default=None,
        description="Mensaje del motor de anclaje si el distractor requiere revisión por proximidad léxica.",
    )
    key_similarity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Similitud semántica calculada frente a la clave para asegurar plausibilidad sin equivalencia.",
    )


class CitationBlockModel(BaseModel):
    """
    Estructura de trazabilidad agregada para el cuerpo del ítem.
    """

    claim: str = Field(
        ...,
        min_length=5,
        description="Aserción pedagógica o técnica formulada en el contenido del ítem.",
    )
    fragment_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Colección de IDs de fragmentos asociados directamente a la afirmación.",
    )
    detailed_evidence: list[FragmentCitationModel] | None = Field(
        default=None,
        description="Desglose exhaustivo de citas con texto literal, página y similitud.",
    )


class ResourceEvaluateItemModel(BaseModel):
    """
    Recurso de evaluación formativa de opción múltiple.
    """

    id: str = Field(
        ...,
        description="Identificador persistente del recurso en la base de datos (ej. rec-eval-01).",
    )
    stage_5e: Literal["evaluate"] = Field(
        default="evaluate",
        description="Etapa fija correspondiente al modelo instruccional 5E.",
    )
    resource_type: Literal["item_opcion_multiple"] = Field(
        default="item_opcion_multiple",
        description="Tipología estructural del recurso didáctico generado.",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Encabezado descriptivo del ítem según el tema evaluado.",
    )
    prompt: str = Field(
        ...,
        min_length=10,
        description="Cuerpo de la pregunta, caso o problema planteado al estudiante.",
    )
    options: list[ItemOptionModel] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="Conjunto de opciones que contiene una clave y entre 2 y 4 distractores funcionales.",
    )
    citations: list[CitationBlockModel] = Field(
        ...,
        min_length=1,
        description="Bloques obligatorios de citas que verifican la fidelidad semántica con el material.",
    )
    status: Literal["pendiente", "aprobado", "descartado"] = Field(
        default="pendiente",
        description="Estado del recurso en el flujo de decisión del docente.",
    )