# Atributos de calidad — Sprint 2

**Ficha** QA · ISO 25010
**Responsable** Juan (líder del sprint)
**Estado** Borrador (14 de noviembre de 2026)
**Referencias** [Constitución](../../.specify/memory/constitution.md), [OpenAPI](../../docs/api/openapi.json), [REV-01](../001-revision-citas/spec.md), [GEN-01](../002-generacion-multiple/spec.md), [CC-01](../003-cuentas-y-cursos/spec.md), [MAT-01](../004-material-y-evidencia/spec.md)

## Objetivo y alcance

El Sprint 2 mejora los atributos de calidad de la Plataforma Docente según ISO 25010: fiabilidad, compatibilidad, adecuación funcional, eficiencia de desempeño, seguridad y usabilidad. Cada tarea tiene un escenario de calidad con las seis partes (fuente, estímulo, entorno, artefacto, respuesta y medida) y un criterio medible. El sprint cierra el lunes 16 de noviembre de 2026 a las 9:00.

## Origen

Hallazgos del Sprint 1 que motivan cada meta:

| Hallazgo | Tarea que lo aborda |
| --- | --- |
| Ragas dio context_recall 0,20 con SQLite (solo búsqueda léxica); la búsqueda híbrida con pgvector, que usa producción, no se midió| QA-07 |
| El caso C-06 de Ragas no pasa: sin material del tema se genera un recurso en vez de rechazarlo. | QA-05 |
| No hay límite de intentos de inicio de sesión ni cabeceras de seguridad (`X-Content-Type-Options`, `Content-Security-Policy`, `Referrer-Policy`). | QA-08 |
| `GET /health` no revisa dependencias externas (Gemini, Wikipedia, base de datos); si una cae, no hay forma de saberlo sin probar la función completa. | QA-02 |
| No hay revisión de accesibilidad ni recorrido con teclado. | QA-09 |
| El exportador Moodle XML solo soporta `item_opcion_multiple`; `verdadero_falso` y `emparejamiento` no se exportan. | QA-03 |
| No hay presupuesto del bundle del frontend ni auditoría de dependencias en CI. | QA-10 |
| Los guiones de `audio_detonante` y `podcast_resumen` no se verifican frase por frase contra el material. | QA-11 |

## Escenarios de calidad

### QA-02 · Fiabilidad — Diagnóstico de dependencias (EN-028)

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Operador o sistema de monitoreo |
| Estímulo | Consulta `GET /health/dependencies` mientras Gemini o Wikipedia no responden |
| Entorno | Producción, servicio en funcionamiento normal |
| Artefacto | Ruta `/health/dependencies` del backend |
| Respuesta | Responde 200 con el servicio afectado como `degraded` (`down` o `slow`); la aplicación sigue funcionando con el respaldo (generador por reglas para Gemini, subida manual para Wikipedia) |
| Medida | Si Gemini o Wikipedia no responden en 3 s, la ruta informa `degraded` en menos de 4 s. La base de datos caída produce 503. El resultado se guarda en caché durante 30 s. |

#### Validación de comportamiento con dependencia caída (acuerdo con Yan y Sergio)

- **Yan (Generación):** Si Gemini está caído (`down`) o lento (`slow`), el caso de uso `RunGenerationRequest` recurre al generador por reglas (`RuleBasedGenerator`) registrando `fallback = true` y el motivo genérico en `fallbackReason` (sin exponer claves ni mensajes del proveedor). Los pedidos de los docentes no se interrumpen.
- **Sergio (Material y Evidencia):** Si Wikipedia no responde o está degradada, la ruta de importación desde fuentes abiertas (`POST /documents/from-topic`) responde 503 (`SOURCE_UNAVAILABLE`) con un mensaje claro al docente. La subida manual de archivos locales (PDF, TXT, PPTX, DOCX) y su procesamiento/vectorización continúan operando normalmente.

---

### QA-03 · Compatibilidad — Exportación Moodle XML con tres tipos de pregunta

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Docente |
| Estímulo | Exporta recursos aprobados de tipo opción múltiple, verdadero/falso y emparejamiento a Moodle XML e importa el archivo en Moodle |
| Entorno | Moodle 5.3.1 (sandbox.moodledemo.net) |
| Artefacto | Exportador Moodle XML (`moodle_xml_exporter.py`) y archivo generado |
| Respuesta | Los tres tipos se importan sin errores en Moodle, con su calificación y retroalimentación correctas |
| Medida | Opción múltiple, verdadero/falso y emparejamiento se importan sin errores en Moodle 5.3.1, con la calificación asignada correctamente y la retroalimentación visible al responder bien y mal |

---

### QA-05 · Adecuación funcional — Rechazo sin material del tema (C-06)

**Responsable:** Yan

| Parte | Descripción |
| --- | --- |
| Fuente | Docente |
| Estímulo | Pide generar un recurso para una unidad cuyo material no trata el tema solicitado |
| Entorno | Producción, material procesado pero sin relación con el tema |
| Artefacto | Caso de uso de generación y evaluación Ragas |
| Respuesta | C-06 pasa: sin material del tema no se genera ningún recurso. C-01 a C-05 siguen generando con `faithfulness` ≥ 0,90. |
| Medida | C-06 rechaza el pedido; C-01 a C-05 generan recursos con `faithfulness` ≥ 0,90 |

---

### QA-06 · Eficiencia de desempeño — Tiempos de respuesta y límite de llamada

**Responsable:** Yan

| Parte | Descripción |
| --- | --- |
| Fuente | 5 docentes en paralelo |
| Estímulo | Cada uno crea un pedido de generación simultáneamente |
| Entorno | Producción con Gemini habilitado |
| Artefacto | Ruta `POST /api/v1/generation-requests` y cliente de Gemini |
| Respuesta | Los pedidos se aceptan y ejecutan dentro de los límites de tiempo |
| Medida | Crear un pedido responde en p95 < 500 ms. Ninguna llamada a Gemini queda colgada más de 60 s. |

---

### QA-07 · Adecuación funcional — Búsqueda híbrida con pgvector

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Sistema de generación |
| Estímulo | Recupera fragmentos de evidencia para los casos C-01 a C-05 usando pgvector |
| Entorno | PostgreSQL con pgvector habilitado |
| Artefacto | `HybridEvidenceRetriever` con búsqueda vectorial |
| Respuesta | Los fragmentos recuperados son relevantes al tema y no incluyen fragmentos del documento distractor |
| Medida | `context_recall` ≥ 0,60 con pgvector. Ningún fragmento del documento distractor aparece en los resultados de C-01 a C-05. |

---

### QA-08 · Seguridad — Límite de intentos y cabeceras

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Atacante o usuario con credenciales incorrectas |
| Estímulo | 6 intentos fallidos de inicio de sesión en 15 minutos para el mismo correo e IP |
| Entorno | Producción |
| Artefacto | Ruta de inicio de sesión y middleware de cabeceras |
| Respuesta | El 6.º intento responde 429 con `Retry-After`, sin revelar si el correo existe. Las cabeceras de seguridad están presentes en todas las respuestas. |
| Medida | 429 con `Retry-After` al 6.º intento fallido en 15 min para el mismo correo e IP, sin revelar si el correo existe. Cabeceras presentes: `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'`, `Referrer-Policy`. `pip-audit` sin vulnerabilidades altas. |

---

### QA-09 · Usabilidad — Accesibilidad WCAG 2.1 AA

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | Usuario con discapacidad visual o motora |
| Estímulo | Navega la aplicación completa usando solo el teclado y un lector de pantalla |
| Entorno | Navegador con axe integrado en Playwright |
| Artefacto | Frontend (todas las páginas) |
| Respuesta | La aplicación es navegable y operable sin ratón, sin violaciones serias o críticas |
| Medida | 0 violaciones serias o críticas de WCAG 2.1 AA detectadas por axe. Recorrido completo solo con teclado sin bloqueos. |

---

### QA-10 · Eficiencia y seguridad — Presupuesto del bundle y auditoría npm

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | CI del frontend |
| Estímulo | Se construye el bundle de producción y se auditan las dependencias |
| Entorno | GitHub Actions |
| Artefacto | Bundle de producción y dependencias npm |
| Respuesta | El bundle no excede el presupuesto y no hay vulnerabilidades altas en las dependencias |
| Medida | JavaScript inicial < 200 kB comprimido (gzip). La CI falla si se pasa del presupuesto o si `npm audit` encuentra vulnerabilidades altas. |

---

### QA-11 (opcional) · Adecuación funcional — Verificación frase por frase de guiones de audio

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Sistema de revisión |
| Estímulo | Se lee un recurso de tipo `audio_detonante` o `podcast_resumen` aprobado |
| Entorno | Verificación al guardar o al leer un recurso aprobado con versión de regla anterior |
| Artefacto | `resource_verification.py` |
| Respuesta | Cada frase del guion (`script`) tiene respaldo en los fragmentos citados, con el mismo criterio que los demás textos |
| Medida | Cada frase del guion tiene respaldo en el material. Un guion con una frase sin respaldo queda `insufficient` con el motivo que nombra la frase. Los audios aprobados antes del cambio se reverifican al leerlos. |

## Supuestos

- El código del Sprint 1 está cerrado y funcional en `main`.
- Las pruebas de calidad usan `LLM_PROVIDER=rules` en CI y en local salvo que se indique lo contrario.
- El sandbox de Moodle (sandbox.moodledemo.net) está disponible para la importación manual; se reinicia a cada hora en punto.
- La clave de Gemini de Render es de Yan y no se usa en CI ni en local sin autorización.
- QA-07 depende del PR #40 de Yan (corpus de T067 y resultados de Ragas de T068)
