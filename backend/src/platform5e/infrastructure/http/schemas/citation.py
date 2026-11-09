"""
Módulo base para estructuras de datos compartidas y anclaje de evidencia.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FragmentCitationModel(BaseModel):
    """
    Representa una referencia explícita a un fragmento del material de estudio.
    """

    fragment_id: str = Field(
        ...,
        description="Identificador persistente del fragmento en la base de datos (ej. f-u2-01).",
    )
    document_id: str | None = Field(
        default=None,
        description="Identificador único o nombre del documento maestro de origen.",
    )
    location: int = Field(
        ...,
        ge=1,
        description="Número de página o diapositiva donde se ubica el texto original.",
    )
    quoted_text: str = Field(
        ...,
        min_length=10,
        description="Extracto literal del fragmento que valida la afirmación generada.",
    )
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Proporción (0 a 1) de las palabras útiles de la afirmación que aparecen en el fragmento, con la misma raíz "
            "o los mismos seis primeros caracteres. Es una coincidencia por palabras (grounding.py), no una similitud "
            "semántica coseno."
        ),
    )