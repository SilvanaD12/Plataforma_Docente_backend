# Tareas de Implementación: Material y Evidencia (MAT-01)

## Fase 1: Dominio y Puertos

- [X] T001 Revisar e implementar entidades de dominio `Material` y `Chunk`
- [X] T002 Completar la interfaz en `backend/src/platform5e/application/ports/outbound/evidence_retriever_port.py`
- [X] T003 Completar la interfaz en `backend/src/platform5e/application/ports/outbound/chunk_repository_port.py`

## Fase 2: Carga y Validación (Documentos) [US1]

- [X] T004 [US1] Completar esquemas Pydantic para carga y respuesta en `backend/src/platform5e/infrastructure/http/schemas/documents.py`
- [X] T005 [P] [US1] Implementar validación de outcomes llamando al contexto de Generación en `backend/src/platform5e/application/services/materials/material_service.py`
- [X] T006 [US1] Implementar endpoint de subida conectando la regla del 404 (unidad ajena vs inexistente) en `backend/src/platform5e/infrastructure/http/routers/documents.py`

## Fase 3: Procesamiento y Fragmentación [US2]

- [X] T007 [US2] Implementar la lógica de 512 tokens y 50 de overlap en `backend/src/platform5e/domain/materials/chunking.py`
- [X] T008 [US2] Conectar modelo SQLAlchemy `Chunk` con soporte para `Vector(768)` e índice GIN
- [X] T009 [P] [US2] Implementar guardado en `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_chunk_repository.py`
- [X] T010 [US2] Integrar el flujo de fragmentación y vectorización en `backend/src/platform5e/application/services/materials/chunk_embedding_service.py`

## Fase 4: Recuperación Híbrida [US3]

- [X] T011 [US3] Implementar consulta HNSW + GIN con límite de 1500ms en `backend/src/platform5e/infrastructure/retrieval/hybrid_evidence_retriever.py`
- [X] T012 [US3] Manejar el timeout y delegar a `bm25_fallback` dentro de `backend/src/platform5e/infrastructure/retrieval/bm25_evidence_retriever.py` o el adaptador principal
- [X] T013 [US3] Exponer el método de búsqueda en `documents.py` o a través del puerto interno para que Yan lo consuma

## Fase 5: Pruebas (Tests existentes)

- [X] T014 Escribir prueba HTTP del 404 seguro (MAT-C2) en `backend/tests/e2e/test_material_ingestion_api.py`
- [X] T015 [P] Escribir pruebas de aislamiento vectorial (MAT-C3) en `backend/tests/unit/test_material_retrieval.py`
- [X] T016 [P] Escribir pruebas unitarias del servicio en `backend/tests/unit/test_material_service.py`
- [X] T017 [P] Completar la cobertura en `backend/tests/unit/test_chunk_embedding_service.py`
