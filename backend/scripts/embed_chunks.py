"""Vectoriza los fragmentos que todavía no tienen embedding y prueba una búsqueda por significado (EN-013).

Sirve para los fragmentos subidos antes de EN-013: los nuevos se vectorizan solos al procesar el material.
Es incremental: lo que ya tiene vector del modelo actual no se vuelve a calcular.

Uso, desde backend/ (PowerShell; en macOS o Linux usa export en vez de $env:):
    $env:DATABASE_URL="postgresql://…"   # la base de Neon o la local de docker compose
    $env:LLM_API_KEY="TU_CLAVE"
    python scripts/embed_chunks.py                   # vectoriza todo lo pendiente
    python scripts/embed_chunks.py --limit 20        # solo 20 fragmentos
    python scripts/embed_chunks.py --search "¿qué protocolo confirma la entrega?"
"""

from __future__ import annotations

import argparse
import sys

from platform5e.application.services.materials.chunk_embedding_service import ChunkEmbeddingService
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError
from platform5e.infrastructure.llm.language_model_factory import create_embedding_generator
from platform5e.infrastructure.persistence.repositories.sqlalchemy_chunk_repository import (
    SQLAlchemyChunkRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="máximo de fragmentos a vectorizar")
    parser.add_argument("--search", default="", help="consulta para probar la búsqueda por significado")
    parser.add_argument("--unit", default=None, help="id de la unidad para filtrar la búsqueda")
    args = parser.parse_args()

    generator = create_embedding_generator()
    if generator is None:
        print("No hay embeddings: define LLM_API_KEY (Gemini) y no pongas EMBEDDINGS_ENABLED=false.")
        return 1
    repository = SQLAlchemyChunkRepository()
    if not repository.vector_store_available():
        print("La base no tiene la columna embedding (pgvector). Revisa DATABASE_URL y la migración de EN-024.")
        return 1

    service = ChunkEmbeddingService(repository, generator)
    try:
        run = service.embed_pending(limit=args.limit)
    except AIProviderError as error:
        print(f"Gemini no respondió: {error}")
        return 1
    print(f"Modelo {run.model}: {run.embedded} fragmentos vectorizados ahora, {run.total} con vector en total.")

    if args.search:
        vector = generator.embed_query(args.search)
        print(f"\nMás cercanos a «{args.search}» (similitud coseno):")
        for chunk in repository.search_similar_chunks(vector, 5, args.unit):
            snippet = " ".join(chunk["text"].split())[:110]
            print(f"  {chunk['similarity']:.3f}  {chunk['location']:<6} {snippet}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
