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

## Dependencias entre tareas

```mermaid
flowchart LR
    QA01["QA-01 Spec"]
    QA02["QA-02 /health/dependencies"]
    QA03["QA-03 Moodle XML"]
    QA04["QA-04 Informe final"]
    QA05["QA-05 C-06 Ragas"]
    QA06["QA-06 Tiempos"]
    QA07["QA-07 pgvector"]
    QA08["QA-08 Seguridad"]
    QA09["QA-09 Accesibilidad"]
    QA10["QA-10 Bundle"]
    QA11["QA-11 Audio"]
    PR40["PR #40 Yan"]

    QA01 --> QA02
    QA01 --> QA03
    QA01 --> QA05
    QA01 --> QA06
    PR40 --> QA07
    QA01 --> QA08
    QA01 --> QA09
    QA01 --> QA10
    QA02 --> QA04
    QA03 --> QA04
    QA05 --> QA04
    QA06 --> QA04
    QA07 --> QA04
    QA08 --> QA04
    QA09 --> QA04
    QA10 --> QA04
    QA11 --> QA04
```

- **QA-01** es el punto de partida: define los escenarios y las tareas.
- **QA-02** la validan Yan y Sergio (comportamiento con dependencia caída).
- **QA-07** depende del PR #40 de Yan (corpus de T067 y resultados de Ragas de T068).
- **QA-04** va al final, después de todos los PR del equipo.
- **QA-11** es opcional y solo se hace si las tareas 1 a 4 están integradas.
- Las demás tareas son independientes entre sí y pueden hacerse en paralelo.
