# Plan antes de generar

**Ficha** GEN-01 · GEN-P1 · GEN-P2 · GEN-P3

**Responsable** Yan

**Estado** Borrador (reunión con el profesor del 21/11/2026)

**Referencias** [Constitución de Plataforma 5E](../../.specify/memory/constitution.md), [Generación (GEN-01)](../002-generacion-multiple/spec.md), [Atributos de calidad](../005-atributos-calidad/spec.md), [Material y Evidencia](../004-material-y-evidencia/spec.md), [Cuentas y Cursos](../003-cuentas-y-cursos/spec.md) y [Revisión y Exportación](../001-revision-citas/spec.md).

## Objetivo y alcance

Antes de generar recursos, el sistema arma un **plan** que el docente revisa, edita y aprueba. El plan dice qué recursos se van a generar, en qué orden y etapa, para qué sirve cada uno, qué conceptos le corresponden a cada uno y en qué fragmentos del material se apoya. La generación parte siempre de un plan aprobado: cada recurso se redacta por separado a partir de su ítem del plan y de lo que ya cubren los recursos anteriores, sin repetirse y sin acortarse.

- **GEN-P1.** Etapa de planificación obligatoria: el plan como recurso propio, con su contrato JSON, su validación y su creación con IA o con reglas.
- **GEN-P2.** Generación de cada recurso desde su ítem del plan y del resumen de lo ya cubierto.
- **GEN-P3.** Frontend: revisión, edición y aprobación del plan antes de generar.

Otros equipos programan contra este contrato:

| Ficha | Responsable | Qué aporta al plan |
| --- | --- | --- |
| MAT-P2 | Sergio | Los «referentes» del tema (autores principales), por un puerto de Material. El plan los guarda; pueden faltar. |
| CUR-P3 | Silvana | Las tipologías usadas en las sesiones anteriores del curso, para que el plan siguiente varíe. Pueden faltar. |
| CUR-P2 | Silvana | El catálogo configurable de tipos: de 10 a 15 por etapa, selección múltiple y cantidad opcional. |
| REV-P3 | Juan | El indicador de duplicación entre recursos de una misma generación, por similitud de embeddings. Mide P4. |

Fuera de alcance: lo que cambia en la recuperación con los referentes (P8) y el editor WYSIWYG (P10) quedan como [preguntas abiertas](#preguntas-abiertas-para-el-profesor).

## Historia de planificación

Como docente, quiero ver y ajustar un plan de los recursos antes de generarlos para que cada uno tenga un propósito propio y no repita a los demás.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| PLAN-C1 | Pido un plan para una unidad con material procesado, con indicaciones, audiencia, competencia, resultado, modalidad y tipos (cantidad opcional) | Recibo un plan en borrador con sus ítems ordenados por etapa. Cada ítem trae tipo, cantidad, propósito, conceptos que le corresponden, conceptos que le corresponden a otros ítems y los fragmentos que lo respaldan. |
| PLAN-C2 | Lo pido con `LLM_PROVIDER=rules`, o la IA no responde en 60 s o responde un plan inválido | El plan se arma con reglas, de forma determinista, y `generator.fallbackReason` dice por qué no se usó la IA. |
| PLAN-C3 | El material de la unidad no trata el tema de las indicaciones (QA-05) | No se crea el plan: `422 INSUFFICIENT_EVIDENCE` con el motivo que nombra lo que falta. |
| PLAN-C4 | Edito el plan: propósito, conceptos, fragmentos, cantidad, orden, agrego o quito ítems | El plan sube de versión y vuelve a borrador. Si deja de ser válido, se guarda igual y muestra cada problema; no se puede aprobar hasta corregirlo. |
| PLAN-C5 | Apruebo el plan con su versión actual | Queda aprobado. Si otra pestaña lo cambió, `409 PLAN_VERSION_CONFLICT` y no se aprueba. |
| PLAN-C6 | Pido generar con un plan aprobado | Se crea el pedido de generación con el plan y su versión, y el plan pasa a usado. Un plan en borrador, con otra versión o ya usado no genera. |
| PLAN-C7 | Otro docente consulta, edita o usa mi plan | Responde `404 PLAN_NOT_FOUND`, igual que un plan inexistente. |
| PLAN-C15 | Entre la aprobación y la generación borro o vuelvo a procesar un documento del plan | La generación responde `409 PLAN_EVIDENCE_STALE` con los documentos afectados y no crea el pedido. Creo un plan nuevo. |

## Historia de generación desde el plan

Como docente, quiero que cada recurso desarrolle completo lo que le asignó el plan y no repita lo que ya cubren los demás.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| PLAN-C8 | Se genera un plan aprobado | Cada recurso se redacta por separado con su ítem (propósito, conceptos propios, conceptos ajenos) y el resumen de lo que cubrieron los ítems anteriores. Usa la evidencia que el plan congeló. |
| PLAN-C9 | Un recurso no desarrolla ninguno de sus conceptos, o desarrolla un concepto de otro ítem | Se pide de nuevo una vez con la indicación del problema; si sigue igual, se rechaza con `kind: plan` y su motivo. |
| PLAN-C10 | Se regenera desde Revisión un recurso que nació de un plan | Lee su ítem del plan y el resumen de los demás recursos del plan, sin crear ni escribir un plan: aunque el plan esté usado, no responde `PLAN_ALREADY_USED`. Si los fragmentos del ítem ya no existen, falla con `PLAN_EVIDENCE_STALE` y el recurso se conserva. |
| PLAN-C11 | Se mide la duplicación con el corpus de T067 antes y después del plan | La duplicación medida con el indicador de REV-P3 baja hasta la meta de [P4](#criterios-de-éxito), sin perder recursos ni `faithfulness`. |

## Historia de revisión del plan en la interfaz

Como docente, quiero revisar el plan en la pantalla de Generación, corregirlo y aprobarlo antes de generar.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| PLAN-C12 | Pido «Planificar» en la pestaña Generación | Veo los ítems agrupados por etapa, con nombre de la etapa, tipo, cantidad, propósito, conceptos propios (editables), conceptos de otros ítems (solo lectura), fragmentos con su texto y los referentes y tipologías anteriores si existen. |
| PLAN-C13 | Edito, apruebo y genero | Puedo editar y guardar el borrador, ver los problemas de validación junto a cada ítem, aprobar y después generar. «Generar» solo se habilita con el plan aprobado. |
| PLAN-C14 | Recargo la pantalla con un plan en borrador | Recupero el último plan de la unidad sin perder mis cambios guardados. |

## Requisitos funcionales

- **PLAN-R1.** Crear el plan con `POST /api/v1/generation-plans`, de forma síncrona y con `Idempotency-Key`. Consultarlo con `GET` (uno o la lista de la unidad), editarlo con `PUT` (con `expectedVersion`) y aprobarlo con `POST …/approve`.
- **PLAN-R2.** El plan congela su evidencia al crearse: cada ítem cita solo fragmentos de esa evidencia, y la generación usa esa misma evidencia, no una búsqueda nueva. Al generar o regenerar, si algún fragmento ya no existe en la unidad, se responde `409 PLAN_EVIDENCE_STALE` ([research R3](research.md#evidencia-vigente-por-qué-rechazar-y-no-volver-a-buscar)).
- **PLAN-R3.** Validar el plan con las reglas de [data-model](data-model.md#reglas-de-validación): todo ítem cita evidencia, ningún concepto pertenece a dos ítems, al menos un ítem, tipos del catálogo y de la modalidad, cantidades dentro de los límites.
- **PLAN-R4.** Armar el plan con una sola llamada a la IA, con esquema de respuesta propio y el límite de 60 s de QA-06. Si falla, armarlo con reglas, de forma determinista, y registrar `fallbackReason`.
- **PLAN-R5.** `POST /api/v1/generation-requests` recibe `planId` y `planVersion` de un plan aprobado. Mientras el frontend no use el plan, el cuerpo anterior sigue aceptándose y el servidor crea un plan implícito aprobado: toda generación tiene plan ([research R2](research.md#r2-el-plan-es-obligatorio-compatibilidad-del-pedido-sin-plan)).
- **PLAN-R6.** Cada recurso se redacta con su ítem y el resumen de lo ya cubierto; se comprueba que desarrolle sus conceptos y no los ajenos; el control de repetición vigente se mantiene.
- **PLAN-R7.** Los tipos de texto nuevos del catálogo (CUR-P2) se redactan con una instrucción genérica a partir de su descripción, con el generador por reglas como respaldo.
- **PLAN-R8.** La interfaz nunca menciona la metodología 5E (ni «5E», ni «modelo 5E», ni «metodología 5E»). Los nombres de las etapas (Enganchar, Explorar, Explicar, Elaborar, Evaluar) sí se muestran. Los mensajes que devuelve la API al docente siguen la misma regla.
- **PLAN-R9.** Aislamiento por docente (Constitución IV): un plan ajeno responde igual que uno inexistente.

## Criterios de éxito

- Verificar PLAN-C1 a PLAN-C15 con resultados observables en API e interfaz y enlazar su evidencia en las tareas.
- **P4.** Con el corpus y los casos de T067 (`backend/evaluation/corpus_t067`), una secuencia de 8 tipos × 2 recursos, la tasa de pares duplicados de una misma generación ([research R7](research.md#r7-medición-de-la-duplicación-p4)) baja al menos a la mitad frente a la generación sin plan y queda en 5 % o menos, sin bajar la cantidad de recursos entregados ni la `faithfulness` media (≥ 0,90).
- Crear un plan con Gemini responde en p95 < 30 s y nunca pasa de 60 s más la recuperación; con reglas, en p95 < 1 s.

## Preguntas abiertas para el profesor

- **P8 · Referentes en la recuperación.** ¿Qué debe cambiar en la recuperación (RAG) con los referentes? Opciones: (a) solo mostrarlos en el plan; (b) agregarlos a la consulta de búsqueda; (c) dar prioridad a los fragmentos que los citan; (d) buscar fuentes externas sobre esos autores, con su licencia. Hasta decidirlo, el plan los muestra y los pasa a la IA como contexto, sin cambiar la búsqueda.
- **P10 · Editor WYSIWYG.** ¿El editor WYSIWYG es para editar el plan, o para editar los recursos antes de exportar a SCORM? Este plan se edita con un formulario estructurado; si P10 es para el plan, cambia GEN-P3.

## Supuestos y dependencias

- Material (MAT-P2) entrega los referentes por un puerto; mientras no exista, la lista queda vacía.
- Cursos (CUR-P3) lee y guarda las tipologías por sesión; mientras no exista, el contexto de sesión queda vacío. Falta acordar qué es una «sesión» del curso ([research R9](research.md#r9-contexto-de-sesión-cur-p3)).
- Cursos (CUR-P2) mantiene el catálogo de tipos; Generación lo lee por un puerto ([research R6](research.md#r6-catálogo-configurable-cur-p2)).
- Revisión (REV-P3) entrega el indicador de duplicación por embeddings.
- QA-16 agrega `POST /api/v1/generation-plans` a sus rutas costosas con límite por IP.
