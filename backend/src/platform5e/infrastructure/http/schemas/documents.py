"""Esquemas del material de la unidad: documentos, fragmentos y búsqueda por tema."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse

Stage = Literal["engage", "explore", "explain", "elaborate", "evaluate"]


class DocumentContextInput(ApiRequest):
    """JSON sent in the `context` form field of POST /documents."""

    unit_id: str = Field(description="Unit that receives the material.", examples=["unidad-1"])
    outcome_ids: list[str] = Field(default_factory=list, max_length=50, description="Related learning outcomes.")
    document_type: str = Field(examples=["Separata o apuntes de clase"])
    suggested_stage: Stage | None = None
    use_permission: bool = Field(description="The teacher confirms they may use this material. Must be true.")


class TopicSearchRequest(ApiRequest):
    unit_id: str = Field(examples=["unidad-1"])
    topic: str = Field(min_length=3, max_length=120, examples=["Protocolo de control de transmisión"])
    max_results: int = Field(default=3, ge=1, le=5, description="Maximum number of articles to add.")


class DocumentOrigin(ApiResponse):
    """Open source the document came from (POST /documents/from-topic)."""

    source: str = Field(examples=["Wikipedia"])
    url: str
    license: str = Field(examples=["CC BY-SA 4.0"])
    topic: str


class DocumentResponse(ApiResponse):
    id: str
    file_name: str
    kind: Literal["pdf", "pptx", "txt"]
    size_bytes: int
    unit_id: str
    outcome_ids: list[str] = []
    document_type: str
    status: str = Field(description="`registrado`, `procesando`, `procesado` or `error` (values migrate in Sprint 2).")
    registered_at: str
    processed_at: str | None = None
    fragment_count: int = 0
    page_count: int | None = None
    error_message: str | None = None
    embedded_fragment_count: int | None = Field(
        default=None, description="Chunks with an embedding in pgvector (EN-013); null if embeddings are disabled."
    )
    embedding_model: str | None = Field(default=None, examples=["gemini-embedding-001"])
    embedding_error: str | None = Field(
        default=None, description="Why the embeddings failed; the document stays processed and BM25 still works."
    )
    origin: DocumentOrigin | None = None


class ChunkResponse(ApiResponse):
    id: str
    order: int = Field(description="Position of the chunk in the document, from 0.")
    location: str = Field(examples=["p. 3"])
    text: str
