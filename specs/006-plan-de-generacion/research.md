# Research del plan de generación (GEN-P1 a GEN-P3)

[Ficha](spec.md) · [Plan](plan.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/generation-plans.openapi.yaml) · [Validación](quickstart.md) · [Tareas](tasks.md)

Decisiones tomadas a partir de la reunión del 21/11/2026 y del código actual de GEN-01 ([002](../002-generacion-multiple/research.md)).

## R1. El plan como recurso propio, creado de forma síncrona

**Decisión.** El plan es un recurso REST propio, `generation-plans`, separado del pedido de generación:

- `POST /api/v1/generation-plans` crea un plan en borrador, con `Idempotency-Key`.
  - **Entradas:** unidad, indicaciones (el tema), audiencia, competencia, resultado de aprendizaje, modalidad, y tipos con cantidad opcional.
  - **Pasos:** recupera la evidencia, pide a Material los referentes (MAT-P2), pide a Cursos el contexto de sesión (CUR-P3), arma el plan y lo valida.
- `GET /api/v1/generation-plans/{planId}` y `GET /api/v1/generation-plans?unitId=…` lo recuperan. La lista sirve para volver al último plan después de recargar (PLAN-C14).
- `PUT /api/v1/generation-plans/{planId}` guarda la edición del docente con `expectedVersion`.
- `POST /api/v1/generation-plans/{planId}/approve` lo aprueba con `expectedVersion`.
- `POST /api/v1/generation-requests` recibe `planId` y `planVersion` ([R2](#r2-el-plan-es-obligatorio-compatibilidad-del-pedido-sin-plan)).

**Creación síncrona.** Crear un plan es una sola llamada al modelo, no una secuencia de pasos:

- **Duración acotada.** El adaptador de Gemini ya tiene un límite total de 60 s por llamada, de punta a punta, con el reintento por JSON inválido incluido (QA-06, `infrastructure/llm/call_deadline.py`). Si vence, el plan se arma con reglas en menos de 1 s, así que `POST` responde en 60 s más la recuperación como máximo, y casi siempre mucho antes.
- **El docente espera de todos modos.** No puede seguir sin ver el plan, porque lo revisa antes de generar. Un pedido en segundo plano solo agregaría consultas de estado a la interfaz.
- **No hace falta la maquinaria de pedidos.** La cola, el latido, el barrido de interrumpidos y el cupo de activos (002, R3 y R4) protegen ejecuciones de minutos con varios pasos; para una llamada acotada son innecesarios.
- **Reintentos sin duplicar.** Con `Idempotency-Key`, un reintento tras perder la conexión devuelve el mismo plan (misma regla de `payload_hash` que 002 R2).

**Alternativas descartadas.**
- **Creación asíncrona** (`202` y consultas de estado): duplica la maquinaria de 002 para una sola llamada. Se reconsidera solo si la medición de [quickstart](quickstart.md#v9--tiempos) da un p95 de creación con Gemini mayor que 30 s.
- **El plan como paso del pedido de generación:** obligaría a pausar el pedido a la espera de la aprobación del docente, y un pedido no se puede editar.
- **Plan solo en el frontend:** no habría plan para el generador por reglas, para la regeneración ni para medir P4.

## R2. El plan es obligatorio: compatibilidad del pedido sin plan

**Decisión.** El profesor pide planificar siempre. Desde esta entrega, todo pedido de generación tiene un plan:

- **Con plan.** El cuerpo de `POST /api/v1/generation-requests` es `{planId, planVersion}`. El plan debe estar aprobado, en esa versión, y no estar usado. El modo sale del plan: `individual` si tiene un ítem con un tipo y cantidad 1, y `sequence` en los demás casos. Al aceptar el pedido, el plan pasa a `used`.
- **Sin plan (transición).** El cuerpo anterior, el de 002, sigue aceptándose mientras el frontend de GEN-P3 no esté integrado. El servidor crea un plan implícito con las mismas entradas: lo arma, lo valida y lo aprueba sin intervención, con `origin: implicit`, y genera desde él. Así se cumple «siempre hay plan», y P4 mide también los pedidos antiguos y los scripts de evaluación.
- **Fin de la transición.** Con `GENERATION_REQUIRE_PLAN=true` (por defecto `false` hasta integrar GEN-P3, y después `true`), el cuerpo sin plan responde `422 PLAN_REQUIRED`. `collect_samples.py` y `measure_generation_load.py` pasan a crear el plan antes de generar.
- **Regeneración desde Revisión (002, GEN-C7).** No crea un plan nuevo y no escribe el plan: lee el ítem del recurso (`params.planId` y `params.planItemPosition`) y el resumen de los demás recursos del plan. Como no cambia `status`, `version` ni `usedByRequestId`, un plan `used` no responde `409 PLAN_ALREADY_USED`. Si los fragmentos del ítem ya no existen, aplica la misma regla de [evidencia vigente](#evidencia-vigente-por-qué-rechazar-y-no-volver-a-buscar). Un recurso anterior a esta entrega, sin plan, se regenera como hoy.
- **Interpretación de pedidos (HU-038).** El borrador del chat llena el formulario, y el formulario crea el plan en lugar del pedido.

**Alternativas descartadas.**
- **Exigir el plan desde el primer día:** rompería el frontend actual y los scripts de evaluación antes de que exista GEN-P3.
- **Dejar el camino sin plan para siempre:** contradice el pedido del profesor, y la duplicación de esos pedidos no mejoraría.

## R3. El contrato JSON del plan

**Decisión.** El contrato completo está en [data-model](data-model.md#generationplan) y en el [OpenAPI](contracts/generation-plans.openapi.yaml). Los puntos que conviene justificar:

- **El plan congela su evidencia** (`evidence.fragments`, con id, documento, ubicación y texto). Los `fragmentIds` de los ítems solo pueden ser de esa evidencia. La generación usa esa misma evidencia, no una búsqueda nueva, así que lo que el docente aprobó es lo que se cita. La recuperación se hace una sola vez, al crear el plan, igual que hoy se hace una vez por pedido (002, GEN-R2).
- **`covers`: los conceptos que el ítem desarrolla.** Son frases cortas del docente o del planificador, por ejemplo «control de flujo en TCP». Se comparan normalizadas: minúsculas, sin tildes, sin espacios repetidos y sin palabras vacías, como en `domain/generation/topic_coverage.py`. Ningún concepto normalizado puede estar en dos ítems.
- **`doesNotCover` lo calcula el servidor** como la unión de los `covers` de los demás ítems, en orden. El docente no lo edita: al cambiar los conceptos de un ítem, los demás se actualizan solos, y no puede quedar una contradicción. El modelo no lo devuelve.
- **`quantity` por ítem**, de 1 a 5, como hoy. Un ítem con cantidad N reparte sus `covers` entre sus N recursos, en bloques consecutivos y en orden; por eso necesita al menos N conceptos. Si el docente deja la cantidad vacía (`null`), la elige el planificador según los conceptos disponibles, con las reglas de [R4](#r4-planificación-con-reglas-y-con-gemini).
- **Por qué 5 como máximo.**
  - Es el mismo límite por tipo de GEN-01 (`MAX_QUANTITY_PER_TYPE`), así que el plan no abre un caso nuevo para la generación.
  - Cada recurso se redacta por separado desde su bloque de conceptos (GEN-P2): el tiempo y el costo crecen con la cantidad, y 8 tipos × 5 ya son 40 recursos en un pedido.
  - Cada recurso necesita conceptos propios. Con 3 a 12 fragmentos de evidencia, más de 5 recursos del mismo tipo terminarían repitiendo conceptos, que es lo que el plan quiere evitar.
- **`stage` sale del catálogo y es de solo lectura.** El orden de los ítems sigue el de las etapas y, dentro de cada etapa, el de `position`.
- **`version`** sube en cada `PUT`. `approve` y el pedido de generación la exigen (concurrencia optimista, como `expectedVersion` en Revisión).
- **`validation`** se calcula en cada escritura: `{valid, problems[]}`. El borrador se guarda aunque sea inválido, para no perder la edición, pero no se puede aprobar.
- **`referents` y `sessionContext`** pueden estar vacíos. Se guardan tal como llegaron al crear el plan, para que el plan sea reproducible.

**Alternativa descartada.** Que el modelo devuelva `doesNotCover`: podría contradecir los `covers` de otros ítems y habría que validarlo igual. Calcularlo es más simple y siempre es correcto.

### Evidencia vigente: por qué rechazar y no volver a buscar

Entre la aprobación y la generación, el docente puede borrar un documento o volver a procesarlo; al procesar de nuevo, los fragmentos reciben ids nuevos. Por eso `POST /generation-requests` comprueba que cada `fragmentId` del plan siga existiendo en la unidad del docente (`EvidenceProviderPort.existing_fragment_ids`, nuevo en MAT-01) y, si falta alguno, responde `409 PLAN_EVIDENCE_STALE` con los documentos afectados; el docente crea un plan nuevo. Se rechaza en lugar de volver a buscar en silencio por tres motivos:

- **El plan aprobado es la evidencia.** Una búsqueda nueva traería otros fragmentos: los `covers` y `fragmentIds` que el docente aprobó dejarían de corresponder a lo que se cita, y se perdería «lo que aprobaste es lo que se cita».
- **Borrar puede ser deliberado.** El docente pudo quitar un documento por su licencia o su permiso de uso; generar con una copia congelada de ese texto lo citaría igual.
- **Rehacer el plan es barato.** Es síncrono y tarda segundos con reglas o hasta 60 s con IA ([R1](#r1-el-plan-como-recurso-propio-creado-de-forma-síncrona)), y el docente ve qué cambió.

## R4. Planificación con reglas y con Gemini

**Con reglas (`LLM_PROVIDER=rules`, o como respaldo).** El resultado es determinista: las mismas entradas y la misma evidencia dan el mismo plan.

1. **Conceptos candidatos.** Primero las frases y los términos del tema que aparecen en la evidencia (`topic_phrases` y `topic_terms` de QA-05), después los términos clave de la evidencia (`extract_key_terms` de `domain/materials/text_analysis.py`). Cada grupo se ordena por el primer fragmento donde aparece cada concepto (el orden de relevancia de la búsqueda); en el mismo fragmento, las frases antes que las palabras sueltas, y en empate, por orden alfabético. Una palabra suelta que ya está dentro de un concepto elegido («modelo» en «modelo OSI») no se agrega.
2. **Ítems.** Uno por tipo pedido, ordenados por etapa; los tipos con cantidad N reciben N bloques de conceptos.
   - **Cantidad vacía (`null`).** Con C conceptos candidatos y T tipos pedidos, la cantidad es `min(3, max(1, C // (2 × T)))`: un recurso por cada dos conceptos que le tocarían al tipo, al menos 1.
   - **Por qué hasta 3 y no hasta 5.** El tope automático es más bajo que el máximo que puede pedir el docente (5): si el docente no lo pidió, el planificador no multiplica los recursos, y cada bloque conserva por lo menos dos conceptos. Para tener 4 o 5, el docente escribe la cantidad.
   - Las cantidades elegidas pasan por el mismo ajuste del paso 3 si los conceptos no alcanzan.
3. **Reparto.** Los conceptos se reparten por turnos (round robin) entre los bloques, en el orden de los ítems. Cada bloque recibe al menos un concepto. Si hay menos conceptos que bloques, se baja la cantidad del último ítem que la tenga mayor que 1. Si aun así no alcanzan, se informa como problema de validación, sin inventar conceptos.
4. **Fragmentos.** Los de cada ítem son los fragmentos donde aparece alguno de sus conceptos, en el orden de la evidencia. Un ítem sin fragmentos queda inválido («sin evidencia»).
5. **Propósito.** Una plantilla por tipo con la descripción del catálogo y los primeros conceptos, por ejemplo: «Explicación citada: desarrolla «control de flujo», «retransmisión»».

**Con Gemini.** Una sola llamada:

- **Entrada:** el catálogo de los tipos pedidos (nombre, etapa y descripción), la evidencia con etiquetas F1…Fn, los referentes, el contexto de sesión y las entradas del docente.
- **Cantidad.** Para un tipo con cantidad pedida, el prompt dice «cantidad N» y el servidor conserva N aunque el modelo devuelva otra. Para un tipo con cantidad vacía, dice «cantidad de 1 a 5, según los conceptos», con la regla de que cada ítem tenga al menos tantos conceptos como su cantidad. La cantidad que devuelve el modelo se acota de 1 a 5; si el plan resultante no tiene conceptos suficientes (`NOT_ENOUGH_CONCEPTS`), cuenta como inválido y va al respaldo por reglas.
- **Esquema de respuesta propio**, como el de la actividad kinestésica en T073: `items` obligatorio, con `minItems` 1 y `maxItems` igual a la cantidad de tipos pedidos (como máximo 8, el límite de GEN-01); cada ítem exige `resourceType`, `quantity`, `purpose`, `covers` (con `minItems` 1) y `fragmentos` (con `minItems` 1).
- **Dos límites de ítems, a propósito.** Al crear el plan, la IA arma un ítem por tipo pedido, así que su esquema tiene como máximo 8 ítems. Un plan editado con `PUT` acepta hasta 40 ítems (`UpdateGenerationPlan.items` del contrato, `maxItems` 40): el docente puede partir un tipo en varios ítems con conceptos distintos (8 tipos × 5 de cantidad = 40). Los dos límites son intencionales: el primero limita lo que la IA propone, y el segundo, lo que el docente puede editar.
- **Después de la respuesta:** las etiquetas se traducen a ids, se descartan los tipos no pedidos, se calcula `doesNotCover` y se valida.
- **Respaldo:** si la llamada vence a los 60 s, si la respuesta no es JSON válido, o si el plan resultante no es válido, se arma con reglas y `generator.fallbackReason` guarda el motivo público genérico de `provider_errors.py`.

Un plan de la IA con conceptos repetidos entre ítems no se corrige a mano: cuenta como inválido y va al respaldo por reglas, igual que los recursos sin la estructura del tipo (T073).

**Alternativa descartada.** Una llamada por ítem: multiplica las llamadas y no evita la repetición, porque cada llamada no ve los conceptos de las demás.

## R5. Generación desde el plan (GEN-P2)

**Decisión.** El pedido ejecuta un paso por ítem, como hoy un paso por tipo, con la evidencia del plan. Cada recurso del ítem se redacta por separado:

- **Lo que recibe el prompt de cada recurso:**
  - su bloque de conceptos (`covers` del bloque), que debe desarrollar completo;
  - el propósito del ítem;
  - los conceptos de los demás ítems (`doesNotCover`), que no debe desarrollar: puede nombrarlos, pero no explicarlos (en los recursos de un solo párrafo, no debe nombrarlos; ver la comprobación de cobertura);
  - el resumen de lo ya cubierto: por cada recurso entregado antes en el pedido, su título, sus conceptos y un resumen de hasta 300 caracteres (`secuenciaPrevia`, como hoy);
  - la evidencia, con los fragmentos del ítem primero.
- **Sin acortar.** Se mantienen las reglas de formato y extensión de cada tipo; se quita la instrucción «si los fragmentos no alcanzan, devuelve menos recursos» para los ítems del plan, porque el plan ya decidió cuántos.
- **Comprobación de cobertura**, léxica y sin IA, con la normalización de QA-05:
  - el recurso debe mencionar al menos uno de sus conceptos;
  - no debe desarrollar un concepto ajeno: un concepto ajeno que aparece en más de un párrafo cuenta como desarrollado.
  - **Recursos de un solo párrafo** (`pregunta_detonante`, `item_opcion_multiple`, `audio_detonante` y los demás tipos cortos, también los tipos nuevos de CUR-P2 cuyo contenido salga en un párrafo): la regla anterior nunca se cumple, porque no hay un segundo párrafo. Para ellos rige una regla más estricta: un concepto ajeno que aparece como término completo (todas sus palabras seguidas, con la normalización de QA-05) en el enunciado, la situación, la pregunta o una opción cuenta como desarrollado. La retroalimentación de las opciones no se cuenta. Su prompt dice que no nombre los conceptos ajenos, en vez de «puede nombrarlos». La regla se decide por el contenido entregado (sin línea en blanco que separe párrafos), no por una lista fija de tipos.
  - **Falsos rechazos.** Las pruebas de T013 con el corpus de T067 deciden si la regla estricta rechaza recursos correctos. Si rechaza más del 5 % de los recursos cortos marcados como correctos, se afloja (por ejemplo, contar solo el enunciado y no las opciones) y el cambio se registra aquí.
  - Si falla, se pide de nuevo una vez con la indicación del problema. Si sigue fallando, se rechaza con `kind: plan` (nuevo tipo de rechazo en el contrato) y su motivo, y el respaldo por reglas lo intenta como hoy.
- **Verificación de anclaje (HU-016, HU-049, REV-01):** sin cambios. Cada recurso se verifica contra la evidencia del plan.
- **Control de repetición:** el filtro léxico actual (`SIMILARITY_THRESHOLD` = 0,6 en `domain/generation/sequence.py`) se mantiene como red de seguridad. Con el plan, su reintento agrega los conceptos que el recurso no debe repetir.
- **Generador por reglas:** redacta cada recurso con las oraciones de los fragmentos que contienen sus conceptos, así respeta el plan sin IA.

**Alternativas descartadas.**
- **Redactar todos los recursos en una sola llamada:** es justo lo que hoy produce repetición y recursos más cortos.
- **Quitar el filtro de repetición:** el plan reduce la repetición, pero no la impide si el modelo no obedece.

## R6. Catálogo configurable (CUR-P2)

**Decisión.** El catálogo pasa a Cursos (CUR-P2), con 10 a 15 tipos por etapa, selección múltiple y cantidad opcional. Generación lo lee por un puerto nuevo, `ResourceCatalogPort`; hasta que exista, el adaptador lee el catálogo actual (`domain/generation/resource_catalog.py`).

**Qué debe tener cada entrada para que Generación pueda redactarla:**

| Campo | Para qué |
| --- | --- |
| `id` | Identificador estable (snake_case), el valor de `resourceType`. |
| `name`, `singular`, `plural` | Lo que ve el docente y lo que usa el prompt. |
| `stage` | La etapa (`engage` … `evaluate`). |
| `format` | `text`, `visual`, `image`, `audio` o `interactive`. Un tipo nuevo de CUR-P2 solo puede ser `text` mientras no tenga redactor propio. |
| `description` | Una o dos oraciones de qué es el recurso y cómo lo usa el estudiante. Es la instrucción del prompt genérico. |
| `structure` | `none` para los tipos nuevos; los tipos actuales conservan la suya (pasos, pares, afirmaciones…). |
| `lengthHint` | Opcional. Extensión esperada del recurso en palabras, `{minWords, maxWords}` ([reglas](#extensión-lengthhint)). |
| `modalities` | Las modalidades que lo incluyen (HU-024). |
| `hasOptions` | Solo `item_opcion_multiple`. |
| `active` | Si se ofrece en el formulario. |

**Lo que entrega Cursos (CUR-P2) por cada tipo nuevo**, además de `id`, `name`, `singular` y `plural`:

| Campo | Valor |
| --- | --- |
| `stage` | Una de las cinco etapas. |
| `description` | Qué es el recurso y cómo lo usa el estudiante, en una o dos oraciones. |
| `lengthHint` | Opcional: `{minWords, maxWords}`. |
| `modalities` | Las modalidades que lo incluyen. |
| `format` | `text`. |
| `structure` | `none`. |
| `active` | `true` para ofrecerlo en el formulario. |

<a id="extensión-lengthhint"></a>**Extensión (`lengthHint`).**
- **Forma.** Un objeto opcional `{minWords, maxWords}`, con enteros: `minWords` ≥ 20, `maxWords` ≤ 600 y `minWords` ≤ `maxWords`. Cursos valida estas reglas al guardar la entrada; si Generación recibe una entrada que no las cumple, la trata como si no tuviera `lengthHint`.
- **Uso.** Es una guía para la redacción: el prompt pide «entre X y Y palabras». Nunca es una regla de rechazo: un recurso más corto o más largo no se rechaza ni se regenera por su extensión.
- **Sin `lengthHint`.** Vale la extensión por defecto del prompt genérico, la misma de `explicacion`: de 3 a 5 párrafos, sin un rango de palabras.

**Tipos nuevos de texto.**
- Se redactan con un prompt genérico: la `description` de la entrada, el ítem del plan, y el contenido con citas como en `explicacion`.
- Se verifican como `explicacion`: las citas (HU-016) y los párrafos (HU-049).
- El generador por reglas tiene un redactor genérico, de párrafos citados con las oraciones de los conceptos del ítem.
- Revisión y la exportación los tratan como texto. Su etiqueta sale del catálogo, sin caer en «Pregunta de opción múltiple», como pide T059.

**Alternativa descartada.** Escribir un redactor por cada tipo nuevo: no escala a 50 a 75 tipos, y los tipos de texto solo cambian la intención.

## R7. Medición de la duplicación (P4)

**Métrica.** Para cada generación, la similitud coseno de los embeddings de cada par de recursos (título y contenido), con el indicador de REV-P3:

- **Tasa de duplicación** = pares con similitud ≥ τ ÷ total de pares de la generación. τ lo fija REV-P3; mientras tanto, 0,85.
- **Similitud máxima media** = promedio, sobre los recursos, de su similitud más alta con otro recurso de la misma generación. Es la métrica secundaria.

**Procedimiento.**
- **Corpus:** `corpus_t067` (unidad de redes de C-01 a C-05).
- **Pedido:** una secuencia de 8 tipos de texto × 2 recursos, la misma de `measure_generation_load.py`. Se repite 3 veces con cada generador (reglas y Gemini).
- **Línea base:** sin plan, con el código de `main` antes de GEN-P1.
- **Con plan:** aprobado sin cambios.

Se registran en `docs/evidence/GEN-P4/` la tasa, la similitud máxima media, los recursos entregados por pedido y la `faithfulness` media (con `run_ragas.py`).

**Meta.**
- La tasa de duplicación con plan baja al menos un 50 % frente a la línea base y queda en 5 % o menos.
- Los recursos entregados no bajan.
- La `faithfulness` media sigue en 0,90 o más.

Mientras REV-P3 no esté, la medición provisional usa la similitud léxica de `most_similar` (`domain/generation/sequence.py`), registrada como tal.

## R8. La interfaz no menciona la metodología 5E

**Decisión.**
- **Interfaz:** ningún texto del frontend ni mensaje de la API que vea el docente dice «5E», «modelo 5E» ni «metodología 5E». Los nombres de las etapas se muestran (Enganchar, Explorar, Explicar, Elaborar, Evaluar).
- **Prompts:** ya piden no mencionar el modelo ni la etapa en los recursos; la regla se mantiene para los propósitos del plan.
- **Pruebas:** una prueba del frontend recorre los textos de la pantalla de Generación y falla si aparece «5E». Una prueba del backend revisa los mensajes de error de los planes y los motivos de rechazo.
- **Alcance:** los nombres internos, como `PHASES_5E` o los comentarios, no se ven y no cambian.

## R9. Contexto de sesión (CUR-P3)

**Decisión.** Cursos guarda la tipología (los tipos de recurso) usada en cada sesión del curso. Generación usa dos operaciones del puerto `SessionTypologyPort`:

- `previous_typologies(teacher_id, unit_id, limit=3)`: devuelve las últimas 3 tipologías del mismo curso de la unidad (de cualquiera de sus unidades), de la más reciente a la más antigua. Cada una trae `sessionLabel`, `usedAt` y `resourceTypes`.
- `record_typology(teacher_id, unit_id, plan_id, resource_types, used_at)`: se llama cuando el plan pasa a `used`.

**Qué es una sesión.** Se cuenta una sesión cada vez que un plan pasa a `used`, es decir, cuando inicia un pedido de generación. Un plan en borrador o aprobado que no se usa no cuenta. `usedAt` es el instante en que el plan pasó a `used`, y `resourceTypes` son los tipos de sus ítems.

**Uso en el plan.**
- **Aviso.** Si los tipos pedidos son los mismos que los de la sesión más reciente del curso (la primera de `previousTypologies`), sin importar el orden ni las cantidades, el plan trae `warnings: ["SAME_TYPOLOGY_AS_LAST_SESSION"]` y la interfaz sugiere variar.
- **Variación.** Con Gemini, las tipologías anteriores van al prompt para variar los propósitos y los enfoques. El planificador no cambia los tipos que eligió el docente.

**Acordado con CUR-P3 (Silvana).** La sesión es cada plan usado, como se describe arriba. Una fecha de clase o una unidad como sesión quedan descartadas: Generación no conoce el calendario del curso, y una unidad puede tener varias clases.

## R10. Referentes (MAT-P2)

**Decisión.** Material entrega `referents_for(teacher_id, unit_id, topic)` → `[{name, description, fragmentIds}]`. Son los autores principales del tema, detectados en el material de la unidad, con los fragmentos donde aparecen.

**Regla al crear el plan.** Los `fragmentIds` de cada referente son un subconjunto de `evidence.fragments` del plan:
- el servidor descarta los ids que no están en la evidencia congelada (Material puede devolver fragmentos que la búsqueda del plan no trajo);
- un referente que se queda sin ids se conserva con `fragmentIds: []`: se muestra, pero no se cita;
- no es un problema de validación: el plan no informa nada ni queda inválido por esto, y la regla se aplica antes de guardar, aunque los referentes lleguen del adaptador de MAT-P2 o de un doble.

Como el `PUT` no edita los referentes, la regla solo hace falta al crear el plan.

**Uso en el plan.**
- El plan los guarda en `referents`, ya filtrados.
- La IA los recibe como contexto para nombrarlos en los propósitos cuando corresponda.
- La interfaz los muestra.

**Lo que no cambia.** La búsqueda no cambia hasta que el profesor responda P8 ([spec](spec.md#preguntas-abiertas-para-el-profesor)). Un referente sin fragmentos de la evidencia del plan (`fragmentIds: []`) se muestra, pero no se cita.
