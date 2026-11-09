"""Entidades de dominio puro para Material y Evidencia."""

from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class Chunk:
    """Representa un fragmento de evidencia extraído de un documento."""
    id: str
    text: str
    order: int
    location: Optional[str] = None
    embedding: Optional[List[float]] = None

@dataclass
class Material:
    """Representa un documento subido por el docente a una unidad."""
    id: str
    unit_id: str
    file_name: str
    status: str
    document_type: str
    chunks: List[Chunk] = field(default_factory=list)
    page_count: Optional[int] = None
    error_message: Optional[str] = None