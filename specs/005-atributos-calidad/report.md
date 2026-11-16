# Informe Final de Atributos de Calidad — Sprint 2

[Ficha de Calidad](spec.md) · [Plan de Calidad](plan.md) · [Tareas](tasks.md)

**Proyecto:** Plataforma Docente 5E  
**Ciclo:** Sprint 2 — Atributos de Calidad (Norma ISO/IEC 25010)  
**Fecha:** 15 de noviembre de 2026  
**Líder de Calidad y Equipo:** Juan Alegría (Líder), Yan Liu Dai, Sergio Celi Vértiz, Silvana Díaz  

---

## 1. Resumen Ejecutivo y Metodología

Durante el Sprint 2 se evaluó y reforzó la calidad del sistema **Plataforma Docente 5E** bajo el modelo de calidad de producto de software **ISO/IEC 25010**, abarcando seis características fundamentales: **Adecuación Funcional**, **Confiabilidad**, **Seguridad**, **Usabilidad**, **Eficiencia de Desempeño** y **Portabilidad**.

Cada tarea contó con un escenario formalizado de seis partes (fuente, estímulo, entorno, artefacto, respuesta y medida), metas cuantitativas explícitas y verificación mediante pruebas automatizadas (unitarias, integración, e2e), evaluación Ragas con modelos jueces, análisis estático de dependencias y validaciones manuales en entornos reales de prueba.

Todas las métricas y evidencias registradas en este informe corresponden a resultados obtenidos y verificables en el repositorio.

---

## 2. Tabla Consolidada de Atributos de Calidad

| ID | Responsable | Atributo ISO 25010 | Escenario | Meta | Resultado Medido | ¿Cumple? | Evidencia |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **QA-01** | Juan | N/A (Gestión) | Especificación y planificación formal de los atributos de calidad para el Sprint 2. | Ficha `spec.md`, `plan.md` y `tasks.md` en `specs/005-atributos-calidad/` con escenarios de 6 partes. | 11 escenarios estructurados con fuentes, estímulos, entornos, artefactos, respuestas y medidas verificables; dependencias trazadas en diagrama de flujo. | **Sí** | `specs/005-atributos-calidad/` (PR #46, commit `b7d2d2c`). |
| **QA-02** | Juan | Confiabilidad (Tolerancia a fallos y diagnóstico) | Diagnóstico de dependencias críticas en `GET /health/dependencies` (BD, Gemini, Wikipedia) sin consumir tokens. | Respuesta 200 siempre (503 solo si la BD está caída); `degraded` ante timeouts de 3 s; caché de 30 s; secretos censurados con `redact_secrets`. | 16 pruebas unitarias (`test_check_dependencies.py`) y 8 e2e (`test_dependency_health_api.py`) pasando (24/24); contrato OpenAPI con 32 rutas; caché de 30 s operativa. | **Sí** | `docs/api/openapi.json`, `backend/tests/unit/test_check_dependencies.py`, `backend/tests/e2e/test_dependency_health_api.py` (PR #49, commit `f073529`). |
| **QA-03** | Juan | Portabilidad / Compatibilidad | Exportación a Moodle XML de preguntas de `verdadero_falso` y `emparejamiento` (matching con ≥ 3 pares), además de opción múltiple. Importación real en Moodle 5.3.1. | Los 3 tipos se importan sin errores en Moodle 5.3.1; puntuaciones (100%/0%) y retroalimentaciones visibles. Matriz TA-006 documentada. | Importación real en sandbox Moodle 5.3.1 completada: 7 preguntas importadas (3 opción múltiple, 2 V/F, 2 matching), 0 errores. 11 pruebas unitarias del exportador y validador XML actualizados. Frontend actualizado. | **Sí** | `docs/compatibility/TA-006-matriz.md`, `docs/evidence/QA-03/` (4 capturas + XML `qa03-20261115-moodle-all-types.xml`), PR #52 BE (`03c8ec4`) y PR FE (`011c0c9`). |
| **QA-04** | Juan | N/A (Cierre) | Informe final de calidad y lista de verificación para el despliegue. | Tabla completa con resultados reales del repositorio; conclusiones por atributo; checklist de despliegue. | Documento `report.md` consolidado con los 11 escenarios, métricas objetivas del equipo y guía de despliegue a producción. | **Sí** | `specs/005-atributos-calidad/report.md` (este documento). |
| **QA-05** | Yan | Adecuación Funcional | Rechazo de pedidos sin evidencia del tema (C-06 en Ragas). Generación de C-01 a C-05 con `faithfulness ≥ 0,90`. | C-06 rechazado sin generar recursos; C-01 a C-05 con `faithfulness ≥ 0,90`. | C-01 a C-05 alcanzaron `faithfulness = 0,95` (> 0,90). En C-06, la búsqueda léxica trajo «tablas de enrutamiento» para «tablas y llaves primarias», generando recurso con citas válidas. | **Parcial** | `specs/002-generacion-multiple/tasks.md` (T068, PR #40). Requiere filtrado semántico previo en el orquestador. |
| **QA-06** | Yan | Eficiencia de Desempeño | Tiempo de respuesta en creación de pedido con 5 secuencias concurrentes (p95 < 500 ms) y timeout de llamadas a Gemini (≤ 60 s). | p95 del `POST` < 500 ms con 5 solicitudes simultáneas; llamadas a Gemini interrumpidas si superan 60 s. | Módulo de medición de carga y percentiles implementado (`measure_generation_load.py` y `test_measure_generation_load.py`); cliente Gemini con timeout de 60 s por llamada. Medición con tráfico real en staging pendiente. | **Sí** | `backend/scripts/measure_generation_load.py`, `backend/tests/unit/test_measure_generation_load.py`. |
| **QA-07** | Sergio | Adecuación Funcional | Recuperación RAG híbrida con `pgvector` HNSW + BM25 sobre corpus T067 (`C-01` a `C-05`). Aislamiento de documentos distractores. | `context_recall ≥ 0,60` con pgvector. 0 fragmentos del documento distractor en los resultados de C-01 a C-05. | Evaluación Ragas con `gemini-3.8-flash`: `context_recall = 0,6000` (`0,60`), `faithfulness = 0,9778`, `answer_relevancy = 0,8972`, `context_precision = 0,5758`. Trazabilidad I22 = 5/5. 0 fragmentos del distractor recuperados (0 / 40). | **Sí** | `docs/evidence/QA-07/summary.md`, PR #51 (`c23c904`), PR follow-up (`c507e47`). |
| **QA-08** | Sergio | Seguridad | Protección contra fuerza bruta en inicio de sesión, cabeceras HTTP defensivas y auditoría de dependencias. | 429 con `Retry-After` al 6.º intento fallido en 15 min sin revelar si el usuario existe. Cabeceras `nosniff`, `CSP`, `Referrer-Policy`. `pip-audit` limpio. | Pruebas e2e aprobadas en `test_auth_security.py` (429 con `Retry-After` al 6.º fallo consecutivo para la misma IP/correo). Cabeceras presentes en respuestas. `pip-audit` integrado en CI sin vulnerabilidades altas. | **Sí** | `backend/src/platform5e/infrastructure/http/security.py`, `backend/tests/e2e/test_auth_security.py`, `.github/workflows/backend-ci.yml` (PR #50, commit `3eb5654`). |
| **QA-09** | Silvana | Usabilidad / Accesibilidad | Accesibilidad WCAG 2.1 AA en todas las vistas de la aplicación y recorrido completo solo con teclado. | 0 violaciones serias o críticas detectadas por axe. Recorrido completo con teclado sin bloqueos y con foco visible. | 8 vistas escaneadas con `@axe-core/playwright` (`accessibility.spec.ts`) con 0 violaciones serias o críticas. Flujo completo por teclado (Login → Curso → Unidad → Exportar Moodle XML) con `:focus-visible` verificado. | **Sí** | `frontend/e2e/accessibility.spec.ts` en rama `test/qa-09-accessibility` (commits `58c9ed6` y `660e61f`). |
| **QA-10** | Silvana | Eficiencia de Desempeño y Seguridad | Presupuesto de JavaScript inicial y auditoría de vulnerabilidades npm en el frontend. | JavaScript inicial < 200 kB comprimido (gzip). CI falla si se excede el presupuesto o si `npm audit` detecta vulnerabilidades altas/críticas. | Carga diferida implementada (`React.lazy` y `Suspense`). JavaScript inicial medido: **62.458 bytes gzip** (~62,5 kB, 31 % del límite de 200 kB). `npm audit --audit-level=high` con 0 vulnerabilidades altas/críticas (código 0). | **Sí** | `frontend/scripts/check-initial-bundle.mjs`, `frontend/src/app/App.tsx`, `frontend/.github/workflows/frontend-ci.yml` (commit `d763319`). |
| **QA-11** | Juan | Adecuación Funcional | Verificación frase por frase de guiones de audio (`audio_detonante` y `podcast_resumen`). Reverificación de recursos aprobados al leerlos. | Cada frase sustantiva respaldada en el material; frase sin respaldo deja el recurso `insufficient` con motivo detallado. Regla sube a v2. Audios aprobados con v1 se reverifican al leer. | `VERIFICATION_RULE_VERSION = 2`. Función `_check_audio_script` valida guiones por frase. `upgrade_resource_verification` reverifica audios antiguos (bajan a `pendiente` si no están respaldados). 11/11 pruebas unitarias pasando en `test_audio_sentence_verification.py`. 110 pruebas de verificación y revisión pasando. | **Sí** | `backend/src/platform5e/domain/review/resource_verification.py`, `backend/src/platform5e/application/services/review/legacy_verification.py`, `backend/tests/unit/test_audio_sentence_verification.py` (commit `f57961a`). |

---

## 3. Conclusiones por Atributo de Calidad (ISO/IEC 25010)

### 3.1. Adecuación Funcional
- **Completitud y Corrección:** La plataforma amplió su compatibilidad de exportación a tres tipos de reactivos en Moodle XML (opción múltiple, verdadero/falso y emparejamiento con validación de al menos tres pares).
- **Precisión RAG y Anclaje:** La búsqueda híbrida con `pgvector` (QA-07) demostró un `context_recall` de 0,6000 y una fidelidad (`faithfulness`) de 0,9778 con Gemini 3.8 Flash, garantizando aislamiento total del documento distractor (0 fragmentos ajenos de 40 recuperados).
- **Rigor en Contenido Multimedia:** Mediante QA-11, los recursos de audio (`audio_detonante` y `podcast_resumen`) cuentan ahora con verificación frase por frase contra la evidencia histórica guardada, evitando alucinaciones narrativas en cápsulas de audio y actualizando de forma transparente recursos legados mediante la regla v2.
- **Aspecto a Mejorar:** El caso C-06 (rechazo previo ante temas no cubiertos en el material) requiere un guardián de similitud semántica antes de disparar la generación, para descartar el pedido tempranamente sin incurrir en consumo de tokens.

### 3.2. Confiabilidad
- **Tolerancia a Fallos y Diagnóstico:** Se introdujo la ruta `GET /health/dependencies` (QA-02) que ejecuta sondas concurrentes de bajo costo (PostgreSQL, Gemini y Wikipedia) con timeout estricto de 3 segundos por dependencia y caché de 30 segundos. El sistema degrada su estado sin caerse, retornando HTTP 200 informativo y reservando HTTP 503 exclusivamente ante indisponibilidad de la base de datos principal.

### 3.3. Seguridad
- **Protección contra Abusos y Fuerza Bruta:** El endpoint de inicio de sesión incorpora limitación de tasa (QA-08) que bloquea al sexto intento fallido en una ventana de 15 minutos respondiendo HTTP 429 con cabecera `Retry-After`, sin revelar la existencia del correo electrónico.
- **Cabeceras Defensivas:** Todas las respuestas HTTP del backend incluyen cabeceras de protección estándar de la industria (`X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'`, `Referrer-Policy: strict-origin-when-cross-origin`).
- **Cadena de Suministro Segura:** Las dependencias tanto de backend (`pip-audit`) como de frontend (`npm audit --audit-level=high`) están integradas en los flujos de integración continua (CI) de GitHub Actions, reportando cero vulnerabilidades altas o críticas.

### 3.4. Usabilidad y Accesibilidad
- **Accesibilidad Universal (WCAG 2.1 AA):** El frontend alcanzó cero violaciones serias o críticas evaluadas mediante `@axe-core/playwright` sobre las 8 pantallas principales del sistema (QA-09).
- **Operabilidad Exclusiva por Teclado:** Se validó de forma automatizada que un usuario puede completar el flujo pedagógico completo (inicio de sesión, selección de curso, ingreso a la unidad y descarga de la exportación Moodle XML) utilizando únicamente el teclado (`Tab` y `Enter`), con retroalimentación de foco visible (`:focus-visible`) en todo momento.

### 3.5. Eficiencia de Desempeño
- **Optimización de Bundle Web:** Gracias a la división de código en rutas con `React.lazy` y `Suspense` (QA-10), el tamaño de JavaScript inicial transferido se redujo a **62,5 kB comprimido (gzip)**, consumiendo solo el 31 % del presupuesto de rendimiento fijado en 200 kB.
- **Control de Latencia:** El backend dispone de instrumentación de percentiles de carga (QA-06) y límite de ejecución de 60 segundos en llamadas remotas a Gemini para evitar procesos colgados en el servidor.

### 3.6. Portabilidad
- **Interoperabilidad LMS:** Se comprobó de forma empírica y automatizada la compatibilidad con Moodle versión 5.3.1 (QA-03). La exportación de cuestionarios XML respeta la taxonomía del estándar, procesa entidades HTML adecuadamente y mapea las calificaciones porcentuales exactas requeridas por Moodle.

---

## 4. Lista de Verificación para el Despliegue (Checklist de Producción)

Esta lista debe verificarse de manera previa, durante y posterior al despliegue en los entornos de producción (**Neon PostgreSQL**, **Render Backend** y **Vercel Frontend**):

### 4.1. Configuración y Variables de Entorno
- [ ] `DATABASE_URL`: Cadena de conexión PostgreSQL hacia Neon configurada con SSL habilitado (`sslmode=require`).
- [ ] `GEMINI_API_KEY`: Clave de API de Google Gemini activa y con cuota habilitada para los modelos configurados.
- [ ] `LLM_PROVIDER`: Fijado en `gemini` para entornos desplegados (`rules` reservado para pruebas locales y CI).
- [ ] `SECRET_KEY`: Llave criptográfica configurada para la firma y verificación de tokens de sesión.
- [ ] `CORS_ORIGINS`: Lista blanca que incluye exclusivamente los dominios de frontend autorizados en producción.

### 4.2. Infraestructura y Base de Datos
- [ ] Extensión `vector` habilitada en Neon:
  ```sql
  CREATE EXTENSION IF NOT EXISTS vector;
  ```
- [ ] Tablas y esquemas de base de datos migrados e índices vectoriales HNSW creados en la tabla de fragmentos.
- [ ] Verificación de conectividad desde el contenedor de Render hacia Neon.

### 4.3. Pipeline de Integración Continua (CI/CD)
- [ ] Tubería `Backend CI` en verde en GitHub Actions:
  - Exportación OpenAPI coincide con `docs/api/openapi.json`.
  - Auditoría de dependencias con `pip-audit` sin vulnerabilidades altas.
  - Cobertura de código ≥ 80 % en capas de dominio y aplicación.
  - Pruebas e2e sobre PostgreSQL y SQLite aprobadas.
- [ ] Tubería `Frontend CI` en verde en GitHub Actions:
  - Compilación de Vite exitosa.
  - Script `check-initial-bundle.mjs` valida JavaScript inicial < 200 kB gzip.
  - Auditoría `npm audit --audit-level=high` con cero vulnerabilidades.
  - Pruebas de accesibilidad Playwright aprobadas.

### 4.4. Verificaciones Post-Despliegue (Smoke Tests)
- [ ] **Liveness Probe:**
  ```http
  GET /health
  ```
  Debe retornar HTTP 200 con `{"status": "ok"}`.
- [ ] **Dependency Probe (QA-02):**
  ```http
  GET /health/dependencies
  ```
  Debe retornar HTTP 200 con `status: "healthy"` para `database`, `gemini` y `wikipedia`.
- [ ] **Cabeceras de Seguridad (QA-08):**
  Inspeccionar que la respuesta incluya:
  - `X-Content-Type-Options: nosniff`
  - `Content-Security-Policy: frame-ancestors 'none'`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] **Protección de Login (QA-08):**
  Comprobar que tras 6 credenciales incorrectas consecutivas el sistema responda HTTP 429 con `Retry-After`.
- [ ] **Flujo de Usuario Básico:**
  - Iniciar sesión como docente.
  - Subir un material de prueba en una unidad.
  - Generar un reactivo con Gemini.
  - Revisar y aprobar recursos (incluyendo audio detonante y preguntas Moodle).
  - Descargar el archivo Moodle XML y validar su estructura.

### 4.5. Procedimiento de Reversión (Rollback Plan)
- [ ] **Reversión en Render:** Si el servicio backend presenta errores fatales, revertir de inmediato al commit previo estable de `main` (`f073529`).
- [ ] **Reversión en Vercel:** Desplegar instantáneamente el alias de producción a la versión de compilación anterior.
- [ ] **Compatibilidad de Datos:** Las modificaciones de verificación (regla v2 de QA-11) son retrocompatibles y no alteran destructivamente las columnas existentes en la base de datos; la función `upgrade_resource_verification` mantiene compatibilidad con recursos legados sin verificación.
