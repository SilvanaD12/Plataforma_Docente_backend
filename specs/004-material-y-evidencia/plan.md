# Plan de Implementación: Material y Evidencia (MAT-01)

**Ficha**: MAT-01
**Responsable**: Sergio Celi
**Estado**: Planificado

## 1. Contexto Técnico y Arquitectura
El módulo MAT-01 se implementará siguiendo la arquitectura hexagonal del proyecto, utilizando los servicios, adaptadores y repositorios que ya tienen su estructura definida en `backend/src/platform5e/`.

### Stack Tecnológico
- **Base de Datos**: PostgreSQL 17 con `pgvector` 0.8.1.
- **Modelos de Embedding**: `multilingual-e5-base` (requiere prefijos `"query: "` y `"passage: "`).
- **ORM**: SQLAlchemy.
- **Framework Web**: FastAPI.

## 2. Diseño de Arquitectura Hexagonal

### Capa de Dominio (`backend/src/platform5e/domain/`)
- **Archivos**: `materials/chunking.py` y `materials/text_analysis.py` ya existen.
- **Entidades**: `Material` (Documento), `Chunk` (Fragmento).
- **Reglas**: Todo `Chunk` pertenece a un `Material`. El estado de error debe mapearse a motivos específicos.

### Capa de Aplicación (`backend/src/platform5e/application/`)
- **Puertos de Entrada (Servicios)**: 
  - `materials/material_service.py`: Lógica de negocio para carga y validación.
  - `materials/chunk_embedding_service.py`: Orquestación de fragmentación y embeddings.
- **Puertos de Salida (Interfaces en `ports/outbound/`)**:
  - `evidence_retriever_port.py` y `chunk_repository_port.py`.
  - Reutilización de `UnitMembershipPort` para validar pertenencia.

### Capa de Infraestructura (`backend/src/platform5e/infrastructure/`)
- **Persistencia (`persistence/repositories/`)**:
  - `sqlalchemy_chunk_repository.py` y repositorio de material.
- **Recuperación (`retrieval/`)**:
  - `hybrid_evidence_retriever.py` y `bm25_evidence_retriever.py`. Ejecuta la consulta combinada, maneja el límite de 1500ms y aplica el fallback si hay timeout.
- **Controladores (`http/routers/` y `http/schemas/`)**:
  - `documents.py` (routers) y `documents.py` (schemas). Manejan la petición y garantizan el `404 Not Found` seguro.

## 3. Modelo de Datos (SQLAlchemy)
- **Tabla `documento`** -> Clase `Material` (`teacher_id`, `unit_id`, `state`, `file_name`)
- **Tabla `fragmento`** -> Clase `Chunk` (`material_id`, `unit_id`, `texto_tsv`, `embedding vector(768)`)

## 4. Estrategia de Implementación
- Se utilizarán fragmentos de 512 tokens con 50 de overlap.
- Límite duro de 1500ms para consultas HNSW en PostgreSQL.