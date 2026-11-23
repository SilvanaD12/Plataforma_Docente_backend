# Tareas de Implementación: Material y Evidencia

---

# PARTE I — Entrega Base (MAT-01) [COMPLETADA]

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

- [X] T018 [BE] Validar el procesamiento de materiales nuevos con la API key de Gemini activa (`gemini-embedding-001`), verificando en la respuesta del backend `embeddedFragmentCount > 0` y `embeddingError: null`
- [X] T019 [BE][E2E] Comprobar el funcionamiento del motor de búsqueda híbrida (`HÍBRIDO (RRF)`) en el entorno desplegado mediante `GET /api/v1/documents/search` sobre fragmentos vectorizados nuevos
- [X] T020 [BE] Decisión técnica tomada para el mantenimiento de registros históricos: ejecutar `embed_chunks.py` como script único de backfill en producción

## Fase 7 - HU-011: Búsqueda Híbrida con Aislamiento por Unidad y Docente

- [X] T021 [BE] Corregir la validación de tipos de documentos permitidos en `ALLOWED_DOCUMENT_TYPES` dentro de `account_service.py` ([PR #34](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/34))
- [X] T022 [BE][E2E] Validar pertinencia de búsqueda híbrida en la Unidad 1 comprobando recuperación con `100.0%` de relevancia
- [X] T023 [BE][E2E] Verificar aislamiento entre unidades del mismo docente confirmando `0` resultados cruzados
- [X] T024 [BE][E2E] Verificar aislamiento estricto entre cuentas docentes distintas confirmando `0` filtraciones

## Fase 8 - HU-055: Importación de Material de Fuente Abierta (Wikipedia)

- [X] T025 [BE][FE] Validar en demo el flujo completo de búsqueda e importación desde Wikipedia vía `POST /api/v1/documents/from-topic`
- [X] T026 [BE] Inspeccionar el payload de respuesta de `from-topic` confirmando persistencia de metadatos `origin`

---

# PARTE II — Nueva Entrega / Iteración P2 (MAT-P1, MAT-P2, MAT-P3) [COMPLETADA]

## Fase 9 - MAT-P1 (Pedido P6): Ingesta de Material desde URL

- [X] T027 [MAT-P1] Definir puerto `WebContentFetcherPort` y adaptador `WebPageExtractor` con validación de URL (`http`/`https`), protección anti-SSRF (bloqueo de hosts locales/privados), timeout y limpieza de HTML a texto plano
- [X] T028 [MAT-P1] Implementar `create_from_url` en `MaterialService` reutilizando validación de unidad (`404` seguro), persistencia de `origin` (`url`, `title`, `source="Web"`) y flujo de fragmentación/embeddings (`ChunkEmbeddingService`)
- [X] T029 [MAT-P1] Exponer endpoint `POST /api/v1/documents/from-url` con esquemas Pydantic de entrada/salida (`UrlIngestRequest`, `DocumentResponse`) y manejo de errores controlados (URL inválida, inaccesible o sin contenido extraíble)
- [X] T030 [MAT-P1] Escribir pruebas unitarias y de contrato OpenAPI para ingesta desde URL en `backend/tests/unit/test_url_ingestion.py` (éxito, SSRF/URL inválida, unidad ajena `404` e indexación vectorial)

## Fase 10 - MAT-P2 (Pedido P7): Extracción y Entrega de Referentes al Plan (`GEN-P1`)

- [X] T031 [MAT-P2] Utilizar entidad/VO `Referent` y definir puertos `ReferentRepositoryPort` y `ReferentExtractorPort`
- [X] T032 [MAT-P2] Implementar `GeminiReferentExtractor` y `ReferentService` usando salida estructurada para identificar autores/referentes principales del tema y vincular `fragment_ids` de respaldo
- [X] T033 [MAT-P2] Implementar persistencia de referentes en PostgreSQL (`SQLAlchemyReferentRepository` + migración `0007_referents.py` de tabla `referente` aislada por `teacher_id` y `unit_id`) y disparar extracción durante la ingesta/procesamiento de evidencia
- [X] T034 [MAT-P2] Implementar `ReferentService` como adaptador real de `ReferentsPort` para `generation_planning` (`GEN-P1`) reemplazando el stub y conectándolo en `main.py`
- [X] T035 [MAT-P2] Escribir pruebas unitarias en `backend/tests/unit/test_referents_extraction.py` verificando extracción de referentes, caso sin autores (`[]`), aislamiento por unidad/docente y filtrado de fragmentos inválidos

## Fase 11 - MAT-P3 (Pedido P8): Reintento y Aviso al Docente ante Fallo de IA en RAG

- [X] T036 [MAT-P3] Confirmar alcance del pedido P8 respecto al flujo RAG y su manejo de fallos transitorios/persistentes
- [X] T037 [MAT-P3] Implementar política de reintento acotado (`_run_with_ai_retry`) ante fallos transitorios del proveedor de IA en `RunGenerationRequest`
- [X] T038 [MAT-P3] Propagar aviso estructurado al docente (`AI_RETRY_FAILED_MESSAGE` y sanitización `_strip_internal_methodology`) cuando persiste el fallo de IA tras el reintento (sin degradar en silencio y sin mencionar "5E" en mensajes de usuario)
- [X] T039 [MAT-P3] Escribir pruebas unitarias en `backend/tests/unit/test_rag_ai_retry_warning.py` simulando fallo transitorio (recuperado en reintento) y fallo persistente (aviso explícito al docente sin filtrar secretos ni mencionar "5E")