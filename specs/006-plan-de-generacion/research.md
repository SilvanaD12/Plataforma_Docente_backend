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
- **Fin de la transición (T021, hecho).** `GENERATION_REQUIRE_PLAN=true` por defecto desde que el frontend de GEN-P3 está integrado: el cuerpo sin plan responde `422 PLAN_REQUIRED`. `collect_samples.py`, `measure_generation_load.py` y el locustfile de QA-17 crean y aprueban el plan antes de generar. `false` queda para las pruebas del cuerpo anterior y las mediciones que lo usan a propósito (la línea base de P4 y el JMeter de QA-18). `GENERATION_IMPLICIT_PLAN` sigue siendo solo de medición.
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

1. **Conceptos candidatos.** Primero las frases y los términos del tema que aparecen en la evidencia (`topic_phrases` y `topic_terms` de QA-05), después los términos clave de la evidencia (`extract_key_terms` de `domain/materials/text_analysis.py`). Cada grupo se ordena por el primer fragmento donde aparece cada concepto (el orden de relevancia de la búsqueda); en el mismo fragmento, las frases antes que las palabras sueltas, y en empate, por orden alfabético. Una palabra suelta que ya está dentro de un concepto elegido («modelo» en «modelo OSI») no se agrega. **Corrección tras P4:** solo entran frases nominales cortas (2 a 4 palabras útiles del material) y siglas que aparecen al menos dos veces («UDP», «TCP»); las palabras sueltas comunes («decide», «camino», «conexión») ya no son conceptos.
   **Anclaje al resultado (T029, spec 002 R14).** Si el docente eligió un resultado de aprendizaje, el primer grupo son las frases y siglas del resultado que aparecen en la evidencia (`concept_phrases`, sin el verbo del resultado: «Reconoce las capas del modelo OSI» da «modelo OSI» y «capas del modelo»). Después vienen las del tema y los demás grupos. El prompt del plan con Gemini agrega una línea con el resultado elegido; el esquema no cambia.
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
- **Conceptos cortos (corrección tras P4).** En la medición con Gemini, el planificador escribió oraciones y listas como conceptos («no hay confirmacion de entrega o recepcion», «puerto de origen, puerto de destino, longitud y suma de verificación»), y la comprobación de cobertura rechazó los recursos que los parafraseaban. Desde esta corrección:
  - **Qué es un concepto:** una frase nominal de 2 a 4 palabras útiles tomadas del material, o una sigla; nunca una oración, una lista, una pregunta ni una palabra suelta común. La regla es `short_concept_problem` (`plan_validation.py`): sin comas ni signos de oración, sin negaciones ni verbos conjugados frecuentes, y con 7 palabras como máximo contando las vacías.
  - **En la validación:** un concepto que no la cumple es el problema `CONCEPT_NOT_SHORT`, así que el docente lo ve junto al ítem.
  - **Con Gemini:** el prompt y la descripción del esquema piden frases de 2 a 4 palabras. Los conceptos largos que devuelva se descartan; si el ítem se queda sin conceptos suficientes, el plan va al respaldo por reglas.
- **Dos límites de ítems, a propósito.** Al crear el plan, la IA arma un ítem por tipo pedido, así que su esquema tiene como máximo 8 ítems. Un plan editado con `PUT` acepta hasta 40 ítems (`UpdateGenerationPlan.items` del contrato, `maxItems` 40): el docente puede partir un tipo en varios ítems con conceptos distintos (8 tipos × 5 de cantidad = 40). Los dos límites son intencionales: el primero limita lo que la IA propone, y el segundo, lo que el docente puede editar.
- **Después de la respuesta:** las etiquetas se traducen a ids, se descartan los tipos no pedidos, se calcula `doesNotCover` y se valida.
- **Respaldo:** si la llamada vence a los 60 s, si la respuesta no es JSON válido, o si el plan resultante no es válido, se arma con reglas y `generator.fallbackReason` guarda el motivo público genérico de `provider_errors.py`.
- **Reintento con los problemas (segunda corrida de P4).** En 2 de 3 corridas con plan, Gemini devolvió un plan no válido (`CONCEPT_OWNED_TWICE`, `NOT_ENOUGH_CONCEPTS`) y se usó el de reglas.
  - Desde entonces, si el plan no es válido (problemas de validación o tipos que faltan), se le pide una vez más. Se le devuelve, por cada problema, el código, el ítem (posición y tipo) y el mensaje. Si vuelve a fallar, se arma con reglas.
  - Un error del proveedor, un tiempo vencido o un JSON inválido no se reintentan aquí: el adaptador de Gemini ya reintenta el JSON.
  - `generator.attempts` guarda las llamadas a la IA (0 sin IA, 1 o 2).
  - El reintento puede duplicar el tiempo de creación del plan con Gemini (dos llamadas de hasta 60 s); V9 mide si el p95 sigue bajo 30 s.

Un plan de la IA con conceptos repetidos entre ítems no se corrige a mano: cuenta como inválido y va al respaldo por reglas, igual que los recursos sin la estructura del tipo (T073).

**Alternativa descartada.** Una llamada por ítem: multiplica las llamadas y no evita la repetición, porque cada llamada no ve los conceptos de las demás.

## R5. Generación desde el plan (GEN-P2)

**Decisión.** El pedido ejecuta un paso por ítem, como hoy un paso por tipo, con la evidencia del plan. Cada recurso del ítem se redacta por separado:

- **Lo que recibe el prompt de cada recurso:**
  - su bloque de conceptos (`covers` del bloque), que debe desarrollar completo;
  - el propósito del ítem;
  - los conceptos de los demás recursos del plan, que no debe desarrollar: los `doesNotCover` del ítem y los bloques de los otros recursos del mismo ítem. Puede nombrarlos, pero no explicarlos (en los recursos de un solo párrafo, no debe nombrarlos; ver la comprobación de cobertura);
  - el resumen de lo ya cubierto: por cada recurso entregado antes en el pedido, su título, sus conceptos y un resumen de hasta 300 caracteres (`secuenciaPrevia`, como hoy);
  - la evidencia, con los fragmentos del ítem primero.
- **Sin acortar.** Se mantienen las reglas de formato y extensión de cada tipo; se quita la instrucción «si los fragmentos no alcanzan, devuelve menos recursos» para los ítems del plan, porque el plan ya decidió cuántos.
- **Comprobación de cobertura**, léxica y sin IA, con la normalización de QA-05 (corregida tras la medición de P4):
  - **Conceptos propios.** El recurso desarrolla al menos uno de sus conceptos: el 60 % o más de sus palabras útiles en un mismo párrafo (el título, un párrafo, un texto de la estructura o una opción). Se cuenta así, y no la frase exacta, para que valga una paráfrasis («un saludo en tres pasos» para «saludo de tres vías»). Las palabras se comparan por su raíz: sin plural y, si tienen seis letras o más, por sus seis primeras, como en la verificación de anclaje («confirma» y «confirmación»).
  - **Conceptos ajenos.** Cuentan solo si el recurso los desarrolla: el término completo en al menos dos oraciones, o en una oración que lo define («El protocolo UDP es…», «Datagrama: …»). Nombrarlo una vez no cuenta, tampoco en un recurso corto. Así se reemplaza la regla estricta de los recursos de un solo párrafo, que en P4 rechazaba simples menciones. No cuenta un concepto ajeno que solo aparece dentro de uno propio («capas» en «capa de transporte»), ni la retroalimentación de las opciones.
  - **Conceptos de fondo.** Un concepto del plan que está en los fragmentos de la mitad o más de los ítems (y de al menos 2) es contexto compartido de la unidad, no de un solo recurso. No se le pasa a ningún recurso como ajeno, ni en el prompt ni en la comprobación. Ejemplos de P4: «capa de transporte», «Transmission Control Protocol».
  - **Qué es un párrafo.** Los párrafos se separan con una línea en blanco; si no hay ninguna, cada línea es un párrafo, como en la verificación del glosario (HU-049). Cada texto de la estructura y cada opción cuentan como un párrafo más.
  - **El prompt de los tipos breves** sigue diciendo «no los nombres» para `pregunta_detonante`, `item_opcion_multiple`, `audio_detonante` y los tipos del catálogo de hasta 120 palabras. Es más estricto que la comprobación, a propósito: nombrar una vez no se rechaza.
  - **Falsos rechazos (T013).** `tests/fixtures/plan_coverage_short_resources.json` tiene 16 recursos cortos que solo nombran un concepto ajeno o ninguno (marcados correctos) y 6 que lo desarrollan (incorrectos): 0 falsos rechazos y 0 aceptados por error. `tests/fixtures/plan_coverage_p4_cases.json` rearma los casos de P4 con oraciones del corpus de T067. Sergio debe revisar las marcas con el corpus.
- **Si la comprobación falla**, se pide de nuevo una vez con la indicación del problema. **Política tras P4** (acordada al revisar la medición):
  - **Recurso de la IA:** si después del reintento solo falla la comprobación del plan (el anclaje y la estructura pasaron), se entrega igual, con un aviso de solapamiento. El recurso lleva `planWarning` (`kind` `overlap` o `missing_concepts`, el motivo y los conceptos) y el paso lo lista en `planWarnings`. Revisión lo muestra y el docente decide. No se reemplaza con el generador por reglas.
  - **Camino por reglas:** el rechazo `kind: plan` queda solo para él (el generador por reglas como principal, o un respaldo que tampoco respeta el plan).
  - **Si falla el anclaje o la estructura**, el respaldo por reglas actúa como siempre.
  - **Por qué (lo que se gana y lo que se pierde).** En P4, 14 de 24 pasos con plan terminaron en el respaldo por reglas (3 de 24 sin plan). La duplicación bajó (32,3 % → 12,0 %), pero en parte porque los recursos los redactaron las reglas, con oraciones del material casi literales, más cortos y menos variados. Cambiar un buen recurso de la IA por uno de reglas por un solapamiento parcial cuesta más calidad de la que ahorra en repetición. A cambio, un recurso con aviso puede repetir algo de otro: la duplicación puede subir un poco frente a la medición anterior. Por eso el aviso se ve en Revisión, y la medición de P4 cuenta los pasos de la IA, los del respaldo y los avisos de cada corrida (`measure_duplication.py`), para comparar con los mismos generadores.
- **Verificación de anclaje (HU-016, HU-049, REV-01):** sin cambios. Cada recurso se verifica contra la evidencia del plan.
- **Control de repetición:** el filtro léxico actual (`SIMILARITY_THRESHOLD` = 0,6 en `domain/generation/sequence.py`) se mantiene como red de seguridad. Con el plan, su reintento agrega los conceptos que el recurso no debe repetir.
- **Generador por reglas:** redacta cada recurso con las oraciones de los fragmentos que contienen sus conceptos, así respeta el plan sin IA. Al implementar GEN-P2:
  - deja fuera las oraciones que desarrollan conceptos de otros recursos y no repite un concepto ajeno en dos oraciones;
  - prefiere las oraciones que no usaron los recursos anteriores (`secuenciaPrevia`), así dos bloques del mismo ítem no quedan iguales y el filtro de repetición no los rechaza;
  - si no hay oraciones nuevas de sus conceptos, reutiliza las ya usadas antes que dejar el recurso vacío.

- **Lo que guarda cada recurso:** `params.planId`, `params.planItemPosition` y `params.planBlock` (el bloque, desde 0). La regeneración desde Revisión los usa para rehacer ese bloque (R2).
- **Sesión (CUR-P3):** cuando el plan pasa a usado, se llama a `record_typology` con los tipos del plan. Si Cursos falla, el pedido sigue: la tipología es contexto para el plan siguiente, no una condición para generar.

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
| `verification` | `strict` o `framed` en los tipos de texto nuevos ([verificación](#verificación-strict-y-framed)). |
| `modalities` | Las modalidades que lo incluyen (HU-024). |
| `hasOptions` | Solo `item_opcion_multiple`. |
| `active` | Si se ofrece en el formulario. |

**Lo que entrega Cursos (CUR-P2) por cada tipo nuevo**, además de `id`, `name`, `singular` y `plural`:

| Campo | Valor |
| --- | --- |
| `stage` | Una de las cinco etapas. |
| `description` | Qué es el recurso y cómo lo usa el estudiante, en una o dos oraciones. |
| `lengthHint` | Opcional: `{minWords, maxWords}`. |
| `verification` | `strict` o `framed`. |
| `modalities` | Las modalidades que lo incluyen. |
| `format` | `text`. |
| `structure` | `none`. |
| `active` | `true` para ofrecerlo en el formulario. |

<a id="extensión-lengthhint"></a>**Extensión (`lengthHint`).**
- **Forma.** Un objeto opcional `{minWords, maxWords}`, con enteros: `minWords` ≥ 20, `maxWords` ≤ 600 y `minWords` ≤ `maxWords`. Cursos valida estas reglas al guardar la entrada; si Generación recibe una entrada que no las cumple, la trata como si no tuviera `lengthHint`.
- **Uso.** Es una guía para la redacción: el prompt pide «entre X y Y palabras». Nunca es una regla de rechazo: un recurso más corto o más largo no se rechaza ni se regenera por su extensión.
- **Sin `lengthHint`.** Vale la extensión por defecto del prompt genérico, la misma de `explicacion`: de 3 a 5 párrafos, sin un rango de palabras.

<a id="verificación-strict-y-framed"></a>**Verificación (`strict` y `framed`).** Acordado con CUR-P2 (PR #70 de Silvana: 15 tipos `strict` y 13 `framed` en el borrador del catálogo). En los dos modos se verifican las citas (HU-016), como en todos los tipos.
- **`strict`:** cada párrafo se contrasta con el material, como en `explicacion` (HU-049): los párrafos sin respaldo se quitan y, si queda menos de la mitad, el recurso se rechaza (`kind: grounding`).
- **`framed`:** las oraciones de ambientación (la escena, los personajes, el formato de noticia o de diálogo) y las preguntas al estudiante no necesitan cita. Cada oración sobre un concepto del recurso (las que nombran alguno de sus conceptos del plan) sí: si una no se apoya en el material, el recurso se rechaza. También se rechaza si tiene menos de 2 afirmaciones sobre sus conceptos con respaldo. El rechazo es `kind: grounding`, con un motivo claro («solo 1 afirmación sobre los conceptos se apoya en el material; este tipo necesita al menos 2»).
- **Evidencia que necesita un tipo `strict`.** Antes de redactar, si la evidencia del ítem no tiene lo que el tipo necesita, el recurso no se redacta (ni con la IA ni con reglas) y se rechaza (`kind: grounding`) con el motivo:
  - `frase_celebre_comentada` necesita una cita textual en un fragmento del ítem (entre comillas, de 4 palabras o más): «El material no tiene una cita textual para este tema.»;
  - los demás tipos `strict` necesitan que algún fragmento del ítem trate al menos uno de sus conceptos.

  La exigencia de cada tipo está en el código de Generación (`EVIDENCE_REQUIREMENTS`); si Cursos agrega tipos con otras exigencias, conviene que el catálogo las declare en un campo propio.

**Tipos nuevos de texto.**
- Se redactan con un prompt genérico: la `description` de la entrada, su `lengthHint` (o la extensión por defecto), el ítem del plan y el contenido con citas como en `explicacion`.
- Se verifican según su `verification` (arriba).
- El generador por reglas tiene un redactor genérico con las oraciones de los conceptos del ítem: en `strict`, párrafos citados; en `framed`, una oración de ambientación, las oraciones citadas y una pregunta. La frase célebre empieza por la oración con la cita textual.
- **Mientras CUR-P2 no los cablee**, los 28 tipos nuevos siguen inactivos: el adaptador provisional del catálogo no los ofrece. Las pruebas usan entradas falsas de los dos modos.
- Revisión y la exportación los tratan como texto. Su etiqueta sale del catálogo, sin caer en «Pregunta de opción múltiple», como pide T059.

**Alternativa descartada.** Escribir un redactor por cada tipo nuevo: no escala a 50 a 75 tipos, y los tipos de texto solo cambian la intención.

## R7. Medición de la duplicación (P4)

**Lo que aprendimos de las dos primeras corridas con Gemini** (`docs/evidence/GEN-P4/v1-*` y `v2-*`):
- **v1:** −62,8 % en la tasa de pares, pero 14 de 24 pasos con plan los redactó el respaldo por reglas. La baja venía sobre todo de eso.
- **v2:** con la corrección del respaldo, la IA redactó 21 de 24 pasos sin plan y 20 de 24 con plan, y la tasa de pares quedó en 30,1 % frente a 29,7 % (−1,4 %).
- **Planes de reglas:** en 2 de 3 corridas con plan, el plan de Gemini no fue válido y se usó el de reglas (de ahí el reintento de R4).
- **La métrica de pares mide el tema:** la similitud máxima media fue de 0,91 en los dos modos. Con τ = 0,85, la métrica de pares capta sobre todo «el mismo tema», no «contenido repetido».
- **Pocas corridas:** con 3 corridas por modo, la tasa varió entre 0,20 y 0,41 de una corrida a otra.
- **v3** (5 corridas por modo, τ = 0,885 y umbral de oraciones 0,865 de `calibration-v2.json`):
  - pares: 10,1 % → 6,5 % (−36 %); oraciones casi repetidas: 52,4 % → 40,5 % (−23 %); conceptos explicados otra vez: 1,2 → 1,2;
  - con plan hubo más respaldo (8 de 40 pasos, frente a 5 de 40) y menos recursos por pedido (15,0 frente a 15,8);
  - **qué falló en la medición:** las oraciones incluían títulos; no separaban la repetición entre recursos distintos de la de las dos variantes de un tipo; y la métrica de conceptos no discriminaba (solo «capa de transporte», en los dos modos). Las métricas se corrigieron (abajo) y la v3 se puede recalcular sin generar (`--recompute`).

**Métricas.** Por cada generación (`evaluation/measure_duplication.py`):
- **Oraciones casi repetidas (evidencia principal).** La parte de las oraciones de 8 palabras o más (normalizadas) que tienen una casi igual en otro recurso de la misma generación: coseno de embeddings de oración ≥ un umbral calibrado (0,92 hasta calibrarlo), o Jaccard ≥ 0,6 si no hay embeddings. Es lo más parecido a la queja del profesor: el mismo contenido redactado otra vez.
  - **Sin títulos:** el título del recurso y los encabezados de su estructura (títulos de pasos, titulares, conceptos centrales) no son oraciones. En los informes v3 y anteriores, que guardan el texto con el título en la primera línea, esa línea se quita al recalcular.
  - **Tres cifras:** todos los pares (`all`); los de recursos de tipos distintos (`crossType`, **la principal**, porque la queja es la repetición entre recursos distintos); y los de recursos del mismo tipo (`variants`, las dos variantes de un tipo), aparte. Cada grupo trae sus ejemplos.
- **Conceptos explicados otra vez (evidencia principal).** Los conceptos que se definen o se desarrollan en más de un recurso, con la regla de la comprobación del plan (dos oraciones, o una definición: `plan_coverage.develops_concept`).
  - `conceptReexplanationEvidence` usa en los dos modos los mismos conceptos: los candidatos de la evidencia del pedido, con la extracción del planificador por reglas. Los dos modos piden 12 fragmentos. Es la que se compara.
  - `conceptReexplanation` usa los conceptos del plan si lo hay; sirve para ver el plan por dentro.
  - **Tabla por concepto (`table`):** en cuántos recursos se menciona (el término completo en una oración), se desarrolla (la regla de arriba) y se define (una oración que lo define). En la v3 la métrica no discriminó; la tabla muestra si la regla de «desarrollado» es demasiado estricta antes de cambiarla. La regla no cambia todavía.
- **Tasa de pares duplicados (secundaria).** Pares de recursos con similitud de embeddings ≥ τ ÷ total de pares, con la misma división: todos, `crossType` y `variants`. Se conserva la meta de P4 sobre la de todos. La similitud máxima media se sigue informando.
- **Solo los recursos de la IA (`aiOnly`).** Las mismas métricas sin los recursos del respaldo por reglas, en cada corrida y en el resumen, para que la comparación no la sesgue el respaldo (que en la v3 fue mayor con plan).
- **Contexto de cada corrida.** Pasos redactados por la IA, por el respaldo y por reglas; avisos de solapamiento del plan (R5); y si el plan salió de Gemini (en 1 o 2 intentos) o del planificador por reglas. Una baja que viene de recursos del respaldo o de planes de reglas no cuenta como evidencia de la IA con plan.
  - **`fallbacks`:** qué pasos redactó el respaldo y por qué (`steps[].generator.fallbackReason`).
  - **`undelivered`:** qué recursos planeados no se entregaron (en la v3, 14 o 15 de 16 con plan), con los rechazos o el error de su paso.

**Recalcular sin generar.** `measure_duplication.py --recompute --from <informe> --out <nuevo>` recalcula todas las métricas con los textos guardados en el informe (solo embeddings) y conserva los datos de cada corrida.
- **Quién redactó cada recurso:** en los informes v3, sale del paso de su ítem (con plan) o de su tipo.
- **Conceptos:** si el informe no los guarda (v3 y anteriores), se leen de la API con la misma cuenta. Sin cuenta, quedan vacíos.
- **Comparar:** acepta `--compare`. Para comparar, se recalculan los dos informes con los mismos umbrales.
- **Desde ahora:** los informes guardan, por recurso, el texto completo, el texto sin títulos y quién lo redactó, y los conceptos de la evidencia y del plan, así el recálculo no necesita la API.

**Cómo se eligen τ y el umbral de oraciones.** Con `measure_duplication.py --calibrate --from <informes>`:
- **Pares sin repetición:** recursos de tipos distintos en ítems distintos del plan, y de otro corpus si se pasa un informe de otro corpus.
- **Pares repetidos:** el mismo recurso con sus oraciones en otro orden, y medio recurso copiado. En oraciones: la misma oración sin su primera palabra y con sus mitades cambiadas.
- **Umbral sugerido:** el punto medio entre el p95 de los pares sin repetición y el p5 de los repetidos.
- **Si se mezclan** (`overlap`), se informa el p95 de los pares sin repetición, y esa métrica no sirve para separar «mismo tema» de «repetido». Es lo que se espera de los pares completos.
- **Registro:** el umbral elegido y el informe de calibración van en `docs/evidence/GEN-P4/`. τ = 0,85 queda hasta que la calibración o REV-P3 fijen otro.

**Procedimiento.**
- **Corpus:** `corpus_t067` (unidad de redes de C-01 a C-05).
- **Pedido:** una secuencia de 8 tipos de texto × 2 recursos, la misma de `measure_generation_load.py`. Se repite **5 veces** con cada generador (reglas y Gemini): con 3, la variación entre corridas tapaba la diferencia.
- **Línea base:** sin plan, en el mismo servidor y la misma base, con `GENERATION_IMPLICIT_PLAN=false` (interruptor solo de medición: redacta el cuerpo anterior como antes de GEN-P1; [plan](plan.md#medición-de-p4)).
- **Con plan:** aprobado sin cambios.

Se registran en `docs/evidence/GEN-P4/` los dos informes (con su fidelidad) y la calibración.

**Fidelidad (T027 c).** La meta de P4 pide que el plan no baje la `faithfulness` de 0,90. `measure_duplication.py --faithfulness` la calcula en el mismo informe, en una corrida nueva o con `--recompute` sobre un informe guardado:
- **Métrica y juez:** la `Faithfulness` de Ragas con el juez de `evaluation/run_ragas.py`: el mismo modelo (`RAGAS_JUDGE_MODEL`, `gemini-3.8-flash` por defecto), temperatura 0 y la misma configuración (180 s por llamada, 5 reintentos). `ResponseRelevancy` no se usa.
- **Por cada recurso entregado:**
  - la respuesta es el recurso sin su título ni los encabezados de su estructura (el texto de las oraciones);
  - el contexto son los textos de los fragmentos que cita, la copia que guarda el recurso y muestra Revisión (`evidence`), como `run_ragas.py --contexts cited`;
  - la pregunta son las indicaciones del pedido (las mismas en los dos modos).
- **Omitidos:** los recursos sin citas no se califican y se cuentan (`skipped`).
- **Errores:** si el juez falla con un recurso, el error queda en ese recurso (`errors`) y la medición sigue. Un puntaje vacío (NaN) también cuenta como error.
- **Informe:** por corrida y en el resumen, la media, la parte de recursos con 0,90 o más (`atLeastTarget`) y cuántos se calificaron, se omitieron o fallaron; lo mismo solo con los recursos de la IA (`aiOnly`) y por tipo (`byType`). El resumen trae además la media de las medias por corrida (`meanPerRun`).
- **Comparación:** con `--compare`, la diferencia plan − línea base y si el plan mantiene la media en 0,90 o más (`planMeetsTarget`), con todos los recursos y en `aiOnly`.
- **Textos guardados:** el informe guarda los textos citados de cada recurso, así un recálculo posterior no usa la API. Los informes v4 y anteriores no los guardan: el primer `--recompute --faithfulness` los lee una vez con la misma cuenta.
- **Llamadas al juez:** van en paralelo con pocos hilos (`--judge-concurrency`, 2 por defecto) y con el progreso en pantalla. Un recálculo solo califica los recursos sin puntaje, salvo con otro juez o con `--rescore-faithfulness`.

**Comparabilidad con la v5.**
- **Conceptos:** desde T027 (b), los conceptos candidatos de la evidencia (`conceptReexplanationEvidence`) salen de `concept_extraction.py`, la misma extracción del planificador por reglas, sin frases pegadas («ftp sftp») ni encabezados de página. Las cifras de conceptos de la v3 y la v4 no se comparan con las de la v5. Las de oraciones y pares sí.
- **Opción múltiple:** en la v1 a la v4, `item_opcion_multiple` fue siempre al respaldo por reglas, con plan y sin plan, porque el esquema de Gemini no pedía el error conceptual de cada distractor (T027 a). En esas versiones, sus recursos no son de la IA en ningún modo.

**Cómo leer el resultado.**
1. **Primero, ¿los dos modos los redactó la IA?** Mira `aiSteps` frente a `fallbackSteps` y `planGenerators`. Si el plan salió de reglas en varias corridas, la comparación no mide el plan de Gemini.
2. **Luego, la evidencia de «no repetición»:**
   - `crossTypeSentenceRate` (la principal): oraciones casi repetidas entre recursos de tipos distintos. `sentenceNearDuplicateRate` (todas) y `variantsSentenceRate` (variantes de un tipo) van aparte;
   - `meanReexplainedEvidenceConcepts`: conceptos explicados en más de un recurso, con los mismos conceptos en los dos modos, y la tabla por concepto;
   - `crossTypeSentenceReduction` y `reexplainedConceptsReduction` (con `--compare`), la baja frente a la línea base;
   - lo mismo en `aiOnly`, sin los recursos del respaldo: si la baja no se sostiene ahí, viene del respaldo.
3. **Al final, la tasa de pares,** con su umbral calibrado y sabiendo que mezcla tema y repetición.

**Resultado (v3 recalculada y v4, con Gemini).** Evidencia en `docs/evidence/GEN-P4/`: `v3r-gemini-baseline.json`, `v3r-gemini-plan.json` (la v3 recalculada con las métricas corregidas) y `v4-gemini-plan.json`, comparado con la línea base v3r. Umbrales de `calibration-v2.json`: τ = 0,885 y 0,865 en oraciones. Cinco corridas por modo.

| Métrica | Línea base | Plan v3 | Plan v4 |
| --- | --- | --- | --- |
| Oraciones casi repetidas entre tipos distintos (principal) | 32,4 % | 21,2 % (−35 %; solo IA −39 %) | 21,1 % (−35 %; solo IA −50 %) |
| Pares duplicados entre tipos distintos (secundaria) | 6,0 % | 2,7 % (−56 %) | 4,1 % (−32 %) |
| Conceptos explicados otra vez (evidencia) | 0 | 0,4 | 0,6 |
| Recursos por pedido (de 16) | 15,8 | 15,0 | 16,0 |
| Planes de Gemini / de reglas | — | 5 / 0 | 1 / 4 |

- **La métrica principal es la de oraciones entre tipos distintos.** Es la queja del profesor: el mismo contenido redactado otra vez en recursos distintos. Las variantes de un tipo se parecen por diseño, así que la cifra de todos los pares y la de `variants` se informan, pero no cuentan para la meta.
- **El resultado se repite.** La baja de −35 % se dio en las dos corridas con plan, aunque los planes de la v3 fueron 5 de 5 de Gemini y los de la v4, 4 de 5 del planificador por reglas. Solo con los recursos de la IA, la baja se mantiene o crece (−39 % y −50 %): no viene del respaldo.
- **Pares entre tipos distintos:** bajan en las dos corridas, pero cambian mucho de una a otra (−56 % y −32 %). Se informan como evidencia secundaria.
- **Conceptos explicados otra vez:** no discriminan (0 frente a 0,4 y 0,6). El resultado es inconcluso; la tabla por concepto queda para revisar la regla.
- **Recursos:** la pérdida de la v3 (15,0 de 16) no se repitió en la v4 (16,0 de 16, `resourcesKept`).
- **Meta de P4, cumplida en parte.**
  - El valor absoluto se cumple: pares entre tipos distintos ≤ 5 % en las dos corridas con plan.
  - La baja de al menos 50 % solo se cumple en la v3.
  - La evidencia principal (oraciones entre tipos distintos) baja un 35 % en las dos.
  - El `meetsTarget` del informe se calcula sobre todos los pares y sale `false`; para P4 vale la cifra entre tipos distintos.

**v5 (descartada).** Se corrió con los arreglos de T027 y `--faithfulness`, pero la comparación no es justa y no se usa para P4:
- **Otro modelo:** el backend arrancó con el `LLM_MODEL` por defecto (`gemini-3.8-flash`), no con `gemini-3.5-flash-lite`, el de Render y el de la v1 a la v4.
- **Mucho respaldo:** con ese modelo, 16 de 40 pasos de la línea base fueron al respaldo por reglas (10 por el límite de 60 s y 6 por lecturas sin respuesta) y, según la salida de la corrida con plan, 19 de 40. Con tanto respaldo, ninguno de los dos modos mide a la IA.
- **Sin informe con plan:** la corrida con plan terminó, pero no escribió su informe. Se cayó al leer el `--compare`, que todavía no existía. Ya está corregido: los archivos de `--compare` y `--from` se comprueban antes de generar, y el informe se escribe antes de comparar. Ver [plan](plan.md#medición-de-p4), «Sin perder corridas».
- **Lo que se conserva:** `docs/evidence/GEN-P4/v5-gemini-baseline.json`, solo como evidencia de la fidelidad por tipo sin plan (75 recursos calificados, juez `gemini-3.8-flash`):

| Tipo | `faithfulness` | Quién redactó |
| --- | --- | --- |
| `glosario` | 0,99 | respaldo (8 de 9) |
| `explicacion` | 0,93 | IA |
| `sondeo_diagnostico` | 0,92 | respaldo (10 de 10) |
| `pregunta_detonante` | 0,79 | IA |
| `caso_indagacion` | 0,38 | IA |
| `item_opcion_multiple` | 0,30 | IA |
| `ejercicio_aplicacion` | 0,12 | IA (4) y respaldo (3) |
| `guia_exploracion` | 0,07 | respaldo (8) e IA (2) |

- **Por qué las actividades salen bajas:**
  - el juez parte el recurso en afirmaciones y busca cada una en los fragmentos citados;
  - las consignas al estudiante («Observa…», «Anota…», «Explica por qué…») y los escenarios inventados (un caso, una empresa, unos datos de ejercicio) no están en el material, así que el juez los cuenta como afirmaciones sin respaldo;
  - pasa con la IA y con el respaldo por reglas (`guia_exploracion` 0,09 con reglas), así que no es un problema de fidelidad del contenido sino de lo que mide la métrica.
- **La meta absoluta de 0,90 sirve solo para los tipos de contenido** (`explicacion`, `glosario` y similares). Viene de QA-05, que la midió solo con explicaciones (C-01 a C-05, media 0,97). Aplicada a todos los tipos, ninguna generación con actividades la cumpliría, con plan o sin él.
- La media de todos los recursos (0,57; 0,53 solo con la IA) mezcla tipos y quién redactó, así que no se usa.

**Conclusión de P4.**
- **Resultado principal: el plan baja la duplicación.** Las oraciones casi repetidas entre recursos de tipos distintos bajan un 35 % en la v3 y en la v4, con planes de Gemini (v3) y de reglas (v4), y la baja se sostiene solo con los recursos de la IA (−39 % y −50 %). Los pares duplicados entre tipos distintos quedan en 5 % o menos en las dos; la baja de 50 % solo se cumple en la v3.
- **La parte de fidelidad de la meta no está verificada con plan.** La v1 a la v4 no la midieron y la v5 se descartó.
- **Criterio propuesto (decisión del profesor):**
  - los tipos de contenido mantienen una `faithfulness` de 0,90 o más con plan;
  - ningún tipo baja más de 0,05 frente a la línea base;
  - medido con `gemini-3.5-flash-lite`, el modelo de producción, y comparado por tipo (`summary.faithfulness.byType` y `aiOnly`), no con la media de todos los recursos.
- **Pendiente:** la decisión del profesor sobre el criterio y, con ella, la medición de la fidelidad con plan ([tareas](tasks.md), T028; T019 queda abierta solo por eso).

**Meta.**
- **Evidencia principal:** con plan, las oraciones casi repetidas entre recursos de tipos distintos bajan frente a la línea base, con la mayoría de los pasos redactados por la IA en los dos modos; los conceptos explicados otra vez se informan.
- **Tasa de pares (se conserva la meta de P4):** la de recursos de tipos distintos, con plan, baja al menos un 50 % frente a la línea base y queda en 5 % o menos, con el τ calibrado.
- **Recursos:** los entregados no bajan.
- **Fidelidad:** la `faithfulness` media sigue en 0,90 o más. Como meta absoluta solo aplica a los tipos de contenido (ver «v5 (descartada)»); el criterio por tipo queda para decidirlo con el profesor.

Mientras REV-P3 no esté, sin embeddings la medición usa la similitud léxica (Jaccard de `most_similar`, `domain/generation/sequence.py`), registrada como provisional.

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

## R11. Conceptos de unidades anteriores

**Problema.** Cada plan se arma solo con la evidencia de su unidad. Si el material de la unidad 2 vuelve a nombrar lo que ya se trató en la unidad 1, el plan lo asigna otra vez como concepto propio y los recursos lo vuelven a explicar.

**Decisión.** Mismo patrón que CUR-P3 (R9): un puerto, `PreviousUnitConceptsPort.previous_unit_concepts(teacher_id, unit_id, limit)`, con un adaptador sobre los cursos del docente y los planes guardados.

- **Unidades anteriores.** Las del mismo curso con `number` menor que el de la unidad del plan. Una unidad sin `number` toma su posición en el curso (1, 2, 3…).
- **Qué plan cuenta.** El último plan `approved` o `used` de cada unidad (por `updatedAt`); los borradores no cuentan. Sus conceptos son los `covers` de todos sus ítems, sin repetir (singular y plural, con o sin tildes son el mismo concepto).
- **Tope.** Hasta 12 conceptos por unidad y 30 en total, empezando por la unidad más cercana. Un concepto ya tomado de una unidad más cercana no se repite.
- **Aislamiento.** Solo los cursos y los planes del mismo docente.
- **Congelado.** Se guardan al crear el plan en `sessionContext.previousUnitConcepts` (`[{unitNumber, unitTitle, concepts}]`, de la unidad más antigua a la más reciente), como `previousTypologies`: editar o aprobar el plan no los recalcula. No forman parte de `inputs` ni del hash de la clave, porque no los pide el docente. Si el puerto falla, el plan se arma sin ellos.

**Uso en el plan.**
- **Reglas.** Un candidato que es el mismo concepto que uno de unidades anteriores no se asigna a un ítem, salvo que sea un término del resultado de aprendizaje elegido (sus frases y siglas, o un concepto que aparece completo en su texto). Válvula: si sin ellos no alcanzan los conceptos mínimos del plan, se usan al final, para que el plan no quede inválido por esto.
- **Gemini.** El prompt del plan los lista como «YA TRATADOS EN UNIDADES ANTERIORES: refiérete a ellos, no los vuelvas a explicar ni los pongas como conceptos de los ítems, salvo los del resultado elegido». El esquema de respuesta no cambia.
- **Interfaz.** La pantalla del plan los muestra de solo lectura, por unidad (pendiente en el frontend).

**Uso en la generación (GEN-P2).** Los conceptos de unidades anteriores que el plan no asignó a ningún ítem van al prompt de cada recurso («refiérete a ellos sin volver a explicarlos») y a la comprobación del plan: un recurso que desarrolla uno de ellos, con la misma regla que un concepto ajeno (R5), se entrega con el aviso `planWarning.kind: previous_unit`, tanto de la IA como de reglas. No se rechaza ni se pide otra vez: el material de la unidad puede necesitar recordarlo.
