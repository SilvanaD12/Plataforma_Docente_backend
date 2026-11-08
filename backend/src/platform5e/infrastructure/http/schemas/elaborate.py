"""
Módulo de contratos de salida para la etapa pedagógica Elaborar (Elaborate).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from platform5e.infrastructure.http.schemas.citation import FragmentCitationModel


class EvaluationCriterionModel(BaseModel):
    """
    Criterio o dimensión para valorar la resolución del problema.
    """

    dimension: str = Field(
        ...,
        min_length=3,
        description="Dimensión técnica o analítica evaluada (ej. Eficiencia, Modularidad).",
    )
    description: str = Field(
        ...,
        min_length=5,
        description="Expectativa concreta de desempeño para superar satisfactoriamente el rubro.",
    )


class ResourceElaborateItemModel(BaseModel):
    """
    Recurso de transferencia y profundización cognitiva.
    """

    id: str = Field(
        ...,
        description="Identificador persistente del recurso didáctico (ej. rec-elab-01).",
    )
    stage_5e: Literal["elaborate"] = Field(
        default="elaborate",
        description="Etapa instruccional fija correspondiente al modelo 5E.",
    )
    resource_type: Literal["caso_transferencia"] = Field(
        default="caso_transferencia",
        description="Clasificación estructural del recurso generado.",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Título descriptivo del desafío de aplicación.",
    )
    new_context: str = Field(
        ...,
        min_length=20,
        description="Descripción del escenario o sistema donde se sitúa el nuevo problema.",
    )
    proposed_challenge: str = Field(
        ...,
        min_length=10,
        description="Formulación explícita del problema o requerimiento complejo a resolver.",
    )
    evaluation_criteria: list[EvaluationCriterionModel] = Field(
        ...,
        min_length=2,
        description="Pautas o rúbricas para guiar y verificar la calidad de la solución.",
    )
    citations: list[FragmentCitationModel] = Field(
        ...,
        min_length=1,
        description="Referencias documentales que fundamentan los conceptos base aplicados.",
    )
    status: Literal["pendiente", "aprobado", "descartado"] = Field(
        default="pendiente",
        description="Estado del recurso dentro del flujo de revisión docente.",
    )