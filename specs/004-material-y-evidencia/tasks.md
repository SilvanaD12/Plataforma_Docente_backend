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

## Fase 6 - EN-013: Generación de Embeddings y Búsqueda Híbrida (Validación en Demo)

- [X] T018 [BE] Validar el procesamiento de materiales nuevos con la API key de Gemini activa (`gemini-embedding-001`), verificando en la respuesta del backend `embeddedFragmentCount > 0` y `embeddingError: null` (`backend/tests/unit/test_chunk_embedding_service.py` y captura en comentario del PR)
- [X] T019 [BE][E2E] Comprobar el funcionamiento del motor de búsqueda híbrida (`HÍBRIDO (RRF)`) en el entorno desplegado mediante `GET /api/v1/documents/search` sobre fragmentos vectorizados nuevos (captura de respuesta `200 OK` en comentario del PR)
- [X] T020 [BE] Definir estrategia de mantenimiento para registros históricos mediante la ejecución única de `embed_chunks.py` como backfill en producción para indexar materiales previos

## Fase 7 - HU-011: Búsqueda Híbrida con Aislamiento por Unidad y Docente

- [X] T021 [BE] Corregir la validación de tipos de documentos permitidos en `ALLOWED_DOCUMENT_TYPES` dentro de `account_service.py` para soportar guías de laboratorio y otros materiales didácticos ([PR #34](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/34))
- [X] T022 [BE][E2E] Validar pertinencia de búsqueda híbrida en la Unidad 1 (`Protocolos de Transporte y Direccionamiento IP`), comprobando recuperación con `100.0%` de relevancia (`backend/tests/unit/test_material_retrieval.py` y captura en comentario del PR)
- [X] T023 [BE][E2E] Verificar aislamiento entre unidades del mismo docente creando la Unidad 2 (`Seguridad y Aplicaciones de Red`) y confirmando `0` resultados al consultar términos pertenecientes a la Unidad 1 (captura en comentario del PR)
- [X] T024 [BE][E2E] Verificar aislamiento estricto entre cuentas docentes distintas (`sergioceli2026@gmail.com` vs `gvertiz@upao.edu.pe`), confirmando `0` filtraciones de cursos ni fragmentos indexados (captura en comentario del PR)

## Fase 8 - HU-055: Importación de Material de Fuente Abierta (Wikipedia)

- [X] T025 [BE][FE] Validar en demo el flujo completo de búsqueda e importación de artículos de fuente abierta desde Wikipedia (`Modelo OSI` y `Protocolo de datagramas de usuario`) vía `POST /api/v1/documents/from-topic` (captura de interfaz en comentario del PR)
- [X] T026 [BE] Inspeccionar el payload de respuesta de `from-topic` confirmando la persistencia de metadatos de procedencia en el objeto `origin` (`url` exacta de Wikipedia y licencia `CC BY-SA 4.0`) junto con su registro como `Artículo de fuente abierta` (captura de DevTools en comentario del PR)