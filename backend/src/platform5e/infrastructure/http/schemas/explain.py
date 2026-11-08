"""
Módulo de contratos de salida para la etapa pedagógica Explicar (Explain).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from platform5e.infrastructure.http.schemas.citation import FragmentCitationModel


class KeyDefinitionModel(BaseModel):
    """
    Representa una entrada de terminología técnica fundamental.
    """

    term: str = Field(
        ...,
        min_length=2,
        description="Nombre formal del término, algoritmo o estructura analizada.",
    )
    definition: str = Field(
        ...,
        min_length=10,
        description="Explicación conceptual precisa y fundamentada en la cátedra.",
    )
    source_fragment_id: str = Field(
        ...,
        description="Identificador del fragmento que sustenta textualmente la definición.",
    )


class ResourceExplainItemModel(BaseModel):
    """
    Recurso de formalización y síntesis conceptual.
    """

    id: str = Field(
        ...,
        description="Identificador persistente del recurso didáctico (ej. rec-expl-01).",
    )
    stage_5e: Literal["explain"] = Field(
        default="explain",
        description="Etapa instruccional fija correspondiente al modelo 5E.",
    )
    resource_type: Literal["explicacion_conceptual"] = Field(
        default="explicacion_conceptual",
        description="Clasificación estructural del recurso generado.",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Título de la formalización teórica.",
    )
    theoretical_synthesis: str = Field(
        ...,
        min_length=20,
        description="Desarrollo explicativo estructurado de los fundamentos y mecanismos.",
    )
    key_definitions: list[KeyDefinitionModel] = Field(
        ...,
        min_length=1,
        description="Conjunto de términos técnicos esenciales con su definición formal.",
    )
    canonical_example: str = Field(
        ...,
        min_length=15,
        description="Caso práctico completamente resuelto que ilustra la teoría expuesta.",
    )
    citations: list[FragmentCitationModel] = Field(
        ...,
        min_length=1,
        description="Referencias documentales que certifican la exactitud de los conceptos expuestos.",
    )
    status: Literal["pendiente", "aprobado", "descartado"] = Field(
        default="pendiente",
        description="Estado del recurso dentro del flujo de revisión docente.",
    )