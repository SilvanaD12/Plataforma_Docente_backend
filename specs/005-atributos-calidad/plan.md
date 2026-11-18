# Plan de atributos de calidad — Sprint 2

[Ficha QA](spec.md) · [Tareas](tasks.md)

**Rama** `docs/qa-01-quality-spec` (documentación) · **Fecha** 2026-11-14 · **Cierre** 2026-11-16 09:00

## Resumen

El Sprint 2 aborda los hallazgos del Sprint 1 en ocho atributos de calidad ISO 25010. Cada tarea produce un cambio acotado, con pruebas automáticas y evidencia medible. El enfoque es defensivo: medir primero, corregir después y registrar el resultado aunque no alcance la meta.

## Contexto técnico

| Campo | Valor |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL (Neon, pgvector) o SQLite. Arquitectura hexagonal. |
| Frontend | React 18, TypeScript 5.6, Vite 5, Vitest 3, Playwright. |
| CI | GitHub Actions. Backend: cobertura ≥ 80 % de `domain` + `application`, e2e con SQLite y PostgreSQL, verificación OpenAPI. Frontend: lint, test, build, e2e. |
| Despliegue | Backend en Render, frontend en Vercel. |
| IA | `LLM_PROVIDER=rules` en CI y local. Gemini solo en Render con la clave de Yan. |

## Enfoque técnico por tarea

### QA-01 · Especificación de calidad

**Responsable:** Juan · **Tipo:** Documentación

Crear `specs/005-atributos-calidad/` con `spec.md`, `plan.md` y `tasks.md` siguiendo las plantillas y el estilo de los specs 001 y 002. Un escenario de calidad por tarea con las seis partes de ISO 25010. Sin cambios de código.

---

### QA-02 · Diagnóstico de dependencias (`GET /health/dependencies`)

**Responsable:** Juan · **Tipo:** Backend · **Atributo:** Fiabilidad

**Enfoque:** Puerto `DependencyProbePort` en `application/ports/outbound`, caso de uso que ejecuta las comprobaciones en paralelo con tiempo límite de 3 s, adaptadores en `infrastructure`:
- **Base de datos:** `SELECT 1`.
- **Gemini:** Consulta de metadatos del modelo (`GET` del modelo, 0 tokens). Si `LLM_PROVIDER=rules` o no hay clave: `not_configured`.
- **Wikipedia:** Consulta liviana a la misma API en español que usa la importación.

Respuesta siempre 200 (503 solo si la base de datos está caída). Caché de 30 s. Motivos genéricos con `public_reason` / `redact_secrets`.

**Validación de Yan y Sergio:** Yan confirma que la generación usa el generador por reglas cuando Gemini está caído, con su motivo. Sergio confirma que la importación desde Wikipedia muestra el error sin afectar la subida manual.

---

### QA-03 · Moodle XML con tres tipos y matriz TA-006

**Responsable:** Juan · **Tipo:** Backend + Frontend (si hace falta) · **Atributo:** Compatibilidad

**Enfoque:**
- `verdadero_falso` → `<question type="truefalse">`: una pregunta por afirmación, respuesta correcta en `fraction="100"`, retroalimentación con cita.
- `emparejamiento` → `<question type="matching">`: un `<subquestion>` por par (mínimo 3), `shuffleanswers` activo, retroalimentación general.
- Actualizar la elegibilidad de exportación para los tres tipos.
- Actualizar mensajes del frontend si mencionan que Moodle solo exporta opción múltiple.
- Importación real en Moodle 5.3.1, con capturas en `docs/evidence/QA-03/`.
- Matriz TA-006 en `docs/compatibility/TA-006-matriz.md`.

---

### QA-04 · Informe final de calidad

**Responsable:** Juan · **Tipo:** Documentación

**Enfoque:** Recopilar resultados de todas las tareas tras la integración. Tabla con ID, responsable, atributo, escenario, meta, resultado, ¿cumple? y evidencia. Conclusión por atributo. Lista de verificación para el despliegue.

**Dependencia:** Va al final, después de todos los PR del equipo.

---

### QA-05 · Rechazo sin material del tema (C-06)

**Responsable:** Yan · **Tipo:** Backend · **Atributo:** Adecuación funcional

**Enfoque:** C-06 pasa sin generar si no hay material del tema. C-01 a C-05 siguen generando con `faithfulness` ≥ 0,90. Evaluación con Ragas.

**Diseño.** Reemplaza T074 de `specs/002-generacion-multiple`. La comprobación va en el pedido de generación, justo después de recuperar la evidencia y antes de redactar, y no usa IA: funciona igual con `LLM_PROVIDER=rules`.

- **Tema pedido.** Son las indicaciones del docente. Sin indicaciones no hay nada que comprobar: el resultado de aprendizaje siempre es de la unidad. Tampoco se comprueba si las indicaciones dejan menos de 2 términos (por ejemplo, «Usa ejemplos breves» o «¿Cuáles son las características principales de UDP?»).
- **Términos del tema.** Palabras de las indicaciones en minúsculas y sin tildes, de 3 o más letras, o siglas de 2 en mayúsculas (IP). Se quitan las palabras vacías del español, las de estilo, pedagogía o tipo de recurso (breve, ejemplos, estudiantes, explica, actividad, pregunta, usa, glosario…) y las que solo formulan la pregunta (diferencia, características, principal, función, términos clave, conviene…).
- **Frases del tema.** Dos términos seguidos, o unidos por «de», «del», «de la»…: «protocolo de transporte», «llaves primarias», «modelo relacional».
- **Medida absoluta.** Cobertura: qué parte de los términos aparece en los fragmentos recuperados, con igualdad sin tildes y con el singular y el plural («capa» y «capas»). No se usa la relevancia de BM25 ni de la fusión híbrida, que se normaliza y siempre vale 1,0 en el primer fragmento. Tampoco se comparan raíces: «relacional» coincidiría con «relación», que aparece en textos de cualquier tema.
- **Decisión.** Se rechaza si la cobertura queda por debajo del umbral **y** no aparece ninguna frase del tema. Una frase presente basta, porque las palabras de un escenario no están en el material aunque el tema sí («una empresa que transmite en vivo» sobre «protocolo de transporte», c04). Y una palabra suelta puede coincidir con otro sentido: «tablas» de enrutamiento y «modelo» OSI en C-06.
- **Umbral.** `TOPIC_COVERAGE_THRESHOLD` (`infrastructure/settings.py`), 0,5 por defecto; 0 apaga la comprobación. En la medición, los casos que deben generar y no tienen ninguna frase presente (c02, c03, c05, c07 y C-05) tienen una cobertura de 0,60 como mínimo (c07), y C-06 tiene 0,40. El umbral de 0,5 queda entre los dos.
- **Secuencias.** Una secuencia comparte una sola recuperación y las mismas indicaciones, así que se decide una vez por pedido. Si no pasa, ningún paso redacta.
- **Al rechazar.** No se redacta ni se guarda ningún recurso. El pedido y sus pasos terminan `failed` con el código existente `INSUFFICIENT_EVIDENCE` y un motivo que nombra lo que falta, como lo escribió el docente: «El material de la unidad no trata «llaves primarias, modelo relacional». Sube material sobre ese tema o cambia las indicaciones.». La evidencia recuperada queda guardada (`GET /generation-requests/{id}/evidence`). La regeneración desde Revisión usa la misma ejecución, así que aplica la misma comprobación y responde 409 con ese motivo.
- **Código.** `domain/generation/topic_coverage.py` (términos, frases y cobertura) y `RunGenerationRequest` (decisión y motivo). Pruebas: `tests/unit/test_topic_coverage.py` y `tests/e2e/test_collect_samples.py`.

**Medición** (16/11/2026; sin IA, en un servidor local con SQLite, `LLM_PROVIDER=rules` y búsqueda `bm25_fallback`, `topK` 8). Casos de `backend/evaluation/cases_t067.json` con `corpus_t067` y de `backend/evaluation/cases.json` con `corpus/protocols.txt`, que tiene un solo fragmento de 155 palabras. Los fragmentos son los que guardó cada pedido. La misma corrida con la comprobación activa dio las mismas decisiones: 15 casos generan y C-06 se rechaza.

| Caso | Fragmentos | Términos del tema | Presentes | Cobertura | Frases del tema (presentes en negrita) | Decisión |
| --- | --- | --- | --- | --- | --- | --- |
| c01 | 1 | videollamadas, cortan, protocolo, confirma, entrega | 4 de 5 | 0,80 | **confirma la entrega** | Genera |
| c02 | 1 | tcp, udp | 2 de 2 | 1,00 | — | Genera |
| c03 | 1 | tcp, confirma, retransmite, segmentos, perdidos | 4 de 5 | 0,80 | tcp confirma, retransmite los segmentos, segmentos perdidos | Genera |
| c04 | 1 | empresa, protocolo, transporte, transmitir, vivo | 3 de 5 | 0,60 | **protocolo de transporte** | Genera |
| c05 | 1 | tcp, udp | 2 de 2 | 1,00 | — | Genera |
| c06 | 1 | protocolos, transporte, red | 2 de 3 | 0,67 | **protocolos de transporte** | Genera |
| c07 | 1 | protocolo, juego, linea, transferencia, archivos | 3 de 5 | 0,60 | transferencia de archivos | Genera |
| c08 | 1 | protocolo, garantiza, entrega, confiable, datos | 5 de 5 | 1,00 | protocolo garantiza, **entrega confiable**, **confiable de los datos** | Genera |
| c09 | 1 | dispositivo, decide, camino, paquete, destino | 5 de 5 | 1,00 | dispositivo decide, **decide el camino** | Genera |
| c10 | 1 | protocolo, ip, direccionamiento, enrutamiento | 4 de 4 | 1,00 | **protocolo ip** | Genera |
| C-01 | 8 | modelo, osi, capas | 3 de 3 | 1,00 | **modelo osi** | Genera |
| C-02 | 8 | udp | 1 de 1 | 1,00 | — | Genera (menos de 2 términos: no se comprueba) |
| C-03 | 8 | tcp, udp, capa, transporte | 4 de 4 | 1,00 | **capa de transporte** | Genera |
| C-04 | 8 | direccionamiento, ip, enrutamiento, red | 4 de 4 | 1,00 | **direccionamiento ip** | Genera |
| C-05 | 8 | wireshark, analisis, redes | 3 de 3 | 1,00 | análisis de redes | Genera |
| C-06 | 8 | tablas, llaves, primarias, modelo, relacional | 2 de 5 | 0,40 | llaves primarias, modelo relacional | Rechaza: «llaves primarias, modelo relacional» |

Los resultados medidos con Ragas se agregan en `tasks.md` después de la corrida real.

---

### QA-06 · Tiempos de respuesta y límite de Gemini

**Responsable:** Yan · **Tipo:** Backend · **Atributo:** Eficiencia de desempeño

**Enfoque:** Medir p95 del `POST` con 5 secuencias en paralelo. Configurar un tiempo límite de 60 s por llamada a Gemini para que ninguna quede colgada.

**Tiempo límite por llamada (parte A).** El timeout de httpx (`LLM_TIMEOUT_SECONDS`) se aplica a cada operación de red, no a la llamada completa. Un proveedor que envía la respuesta de a poco nunca lo dispara, y el adaptador de texto puede hacer una segunda llamada si el JSON no es válido.

- `LLM_CALL_DEADLINE_SECONDS` (`infrastructure/settings.py`): tiempo límite total de cada llamada a Gemini, de punta a punta. Por defecto es 60 y nunca pasa de 60; un valor mayor, vacío o inválido queda en 60.
- Se aplica al texto (todo `generate()`, con el reintento por JSON inválido y el reintento sin esquema dentro del mismo límite), a la imagen, a la voz y a cada lote de embeddings.
- La llamada corre en un hilo que lee la respuesta por partes (`infrastructure/llm/call_deadline.py`). Quien llama espera solo hasta el límite y sigue con el respaldo de siempre: el generador por reglas, la tarjeta de la imagen o la voz del navegador. El motivo público es genérico, como en `provider_errors.py`: «Gemini no respondió en 60 s», o «… en los embeddings». El hilo de fondo deja de leer en la siguiente parte que llega.
- `LLM_TIMEOUT_SECONDS` sigue siendo el timeout de cada operación, pero no puede pasar del límite de la llamada. **En Render, `LLM_TIMEOUT_SECONDS` debe ser 60 o menos**: un valor mayor se recorta a `LLM_CALL_DEADLINE_SECONDS`.
- Pruebas sin red, con un transporte falso que envía la respuesta de a poco (`tests/unit/test_llm_call_deadline.py`). Con un límite de 0,3 s, cada llamada termina antes de 0,55 s y el paso pasa al respaldo con el motivo. Se prueba lo mismo con la imagen, la voz y los embeddings.

**Medición (parte B).** `backend/scripts/measure_generation_load.py --teachers 5` prepara 5 cuentas separadas (el correo de `EVAL_EMAIL` con `.carga1` a `.carga5` antes de la @), cada una con su curso, su unidad y su material procesado. Después envía las 5 secuencias a la vez (un hilo por docente, con una barrera). Por cada `POST` registra el estado HTTP y el tiempo de respuesta en ms, y el resumen informa p50, p95 y máximo, además de las duraciones de punta a punta de siempre. El informe queda en `backend/evaluation/results/load-<proveedor>-<fecha>.json`. Sin `--teachers`, el script hace la medición de antes. La meta de QA-06 es p95 < 500 ms en el `POST`.

Cómo correrla en local con PostgreSQL (Docker), sin ninguna clave de API. Desde `backend/`:

```bash
# 1. Base de datos: PostgreSQL con pgvector en Docker y migraciones con dbmate
cp .env.example .env                      # deja LLM_API_KEY vacío
docker compose up -d --wait db
docker compose run --rm dbmate up

# 2. Backend con el generador por reglas (terminal 1)
export DATABASE_URL='postgres://platform5e:cambiar-en-local@localhost:5432/platform5e?sslmode=disable'
export LLM_PROVIDER=rules EMBEDDINGS_ENABLED=false MEDIA_GENERATION_ENABLED=false TOPIC_SEARCH_ENABLED=false
unset LLM_API_KEY
.venv/bin/python -m uvicorn platform5e.main:create_application --factory --app-dir src --host 127.0.0.1 --port 8000

# 3. Medición (terminal 2, también desde backend/)
export EVAL_EMAIL=carga.qa06@correo.pe EVAL_PASSWORD=clave-segura-9
.venv/bin/python scripts/measure_generation_load.py --api http://127.0.0.1:8000 --teachers 5

# 4. Al terminar
docker compose stop                       # o «docker compose down -v» para borrar los datos locales
```

`DATABASE_URL` usa los valores de `.env.example`; si cambiaste el usuario, la contraseña o `POSTGRES_PORT` en `.env`, usa los tuyos. El backend acepta la URL `postgres://` de dbmate y la convierte a psycopg.

---

### QA-07 · Búsqueda híbrida con pgvector

**Responsable:** Sergio · **Tipo:** Backend · **Atributo:** Adecuación funcional

**Enfoque:** Medir `context_recall` con pgvector usando la evaluación Ragas. Verificar que los fragmentos del documento distractor no aparecen en C-01 a C-05.

**Dependencia:** PR #40 de Yan (corpus de T067 y resultados de Ragas de T068).

---

### QA-08 · Límite de intentos de sesión y cabeceras de seguridad

**Responsable:** Sergio · **Tipo:** Backend · **Atributo:** Seguridad

**Enfoque:** Límite de 5 intentos por correo e IP en 15 min; el 6.º responde 429 con `Retry-After`. Sin revelar si el correo existe. Middleware para cabeceras `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` y `Referrer-Policy`. `pip-audit` sin vulnerabilidades altas.

---

### QA-09 · Accesibilidad con axe en Playwright

**Responsable:** Silvana · **Tipo:** Frontend · **Atributo:** Usabilidad

**Enfoque:** Integrar `@axe-core/playwright` en las pruebas e2e. Verificar 0 violaciones serias o críticas de WCAG 2.1 AA. Recorrido completo solo con teclado.

---

### QA-10 · Presupuesto del bundle y auditoría npm

**Responsable:** Silvana · **Tipo:** Frontend · **Atributo:** Eficiencia y seguridad

**Enfoque:** Carga diferida (`React.lazy` y `Suspense`). Presupuesto de JavaScript inicial < 200 kB comprimido. La CI falla si se pasa del presupuesto o si `npm audit` encuentra vulnerabilidades altas.

---

### QA-11 (opcional) · Verificación frase por frase de guiones de audio

**Responsable:** Juan · **Tipo:** Backend · **Atributo:** Adecuación funcional

**Enfoque:** En `resource_verification.py`, verificar cada frase del guion de `audio_detonante` y `podcast_resumen` contra los fragmentos citados. Subir `VERIFICATION_RULE_VERSION`. Los audios aprobados antes del cambio se reverifican al leerlos (verificación heredada). Solo se hace si las tareas 1 a 4 están integradas.

---

### QA-12 · Dominio propio con HTTPS

**Responsable:** Juan (backend), Yan (frontend) · **Tipo:** Infraestructura · **Atributo:** Portabilidad y seguridad

**Enfoque:** Registrar el dominio en Name.com (GitHub Student Developer Pack; alternativa: .TECH); en Render, dominio personalizado `api.<dominio>` con su CNAME; en Vercel, `<dominio>` y `www.<dominio>`; variables `CORS_ALLOWED_ORIGINS=https://<dominio>,https://www.<dominio>` y `LLM_TIMEOUT_SECONDS=60` en Render, `VITE_API_URL=https://api.<dominio>` en Vercel; actualizar `README` y guía de despliegue.

Comandos de verificación:
```bash
curl -I http://api.<dominio>/health      # 301 o 308 hacia https
curl -i https://api.<dominio>/health     # 200
grep -rn "vercel.app" .                  # sin resultados en ambos repositorios
```

**Criterio de aceptación:** Certificado válido en ambos; `GET https://api.<dominio>/health` responde 200; redirección permanente (301 o 308) de HTTP a HTTPS; 0 advertencias de contenido mixto en la consola; la dirección `.vercel.app` ya no aparece en los repositorios; `LLM_TIMEOUT_SECONDS=60` en Render.

---

### QA-13 · Limpieza de ramas y borrado automático

**Responsable:** Silvana · **Tipo:** Repositorio · **Atributo:** Mantenibilidad

**Enfoque:** Cerrar sin fusionar el PR #39 (backend); el PR #19 (frontend) queda cerrado, con sus cambios incorporados en `main` mediante el PR #20; borrar las ramas remotas ya integradas en `main`; activar «Automatically delete head branches» en Settings → General de ambos repositorios.

Comandos:
```bash
git fetch origin --prune
git branch -r --merged origin/main
git branch -r --no-merged origin/main
git push origin --delete <rama>
git fetch origin --prune
git branch -r
```

Evidencia: `docs/evidence/QA-13/` (rama `docs/qa-13-branch-cleanup`).

**Criterio de aceptación:** 0 ramas remotas ya integradas en `main`, sin contar `main` ni la referencia simbólica `origin/HEAD` (comprobado con `git branch -r --merged origin/main`); «Automatically delete head branches» activado en ambos repositorios; PR #39 del backend cerrado sin fusionar; PR #19 del frontend cerrado, con sus cambios incorporados en `main` mediante el PR #20.

---

### QA-14 · Lighthouse

**Responsable:** Silvana · **Tipo:** Frontend · **Atributo:** Usabilidad y eficiencia de desempeño (UAc-1-G, PTb-1-G)

**Enfoque:** `@lhci/cli` como dependencia de desarrollo; `lighthouserc.json` con `collect.startServerCommand: "npm run preview"` y las URL `http://localhost:4173/login` y `http://localhost:4173/registro`, 3 corridas, perfil de escritorio; aserciones `categories:performance` ≥ 0,90, `categories:accessibility` ≥ 0,95, `categories:best-practices` ≥ 0,90 y `categories:seo` ≥ 0,90 con nivel error; paso en `frontend-ci.yml` después de `npm run build`. En producción, Lighthouse de Chrome en `/login`, `/courses`, una unidad y `/downloads`, escritorio y móvil, antes y después de las correcciones.

Comandos:
```bash
npm run build
npx lhci autorun
```

**Criterio de aceptación:** Escritorio: Rendimiento ≥ 90, Accesibilidad ≥ 95, Buenas prácticas ≥ 90 y SEO ≥ 90. Móvil: Rendimiento ≥ 80. Se registran también LCP y TBT por pantalla (UAc-1-G = puntaje de accesibilidad; PTb-1-G = LCP medio).

---

### QA-15 · Inyección SQL

**Responsable:** Sergio · **Tipo:** Backend · **Atributo:** Seguridad (SCo-1-G, SIn-2-G)

**Enfoque:** `sqlmap` contra la pila local en las rutas de la tabla de `spec.md`, con token de un docente de prueba; Bandit y Semgrep en `backend-ci.yml` (fallan con hallazgos altos); pruebas e2e en `backend/tests/e2e/test_sql_injection.py`.

Comandos:
```bash
sqlmap -u "http://localhost:8000/api/v1/documents/search?query=redes&unitId=<id>" --headers="Authorization: Bearer <token>" --level=3 --risk=2 --batch --output-dir=docs/evidence/QA-15/sqlmap
sqlmap -r docs/evidence/QA-15/sessions-request.txt --level=3 --risk=2 --batch   # POST /api/v1/sessions con cuerpo JSON
bandit -r backend/src -ll
semgrep scan --config p/python backend/src
```

**Criterio de aceptación:** X = 1 − A/B = 1 (A = rutas con inyección confirmada por sqlmap, B = rutas probadas); 0 hallazgos altos de Bandit y Semgrep (los medios se informan); pruebas e2e con cargas de inyección en verde.

---

### QA-16 · Protección contra denegación de servicio

**Responsable:** Sergio · **Tipo:** Backend · **Atributo:** Fiabilidad (RAv-1-G, RFt-1-G)

**Enfoque:** Límite por IP con la misma idea de `LoginRateLimiter` y `TRUSTED_PROXIES` en las rutas costosas de `spec.md`, configurable por variables de entorno; middleware que rechaza con 413 si `Content-Length` supera 25 MB en `POST /api/v1/documents` y 1 MB en las rutas JSON, antes de leer el cuerpo; pruebas e2e del 429 y del 413; OpenAPI regenerado; ráfaga con el locustfile de QA-17.

Comandos:
```bash
pytest tests/e2e -k "rate_limit or payload_size"
locust -f backend/performance/locust/locustfile.py --host http://localhost:8000 --headless -u 200 -r 50 -t 2m --html docs/evidence/QA-16/burst.html
```

**Criterio de aceptación:** 429 con `Retry-After` en ráfagas (límite configurable por variable de entorno); 413 cuando `Content-Length` supera 25 MB en la subida de archivos y 1 MB en las rutas JSON; pruebas e2e del 429 y del 413 en verde; durante una ráfaga de 200 usuarios por 2 minutos con el locustfile de QA-17, disponibilidad X = A/B = 1 (A = respuestas 200 de `/health`, B = consultas a `/health`) y el proceso no se reinicia.

---

### QA-17 · Concurrencia y capacidad con Locust

**Responsable:** Yan · **Tipo:** Backend · **Atributo:** Eficiencia de desempeño (PTb-1-G, PTb-5-G, PCa-2-G)

**Enfoque:** Cada usuario virtual crea su cuenta, inicia sesión, lista cursos, busca evidencia, crea pedidos y consulta su estado (máximo 2 activos por docente; el 429 de negocio se cuenta aparte); escalones de 10, 25, 50 y 100 usuarios, 3 minutos cada uno; `docker stats --no-stream` cada 30 s.

Comando (por escalón):
```bash
locust -f backend/performance/locust/locustfile.py --host http://localhost:8000 --headless -u <usuarios> -r 5 -t 3m --html docs/evidence/QA-17/<usuarios>u.html --csv docs/evidence/QA-17/<usuarios>u
```

**Criterio de aceptación:** Por escalón (3 minutos cada uno): p50, p95, peticiones por segundo y % de errores. Capacidad (PCa-2-G) = mayor número de usuarios con p95 < 1 s y errores < 1 %.

---

### QA-18 · Punto de quiebre con JMeter

**Responsable:** Juan · **Tipo:** Backend · **Atributo:** Eficiencia de desempeño y fiabilidad (PCa-1-G, RRe-1-G)

**Enfoque:** Escalones de 50, 100, 200, 400 y 800 hilos, 2 minutos cada uno con rampa de 30 s; mezcla 40 % `/health`, 30 % cursos, 20 % búsqueda, 10 % creación de pedidos con consulta de su estado; parada automática cuando un escalón tiene errores > 5 % o más del 5 % de muestras sobre 5 s (p95 > 5 s); medición de recuperación de `/health`; corrida 1 sin QA-16 y corrida 2 con QA-16.

Comandos (desde backend/):
```powershell
.\.venv\Scripts\python.exe performance\jmeter\prepare_users.py --users 800 --workers 16
& "$env:USERPROFILE\tools\apache-jmeter-5.6.3\bin\jmeter.bat" -n -t performance\jmeter\stress.jmx -Jhost=localhost -Jport=8000 -l performance\jmeter\results\run1.jtl -e -o performance\jmeter\results\run1-report
```

**Criterio de aceptación:** Punto de quiebre = primer escalón con errores (5xx, tiempos agotados o conexiones rechazadas) > 5 % o p95 > 5 s. PCa-1-G = peticiones por segundo del último escalón que cumple. RRe-1-G = segundos desde el fin de la carga hasta que `/health` responde 200 en menos de 1 s (meta: menos de 10 s). Dos corridas: antes y después de QA-16. Los 429 `TOO_MANY_ACTIVE_REQUESTS` son respuesta de negocio esperada y se cuentan aparte.

---

### QA-19 · Informe final con ISO/IEC 25023

**Responsable:** Juan · **Tipo:** Documentación · **Atributo:** Calidad consolidada

**Enfoque:** Tabla consolidada QA-01 a QA-19 en `report.md` y tabla de medidas ISO/IEC 25023 (tarea, característica, medida, fórmula, valor medido, meta, ¿cumple?, evidencia), solo con valores de `docs/evidence/` o de los PR integrados.

**Criterio de aceptación:** QA-01 a QA-19 en la tabla consolidada; solo valores presentes en `docs/evidence/` o en los PR integrados; lo no medido queda como «pendiente» con su motivo.

## Dependencias entre tareas

```mermaid
flowchart LR
    QA01["QA-01 Spec"]
    QA02["QA-02 /health/dependencies"]
    QA03["QA-03 Moodle XML"]
    QA04["QA-04 Informe QA-01 a QA-11"]
    QA05["QA-05 C-06 Ragas"]
    QA06["QA-06 Tiempos"]
    QA07["QA-07 pgvector"]
    QA08["QA-08 Seguridad"]
    QA09["QA-09 Accesibilidad"]
    QA10["QA-10 Bundle"]
    QA11["QA-11 Audio"]
    QA12["QA-12 Dominio propio"]
    QA13["QA-13 Limpieza de ramas"]
    QA14["QA-14 Lighthouse"]
    QA15["QA-15 Inyección SQL"]
    QA16["QA-16 Límite por IP y 413"]
    QA17["QA-17 Carga Locust"]
    QA18["QA-18 Estrés JMeter"]
    QA19["QA-19 Informe final"]
    PR40["PR #40 Yan"]

    QA01 --> QA02
    QA01 --> QA03
    QA01 --> QA05
    QA01 --> QA06
    PR40 --> QA07
    QA01 --> QA08
    QA01 --> QA09
    QA01 --> QA10
    QA01 --> QA11
    QA01 --> QA12
    QA01 --> QA13
    QA12 --> QA14
    QA01 --> QA15
    QA17 -. "locustfile" .-> QA16
    QA01 --> QA17
    QA01 --> QA18
    QA16 -. "comparación" .-> QA18
    QA02 --> QA04
    QA03 --> QA04
    QA05 --> QA04
    QA06 --> QA04
    QA07 --> QA04
    QA08 --> QA04
    QA09 --> QA04
    QA10 --> QA04
    QA11 --> QA04
    QA04 --> QA19
    QA12 --> QA19
    QA13 --> QA19
    QA14 --> QA19
    QA15 --> QA19
    QA16 --> QA19
    QA17 --> QA19
    QA18 --> QA19
```

- **QA-01** es el punto de partida: define los escenarios y las tareas.
- **QA-02** la validan Yan y Sergio (comportamiento con dependencia caída).
- **QA-04** va después de QA-02 a QA-11 y es la base de QA-19.
- **QA-07** depende del PR #40 de Yan (corpus de T067 y resultados de Ragas de T068).
- **QA-11** es opcional y solo se hace si las tareas 1 a 4 están integradas.
- **QA-14** en producción depende de **QA-12** (dominio propio con HTTPS).
- **QA-16** usa el locustfile de **QA-17** para disparar ráfagas de prueba.
- **QA-18** se mide antes y después de aplicar el límite de tasa de **QA-16** para comparar el comportamiento en saturación.
- **QA-19** depende de que todas las anteriores tengan su PR integrado en `main`.
- Las demás tareas son independientes entre sí y pueden realizarse en paralelo.
