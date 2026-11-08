"""
Módulo de contratos de salida para la etapa pedagógica Enganchar (Engage).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from platform5e.infrastructure.http.schemas.citation import FragmentCitationModel


class ResourceEngageItemModel(BaseModel):
    """
    Recurso didáctico de conflicto cognitivo y activación previa.
    """

    id: str = Field(
        ...,
        description="Identificador único del recurso didáctico (ej. rec-engage-01).",
    )
    stage_5e: Literal["engage"] = Field(
        default="engage",
        description="Etapa fija correspondiente al modelo instruccional 5E.",
    )
    resource_type: Literal["pregunta_detonante"] = Field(
        default="pregunta_detonante",
        description="Clasificación del tipo de recurso pedagógico producido.",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Título de la actividad introductoria.",
    )
    context_situation: str = Field(
        ...,
        min_length=15,
        description="Descripción de un escenario real o dilema técnico que conecta con el tema.",
    )
    trigger_question: str = Field(
        ...,
        min_length=10,
        description="Interrogante abierta diseñada para suscitar el debate en el aula.",
    )
    misconceptions: list[str] = Field(
        ...,
        min_length=1,
        description="Errores conceptuales frecuentes asociados al tema documentados en el corpus.",
    )
    teacher_guide: str = Field(
        ...,
        min_length=10,
        description="Orientaciones pedagógicas para que el profesor dirija la discusión grupal.",
    )
    citations: list[FragmentCitationModel] = Field(
        ...,
        min_length=1,
        description="Referencias documentales que fundamentan el contexto y los conceptos erróneos.",
    )
    status: Literal["pendiente", "aprobado", "descartado"] = Field(
        default="pendiente",
        description="Estado de revisión del recurso antes de ser integrado a la secuencia.",
    )