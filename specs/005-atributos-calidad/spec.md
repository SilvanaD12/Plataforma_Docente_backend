# Atributos de calidad — Sprint 2

**Ficha** QA · ISO 25010
**Responsable** Juan (líder del sprint)
**Estado** Borrador (17 de noviembre de 2026)
**Referencias** [Constitución](../../.specify/memory/constitution.md), [OpenAPI](../../docs/api/openapi.json), [REV-01](../001-revision-citas/spec.md), [GEN-01](../002-generacion-multiple/spec.md), [CC-01](../003-cuentas-y-cursos/spec.md), [MAT-01](../004-material-y-evidencia/spec.md)

## Objetivo y alcance

El Sprint 2 mejora los atributos de calidad de la Plataforma Docente según ISO 25010: fiabilidad, compatibilidad, adecuación funcional, eficiencia de desempeño, seguridad y usabilidad. Cada tarea tiene un escenario de calidad con las seis partes (fuente, estímulo, entorno, artefacto, respuesta y medida) y un criterio medible. El sprint cierra el domingo 22 de noviembre de 2026.

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
| Revisión del profesor del 17/11/2026: dominio propio, ramas, Lighthouse y pruebas medidas con ISO/IEC 25023 (seguridad, usabilidad, rendimiento) | QA-12 a QA-19 |

## Medidas ISO/IEC 25023

| Tarea | Característica ISO 25010 | Medida ISO/IEC 25023 | Fórmula |
| --- | --- | --- | --- |
| QA-14 | Usabilidad / Eficiencia de desempeño | UAc-1-G Accesibilidad para usuarios con discapacidad; PTb-1-G Tiempo medio de respuesta | Puntaje de accesibilidad de Lighthouse; LCP medio por pantalla |
| QA-15 | Seguridad | SCo-1-G Controlabilidad del acceso; SIn-2-G Prevención de corrupción de datos internos | X = 1 − A/B (A = rutas con inyección confirmada, B = rutas probadas) |
| QA-16 | Fiabilidad | RAv-1-G Disponibilidad del sistema; RFt-1-G Prevención de fallos | X = A/B (A = respuestas 200 de /health durante la ráfaga, B = consultas a /health) |
| QA-17 | Eficiencia de desempeño | PTb-1-G Tiempo medio de respuesta; PTb-5-G Rendimiento medio; PCa-2-G Capacidad de acceso de usuarios | Media y p95 en ms por escalón (10, 25, 50 y 100 usuarios); peticiones por segundo; capacidad = máximo de usuarios con p95 < 1 s y errores < 1 % |
| QA-18 | Eficiencia de desempeño / Fiabilidad | PCa-1-G Capacidad de procesamiento de transacciones; RRe-1-G Tiempo medio de recuperación | Peticiones por segundo del último escalón que cumple (p95 ≤ 5 s y errores ≤ 5 %); segundos hasta que /health vuelve a 200 en < 1 s |

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

---

### QA-12 · Portabilidad y seguridad — Dominio propio con HTTPS

**Responsable:** Juan (backend), Yan (frontend)

| Parte | Descripción |
| --- | --- |
| Fuente | Docente o evaluador |
| Estímulo | Abre la plataforma y usa la API desde el dominio propio del proyecto |
| Entorno | Producción (Vercel para el frontend y Render para el backend), con el dominio obtenido del GitHub Student Developer Pack |
| Artefacto | Registros DNS, dominio personalizado y certificado en Vercel y Render, variables CORS_ALLOWED_ORIGINS (Render) y VITE_API_URL (Vercel) |
| Respuesta | El frontend carga en https://<dominio> y consume la API en https://api.<dominio> sin errores de CORS; HTTP redirige a HTTPS |
| Medida | Certificado válido en ambos; GET https://api.<dominio>/health responde 200; redirección permanente (301 o 308) de HTTP a HTTPS; 0 advertencias de contenido mixto en la consola; la dirección .vercel.app ya no aparece en los repositorios; LLM_TIMEOUT_SECONDS=60 en Render. |

---

### QA-13 · Mantenibilidad — Limpieza de ramas y borrado automático

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | Equipo de desarrollo |
| Estímulo | Revisa las ramas remotas de los dos repositorios después de integrar el Sprint 1 y las tareas QA-01 a QA-11 |
| Entorno | GitHub (Plataforma_Docente_backend y Plataforma_Docente_frontend) |
| Artefacto | Ramas remotas y la opción «Automatically delete head branches» de cada repositorio |
| Respuesta | Solo quedan main y las ramas con PR abierto; las ramas de los PR fusionados se borran solas desde ahora |
| Medida | 0 ramas remotas ya integradas en main (comprobado con git branch -r --merged origin/main); «Automatically delete head branches» activado en ambos repositorios; PR #39 del backend y PR #19 del frontend cerrados sin fusionar. Evidencia en docs/evidence/QA-13/. |

---

### QA-14 · Usabilidad y eficiencia de desempeño — Lighthouse (ISO/IEC 25023: UAc-1-G, PTb-1-G)

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | Docente con navegador de escritorio o móvil |
| Estímulo | Abre las pantallas principales de la plataforma |
| Entorno | CI del frontend con Lighthouse CI (páginas públicas /login y /registro, servidas con npm run preview) y producción con una cuenta de demostración (/login, /courses, una unidad /courses/<id>/units/<id> y /downloads) |
| Artefacto | Frontend (Plataforma_Docente_frontend) |
| Respuesta | Las pantallas cargan rápido, son accesibles y siguen buenas prácticas; la CI falla si una página baja de los mínimos |
| Medida | Escritorio: Rendimiento ≥ 90, Accesibilidad ≥ 95, Buenas prácticas ≥ 90 y SEO ≥ 90. Móvil: Rendimiento ≥ 80. Se registran también LCP y TBT por pantalla (UAc-1-G = puntaje de accesibilidad; PTb-1-G = LCP medio). |

---

### QA-15 · Seguridad — Inyección SQL (ISO/IEC 25023: SCo-1-G, SIn-2-G)

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Atacante anónimo o con sesión de docente |
| Estímulo | Envía cargas de inyección SQL (' OR '1'='1, UNION SELECT, '; DROP TABLE ...; --, comillas y caracteres de escape) en parámetros de consulta y cuerpos JSON |
| Entorno | Pila local con PostgreSQL en Docker y LLM_PROVIDER=rules |
| Artefacto | POST /api/v1/sessions, GET /api/v1/documents/search, POST y PUT /api/v1/courses, POST /api/v1/generation-requests/interpret y la persistencia con SQLAlchemy |
| Respuesta | La API responde 4xx o resultados vacíos, nunca 500, nunca expone trazas del motor y nunca devuelve datos de otro docente |
| Medida | X = 1 − A/B = 1 (A = rutas con inyección confirmada por sqlmap, B = rutas probadas); 0 hallazgos altos de Bandit y Semgrep (los medios se informan); pruebas e2e con cargas de inyección en verde. |

---

### QA-16 · Fiabilidad — Protección contra denegación de servicio (ISO/IEC 25023: RAv-1-G, RFt-1-G)

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Cliente que envía ráfagas de peticiones o cuerpos demasiado grandes |
| Estímulo | Ráfaga sobre las rutas costosas y envíos con cuerpo mayor al permitido |
| Entorno | Pila local con PostgreSQL en Docker y LLM_PROVIDER=rules |
| Artefacto | Límite de peticiones por IP (respetando TRUSTED_PROXIES) en POST /api/v1/generation-requests, POST /api/v1/generation-requests/interpret, POST /api/v1/documents, POST /api/v1/documents/from-topic, POST /api/v1/documents/{document_id}/process, POST /api/v1/units/{unit_id}/exports y POST /api/v1/units/{unit_id}/resources/{resource_id}/regenerations; límite de tamaño del cuerpo |
| Respuesta | Al superar el límite por IP responde 429 con Retry-After; un cuerpo demasiado grande se rechaza con 413 antes de leerlo; el servicio sigue disponible |
| Medida | 429 con Retry-After en ráfagas (límite configurable por variable de entorno); 413 cuando Content-Length supera 25 MB en la subida de archivos y 1 MB en las rutas JSON; pruebas e2e del 429 y del 413 en verde; durante una ráfaga de 200 usuarios por 2 minutos con el locustfile de QA-17, disponibilidad X = A/B = 1 (A = respuestas 200 de /health, B = consultas a /health) y el proceso no se reinicia. |

---

### QA-17 · Eficiencia de desempeño — Concurrencia y capacidad con Locust (ISO/IEC 25023: PTb-1-G, PTb-5-G, PCa-2-G)

**Responsable:** Yan

| Parte | Descripción |
| --- | --- |
| Fuente | 10, 25, 50 y 100 docentes simultáneos |
| Estímulo | Cada docente inicia sesión, lista cursos, busca evidencia, crea pedidos de generación y consulta su estado |
| Entorno | Pila local con PostgreSQL en Docker y LLM_PROVIDER=rules |
| Artefacto | API del backend |
| Respuesta | Atiende a todos los docentes con tiempos aceptables y sin errores del servidor |
| Medida | Por escalón (3 minutos cada uno): p50, p95, peticiones por segundo y % de errores. Capacidad (PCa-2-G) = mayor número de usuarios con p95 < 1 s y errores < 1 %. |

---

### QA-18 · Eficiencia de desempeño y fiabilidad — Punto de quiebre con JMeter (ISO/IEC 25023: PCa-1-G, RRe-1-G)

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Carga creciente de docentes simulados |
| Estímulo | Escalones de 50, 100, 200, 400 y 800 hilos (2 minutos cada uno, rampa de 30 s) hasta que el servicio se degrada |
| Entorno | Pila local con PostgreSQL en Docker y LLM_PROVIDER=rules |
| Artefacto | API del backend |
| Respuesta | Se identifica el escalón en que el servicio deja de cumplir y el servicio se recupera al bajar la carga |
| Medida | Punto de quiebre = primer escalón con errores (5xx, tiempos agotados o conexiones rechazadas) > 5 % o p95 > 5 s. PCa-1-G = peticiones por segundo del último escalón que cumple. RRe-1-G = segundos desde el fin de la carga hasta que /health responde 200 en menos de 1 s (meta: menos de 10 s). Dos corridas: antes y después de QA-16. Los 429 TOO_MANY_ACTIVE_REQUESTS son respuesta de negocio esperada y se cuentan aparte. |

---

### QA-19 · Cierre — Informe final con ISO/IEC 25023

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Profesor del curso |
| Estímulo | Revisa el cierre del Sprint 2 |
| Entorno | Repositorio del backend |
| Artefacto | specs/005-atributos-calidad/report.md |
| Respuesta | El informe presenta cada tarea con su medida ISO/IEC 25023, fórmula, valor medido, meta, cumplimiento y evidencia |
| Medida | QA-01 a QA-19 en la tabla consolidada; solo valores presentes en docs/evidence/ o en los PR integrados; lo no medido queda como «pendiente» con su motivo. |

## Supuestos

- El código del Sprint 1 está cerrado y funcional en `main`.
- Las pruebas de calidad usan `LLM_PROVIDER=rules` en CI y en local salvo que se indique lo contrario.
- El sandbox de Moodle (sandbox.moodledemo.net) está disponible para la importación manual; se reinicia a cada hora en punto.
- La clave de Gemini de Render es de Yan y no se usa en CI ni en local sin autorización.
- QA-07 depende del PR #40 de Yan (corpus de T067 y resultados de Ragas de T068)
