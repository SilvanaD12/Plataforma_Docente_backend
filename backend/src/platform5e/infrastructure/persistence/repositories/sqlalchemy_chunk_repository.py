"""
Fragmentos del material y estado de procesamiento de los documentos (EN-012), con sus embeddings en pgvector (EN-013).

La columna `embedding vector(768)` existe solo en PostgreSQL con pgvector (migración de EN-024). En SQLite o en un
PostgreSQL sin la extensión, los métodos de embeddings no hacen nada y la recuperación sigue por palabras.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, text

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.embedding_port import ChunkEmbeddingRepositoryPort
from platform5e.infrastructure.persistence.database import SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    ChunkORM,
    DocumentORM,
)


def _serialize_chunk_entity(entity: ChunkORM) -> dict[str, Any]:
    """Convierte la entidad ORM Chunk a diccionario canónico con compatibilidad dual."""
    return {
        "id": entity.id,
        "document_id": entity.document_id,
        "documentId": entity.document_id,
        "documento_id": entity.document_id,
        "unit_id": entity.unit_id,
        "unitId": entity.unit_id,
        "order": entity.order_index,
        "orden": entity.order_index,
        "location": entity.location,
        "ubicacion": entity.location,
        "text": entity.text_content,
        "texto": entity.text_content,
    }


def vector_literal(vector: list[float]) -> str:
    """Formato de texto de pgvector: «[0.1,0.2,…]», para usarlo con CAST(:v AS vector)."""
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


class SQLAlchemyChunkRepository(ChunkRepositoryPort, ChunkEmbeddingRepositoryPort):
    """Adaptador de infraestructura para almacenamiento de fragmentos de texto y sus embeddings."""

    def __init__(self) -> None:
        self._vector_column: bool | None = None

    @translate_persistence_errors
    def replace_chunks(
        self, teacher_id: str, document_id: str, unit_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        with SessionLocal() as session:
            # EN-013 (incremental): los fragmentos que no cambiaron de texto conservan su vector al reprocesar.
            previous_vectors = self._vectors_by_text(session, teacher_id, document_id)
            session.execute(
                delete(ChunkORM).where(
                    ChunkORM.document_id == document_id, ChunkORM.teacher_id == teacher_id
                )
            )
            new_entities = [
                ChunkORM(
                    id=chunk["id"],
                    teacher_id=teacher_id,
                    document_id=document_id,
                    unit_id=unit_id,
                    order_index=chunk.get("order", chunk.get("orden", idx)),
                    location=chunk.get("location", chunk.get("ubicacion", "")),
                    text_content=chunk.get("text", chunk.get("texto", "")),
                )
                for idx, chunk in enumerate(chunks)
            ]
            session.add_all(new_entities)
            session.flush()
            reused = [
                {"id": entity.id, "vector": previous_vectors[entity.text_content][0],
                 "model": previous_vectors[entity.text_content][1]}
                for entity in new_entities
                if entity.text_content in previous_vectors
            ]
            if reused:
                session.execute(
                    text(
                        "UPDATE ep002_fragmentos SET embedding = CAST(:vector AS vector), modelo_embedding = :model "
                        "WHERE id = :id"
                    ),
                    reused,
                )
            session.commit()

    def _vectors_by_text(self, session: Any, teacher_id: str, document_id: str) -> dict[str, tuple[str, str]]:
        if not self.vector_store_available():
            return {}
        rows = session.execute(
            text(
                "SELECT texto, CAST(embedding AS text), modelo_embedding FROM ep002_fragmentos "
                "WHERE docente = :teacher AND documento = :document AND embedding IS NOT NULL"
            ),
            {"teacher": teacher_id, "document": document_id},
        )
        return {row[0]: (row[1], row[2]) for row in rows}

    # --- EN-013: embeddings en pgvector ---------------------------------------------------------------------------

    @translate_persistence_errors
    def vector_store_available(self) -> bool:
        if self._vector_column is None:
            if engine.dialect.name != "postgresql":
                self._vector_column = False
            else:
                with SessionLocal() as session:
                    self._vector_column = session.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name = 'ep002_fragmentos' AND column_name = 'embedding'"
                        )
                    ).first() is not None
        return self._vector_column

    @translate_persistence_errors
    def get_chunks_missing_embeddings(
        self, model: str, limit: int, document_id: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.vector_store_available():
            return []
        document_filter = "AND documento = :document " if document_id else ""
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, texto FROM ep002_fragmentos "
                    "WHERE (embedding IS NULL OR modelo_embedding <> :model) "
                    f"{document_filter}"
                    "ORDER BY documento, orden LIMIT :limit"
                ),
                {"model": model, "limit": limit, "document": document_id},
            )
            return [{"id": row[0], "text": row[1]} for row in rows]

    @translate_persistence_errors
    def save_embeddings(self, embeddings: dict[str, list[float]], model: str) -> int:
        if not embeddings or not self.vector_store_available():
            return 0
        with SessionLocal() as session:
            session.execute(
                text(
                    "UPDATE ep002_fragmentos SET embedding = CAST(:vector AS vector), modelo_embedding = :model "
                    "WHERE id = :id"
                ),
                [
                    {"id": chunk_id, "vector": vector_literal(vector), "model": model}
                    for chunk_id, vector in embeddings.items()
                ],
            )
            session.commit()
        return len(embeddings)

    @translate_persistence_errors
    def count_embedded_chunks(self, model: str, document_id: str | None = None) -> int:
        if not self.vector_store_available():
            return 0
        document_filter = " AND documento = :document" if document_id else ""
        with SessionLocal() as session:
            return int(
                session.execute(
                    text(
                        "SELECT count(*) FROM ep002_fragmentos "
                        f"WHERE embedding IS NOT NULL AND modelo_embedding = :model{document_filter}"
                    ),
                    {"model": model, "document": document_id},
                ).scalar_one()
            )

    @translate_persistence_errors
    def search_similar_chunks(
        self, vector: list[float], limit: int, unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.vector_store_available():
            return []
        unit_filter = "AND unidad = :unit " if unit_id else ""
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, documento, ubicacion, texto, "
                    "1 - (embedding <=> CAST(:vector AS vector)) AS similarity "
                    "FROM ep002_fragmentos WHERE embedding IS NOT NULL "
                    f"{unit_filter}"
                    "ORDER BY embedding <=> CAST(:vector AS vector) LIMIT :limit"
                ),
                {"vector": vector_literal(vector), "limit": limit, "unit": unit_id},
            )
            return [
                {"id": row[0], "documentId": row[1], "location": row[2], "text": row[3],
                 "similarity": round(float(row[4]), 4)}
                for row in rows
            ]

    @translate_persistence_errors
    def get_chunks_by_document(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(ChunkORM)
                .where(ChunkORM.teacher_id == teacher_id, ChunkORM.document_id == document_id)
                .order_by(ChunkORM.order_index)
            )
            return [_serialize_chunk_entity(entity) for entity in session.scalars(statement)]

    @translate_persistence_errors
    def get_chunks_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(ChunkORM)
                .where(ChunkORM.teacher_id == teacher_id, ChunkORM.unit_id == unit_id)
                .order_by(ChunkORM.document_id, ChunkORM.order_index)
            )
            return [_serialize_chunk_entity(entity) for entity in session.scalars(statement)]

    @translate_persistence_errors
    def update_document(self, teacher_id: str, document_data: dict[str, Any]) -> None:
        with SessionLocal() as session:
            doc = session.get(DocumentORM, document_data["id"])
            if doc and doc.teacher_id == teacher_id:
                doc.metadata_json = document_data
                session.commit()