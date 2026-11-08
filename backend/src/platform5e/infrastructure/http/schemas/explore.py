"""
Módulo de contratos de salida para la etapa pedagógica Explorar (Explore).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from platform5e.infrastructure.http.schemas.citation import FragmentCitationModel


class InquiryStepModel(BaseModel):
    """
    Representa una acción individual dentro del procedimiento de indagación.
    """

    number: int = Field(
        ...,
        ge=1,
        description="Orden secuencial del paso dentro de la actividad.",
    )
    instruction: str = Field(
        ...,
        min_length=10,
        description="Instrucción explícita de la tarea de exploración a ejecutar.",
    )
    expected_result: str = Field(
        ...,
        min_length=5,
        description="Evidencia o respuesta preliminar que el estudiante debe observar.",
    )


class ResourceExploreItemModel(BaseModel):
    """
    Recurso de aprendizaje para el descubrimiento guiado de conceptos.
    """

    id: str = Field(
        ...,
        description="Identificador persistente del recurso didáctico (ej. rec-exp-01).",
    )
    stage_5e: Literal["explore"] = Field(
        default="explore",
        description="Etapa instruccional fija correspondiente al modelo 5E.",
    )
    resource_type: Literal["guia_indagacion"] = Field(
        default="guia_indagacion",
        description="Clasificación estructural del recurso generado.",
    )
    title: str = Field(
        ...,
        min_length=5,
        description="Encabezado temático de la guía de exploración.",
    )
    inquiry_objective: str = Field(
        ...,
        min_length=10,
        description="Propósito pedagógico o patrón técnico que se espera sea descubierto.",
    )
    required_materials: list[str] = Field(
        ...,
        min_length=1,
        description="Conjunto de insumos, fragmentos de código o datos requeridos.",
    )
    steps: list[InquiryStepModel] = Field(
        ...,
        min_length=2,
        description="Secuencia ordenada de actividades prácticas a desarrollar.",
    )
    reflection_questions: list[str] = Field(
        ...,
        min_length=1,
        description="Interrogantes metacognitivas para sintetizar los hallazgos observados.",
    )
    citations: list[FragmentCitationModel] = Field(
        ...,
        min_length=1,
        description="Referencias documentales que fundamentan el diseño de la actividad.",
    )
    status: Literal["pendiente", "aprobado", "descartado"] = Field(
        default="pendiente",
        description="Estado del recurso dentro del flujo de revisión docente.",
    )