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
| QA-17 | Eficiencia de desempeño | PTb-1-G Tiempo medio de respuesta; PTb-5-G Rendimiento medio; PCa-2-G Capacidad de acceso de usuarios | Media y p95 en ms; peticiones por segundo; máximo de usuarios con p95 < 1 s y errores < 1 % |
| QA-18 | Eficiencia de desempeño / Fiabilidad | PCa-1-G Capacidad de procesamiento de transacciones; RRe-1-G Tiempo medio de recuperación | Peticiones por segundo en el punto de quiebre; segundos hasta que /health vuelve a 200 en < 1 s |

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

### QA-12 · Seguridad y compatibilidad — Dominio propio con HTTPS y redirección

**Responsable:** Juan (backend), Yan (frontend)

| Parte | Descripción |
| --- | --- |
| Fuente | Docente |
| Estímulo | El docente accede al frontend y a la API a través del dominio propio con HTTPS y certificado válido (Let's Encrypt / Vercel SSL); las peticiones con HTTP se redirigen a HTTPS y la consola del navegador no muestra advertencias de contenido mixto. |
| Entorno | Producción en la nube (Render para backend, Vercel para frontend con dominio personalizado) |
| Artefacto | Configuración de DNS, certificados SSL/TLS y enrutamiento en backend y frontend |
| Respuesta | La conexión se establece bajo protocolo seguro HTTPS con certificado válido y las peticiones no seguras se redirigen inmediatamente sin advertencias de contenido mixto |
| Medida | Redirección 301/308 de HTTP a HTTPS permanente en todas las rutas; certificado SSL/TLS válido; 0 advertencias de contenido mixto en la consola del navegador. |

---

### QA-13 · Seguridad y fiabilidad — Protección de la rama principal (main)

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | Desarrollador o colaborador del repositorio |
| Estímulo | El docente accede a la rama principal (main) y la encuentra protegida: los cambios solo ingresan por pull request con al menos una revisión aprobada y todos los flujos de CI (pruebas unitarias, lint y cobertura) en verde. |
| Entorno | Repositorios en GitHub (`Plataforma_Docente_backend` y `Plataforma_Docente_frontend`) |
| Artefacto | Reglas de protección de ramas (`Branch protection rules` / rulesets de GitHub) en `main` |
| Respuesta | Se rechazan commits directos a `main` y solo se habilita la fusión tras revisión aprobada y CI obligatoria completada en verde |
| Medida | 0 commits directos permitidos en `main`; mínimo 1 aprobación obligatoria de revisión; 100 % de los flujos de CI en verde antes de permitir la fusión. |

---

### QA-14 · Usabilidad y eficiencia de desempeño — Auditoría Lighthouse (ISO/IEC 25023: UAc-1-G, PTb-1-G)

**Responsable:** Silvana

| Parte | Descripción |
| --- | --- |
| Fuente | Docente |
| Estímulo | El docente navega por las pantallas principales del frontend (inicio de sesión, asistente de generación, visor de recurso) y Lighthouse reporta un puntaje de accesibilidad ≥ 90/100 y LCP ≤ 2,5 s en simulación móvil y de escritorio. |
| Entorno | Navegador web con auditoría automatizada de Lighthouse (perfiles móvil y escritorio) |
| Artefacto | Vistas principales del cliente web (`Plataforma_Docente_frontend`) |
| Respuesta | Las pantallas cargan con rapidez y ofrecen componentes accesibles sin barreras de navegación |
| Medida | Medida UAc-1-G: Puntaje de accesibilidad Lighthouse ≥ 90/100 en las 3 vistas. Medida PTb-1-G: Largest Contentful Paint (LCP) ≤ 2,5 s tanto en móvil como en escritorio. |

---

### QA-15 · Seguridad — Pruebas de inyección SQL (ISO/IEC 25023: SCo-1-G, SIn-2-G)

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Atacante |
| Estímulo | Un atacante envía cargas maliciosas de inyección SQL (comillas, OR 1=1, UNION SELECT, caracteres de escape) a todos los parámetros de ruta, consulta y cuerpo de la API; la aplicación responde con 422 Unprocessable Entity o 400 Bad Request, no ejecuta sentencias no parametrizadas y no expone trazas internas del motor relacional. |
| Entorno | Servidor de API FastAPI local o de staging conectado a PostgreSQL |
| Artefacto | Puntos finales de la API FastAPI y repositorio de datos con SQLAlchemy |
| Respuesta | La aplicación valida y sanea todas las entradas, rechaza las cargas con errores 422 o 400 y ejecuta únicamente sentencias parametrizadas sin exponer detalles internos |
| Medida | Medidas SCo-1-G y SIn-2-G: $X = 1 - A/B = 1,0$ (0 rutas vulnerables entre todas las rutas probadas con `sqlmap`, `bandit` y `semgrep`). 0 hallazgos altos o críticos en el análisis estático. |

---

### QA-16 · Fiabilidad — Límite de tasa por IP y protección ante ráfagas (ISO/IEC 25023: RAv-1-G, RFt-1-G)

**Responsable:** Sergio

| Parte | Descripción |
| --- | --- |
| Fuente | Cliente malicioso o error de bucle en el cliente |
| Estímulo | Un cliente malicioso o un error de bucle en el cliente genera una ráfaga de peticiones a la API; el middleware de límite de tasa responde con 429 Too Many Requests al superar el umbral configurado por IP y por minuto, protegiendo la base de datos y manteniendo /health disponible para el resto de usuarios. |
| Entorno | Servidor FastAPI en ejecución |
| Artefacto | Middleware de límite de tasa y control de tamaño de carga útil en FastAPI |
| Respuesta | El sistema mitiga la saturación respondiendo 429 con cabecera `Retry-After` a las peticiones que exceden el límite, preservando los recursos y la disponibilidad del servicio |
| Medida | Medidas RAv-1-G y RFt-1-G: $X = A/B = 1,0$ (100 % de respuestas 200 en `/health` durante la ráfaga de saturación). Límite de tasa activo por IP y minuto con cabecera `Retry-After`. |

---

### QA-17 · Eficiencia de desempeño — Prueba de carga con Locust (ISO/IEC 25023: PTb-1-G, PTb-5-G, PCa-2-G)

**Responsable:** Yan

| Parte | Descripción |
| --- | --- |
| Fuente | 20 docentes concurrentes |
| Estímulo | 20 docentes concurrentes generan recursos y consultan la API de forma sostenida durante 5 minutos (prueba de carga con Locust); el tiempo de respuesta p95 de los puntos finales de lectura no supera 1,0 s, la tasa de fallos es < 1 % y la tasa de peticiones por segundo se mantiene estable sin fugas de memoria. |
| Entorno | Backend local contra base de datos PostgreSQL local (`LLM_PROVIDER=rules`) |
| Artefacto | Puntos finales de lectura y generación de la API FastAPI |
| Respuesta | La API atiende concurrentemente la carga sin degradación del rendimiento ni saturación de conexiones |
| Medida | Medidas PTb-1-G, PTb-5-G y PCa-2-G: Tiempo de respuesta p95 en lectura ≤ 1,0 s; tasa de fallos < 1 %; peticiones por segundo sostenidas y 0 fugas de memoria durante 5 min con 20 usuarios. |

---

### QA-18 · Eficiencia de desempeño y fiabilidad — Prueba de estrés con JMeter (ISO/IEC 25023: PCa-1-G, RRe-1-G)

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Carga masiva incremental |
| Estímulo | La carga sobre la API se incrementa progresivamente por encima del tráfico nominal hasta saturar los recursos del servidor (prueba de estrés con JMeter); el sistema identifica el punto de quiebre (p95 > 2 s o tasa de error > 5 %), no corrompe datos ni bloquea conexiones huérfanas, y se recupera automáticamente una vez cesa la sobrecarga. |
| Entorno | Backend local en `http://localhost:8000` con PostgreSQL en Docker (`LLM_PROVIDER=rules`) |
| Artefacto | Servidor de API FastAPI y motor de persistencia |
| Respuesta | El servidor procesa la rampa de estrés, registra el umbral de ruptura sin caída irrecuperable ni corrupción, y restablece su operación nominal al cesar la sobrecarga |
| Medida | Medidas PCa-1-G y RRe-1-G: Capacidad de procesamiento (RPS) y usuarios en el punto de quiebre (p95 > 2 s o errores > 5 %); tiempo de recuperación hasta responder `/health` en 200 en < 1 s inferior a 10 s tras finalizar la prueba; 0 conexiones huérfanas y 0 datos corruptos. |

---

### QA-19 · Calidad consolidada — Informe final de calidad del Sprint 2

**Responsable:** Juan

| Parte | Descripción |
| --- | --- |
| Fuente | Equipo de desarrollo y aseguramiento de calidad |
| Estímulo | El equipo ejecuta la consolidación de atributos de calidad del Sprint 2; el informe final en specs/005-atributos-calidad/report.md integra las mediciones de QA-01 a QA-19 con evidencia enlazada, trazabilidad a los PR integrados y verificación cruzada contra los requisitos no funcionales del proyecto. |
| Entorno | Repositorio de código y documentación del Sprint 2 |
| Artefacto | Informe consolidado `specs/005-atributos-calidad/report.md` |
| Respuesta | El informe sintetiza los resultados medidos, enlaces a evidencias reales, estado de cumplimiento de los 19 escenarios y lista de verificación de despliegue |
| Medida | 100 % de las tareas QA-01 a QA-19 documentadas con sus métricas reales (o justificación si alguna no aplica), evidencias enlazadas y trazabilidad a PRs integrados en `main`. |

## Supuestos

- El código del Sprint 1 está cerrado y funcional en `main`.
- Las pruebas de calidad usan `LLM_PROVIDER=rules` en CI y en local salvo que se indique lo contrario.
- El sandbox de Moodle (sandbox.moodledemo.net) está disponible para la importación manual; se reinicia a cada hora en punto.
- La clave de Gemini de Render es de Yan y no se usa en CI ni en local sin autorización.
- QA-07 depende del PR #40 de Yan (corpus de T067 y resultados de Ragas de T068)
