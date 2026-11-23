# Plan de Implementación: Material y Evidencia (MAT-01 + Iteración P2)

**Ficha**: MAT-01 (Actualizada para Iteración P2: MAT-P1, MAT-P2, MAT-P3)
**Responsable**: Sergio Celi
**Estado**: Planificado (Iteración P2)

---

# PARTE I — Arquitectura Base (Entrega 1: MAT-01)

## 1. Contexto Técnico y Arquitectura

El módulo MAT-01 sigue la arquitectura hexagonal del proyecto en `backend/src/platform5e/` (y módulos integrados en `backend/app/modules/`).

### Stack Tecnológico

- **Base de Datos**: PostgreSQL 17 con `pgvector` 0.8.1.
- **Modelos de Embedding**: `multilingual-e5-base` / `gemini-embedding-001`.
- **ORM**: SQLAlchemy.
- **Framework Web**: FastAPI.

## 2. Diseño de Arquitectura Hexagonal (Base)

- **Dominio**: `Material`, `Chunk`, reglas de segmentación (512 tokens / 50 overlap) y estados de procesamiento.
- **Aplicación**: `MaterialService`, `ChunkEmbeddingService`, puertos `EvidenceRetrieverPort`, `ChunkRepositoryPort` y `UnitMembershipPort`.
- **Infraestructura**: `SQLAlchemyChunkRepository`, `HybridEvidenceRetriever` (límite 1500ms + `BM25EvidenceRetriever`), router HTTP `documents.py`.

---

# PARTE II — Plan Técnico Nueva Entrega (Iteración P2: MAT-P1, MAT-P2, MAT-P3)

## 1. Alcance Técnico por Requerimiento

### A. MAT-P1 — Ingesta de Material desde URL (Pedido P6)

- **Dominio**:
  - Extender metadatos de `Material` para soportar origen web (`source_type="url"`, `origin={"url": ..., "title": ..., "license": ...}`) manteniendo compatibilidad con archivos (`pdf`, `txt`) y artículos de fuente abierta.
- **Aplicación**:
  - Añadir caso de uso / método `ingest_from_url(teacher_id, unit_id, url, outcome_ids)` en `MaterialService` reutilizando la validación de unidad (`404` seguro) y el pipeline `ChunkEmbeddingService`.
- **Infraestructura**:
  - Implementar adaptador `WebPageExtractor` (puerto `WebContentFetcherPort`) con:
    - Validación estricta de esquema (`http`/`https`) y bloqueo de rangos privados/loopback (anti-SSRF).
    - Descarga con timeout acotado y extracción limpia de texto principal desde HTML (eliminando `<script>`, `<style>`, `<nav>`, `<footer>`).
  - Exponer endpoint `POST /api/v1/documents/from-url` en `documents.py` con esquemas Pydantic dedicados.

### B. MAT-P2 — Extracción y Exposición de Referentes (Pedido P7)

- **Dominio**:
  - Definir entidad/value object `Referent` (`referent_id`, `unit_id`, `material_id`, `name`, `contribution`, `fragment_ids`).
- **Aplicación**:
  - Crear `ReferentExtractionService` para invocar el modelo con salida estructurada sobre los fragmentos de la evidencia e identificar autores/referentes principales del tema.
  - Persistir los referentes asociados a la evidencia de la unidad (`ReferentRepositoryPort`).
- **Infraestructura e Integración con `GEN-P1`**:
  - Implementar repositorio SQLAlchemy (`sqlalchemy_referent_repository.py`) + migración/tabla `referente`.
  - Implementar el adaptador real de `ReferentsPort` (definido en `generation_planning` tras PR #69) reemplazando el stub para entregar los referentes aislados por `teacher_id` y `unit_id`.

### C. MAT-P3 — Reintento y Aviso al Docente ante Fallo de IA en RAG (Pedido P8)

- **Aplicación / Infraestructura**:
  - En el flujo de recuperación/asistencia RAG, envolver las llamadas al proveedor de IA con política de reintento acotado (ej. 1 reintento con backoff corto ante errores transitorios).
  - Cuando el reintento también falle, propagar un estado/advertencia estructurada (`ai_fallback_warning` / error controlado) en la respuesta hacia la capa HTTP/UI para notificar al docente de forma explícita en lugar de silenciar el fallo con solo texto recuperado.
  - Garantizar que ningún mensaje de aviso mencione "5E".

## 2. Modelo de Datos (Nuevas Entidades / Campos P2)

- **Tabla `documento` (`Material`)**: soporte de `source_type = 'url'` y metadatos JSON `origin` con URL canónica y título extraído.
- **Tabla `referente` (`Referent`)**: `id`, `teacher_id`, `unit_id`, `material_id` (nullable si es consolidado de unidad), `name`, `contribution`, `fragment_ids` (JSONB), `created_at`.
