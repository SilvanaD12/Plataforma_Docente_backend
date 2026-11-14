# Generación individual y secuencia 5E

**Ficha** GEN-01 · HU-003 · HU-024

**Responsable** Yan

**Estado** En revisión

**Referencias** [Constitución de Plataforma 5E](../../.specify/memory/constitution.md), [OpenAPI](../../docs/api/openapi.json), [Revisión y Exportación](../001-revision-citas/spec.md) y [Cuentas y Cursos](../003-cuentas-y-cursos/spec.md).

## Objetivo y alcance

Permitir que un docente pida recursos para una unidad en modo individual o como secuencia 5E. Ambos modos usan el mismo pedido en segundo plano, con clave estable del cliente, estado consultable y recuperación tras una interrupción. Cada secuencia usa una cantidad común por tipo. El módulo incluye el catálogo de tipos, los agentes por etapa y la verificación de evidencia al crear cada recurso. El lote independiente y las cantidades distintas por tipo quedan para una entrega posterior.

HU-024 agrega la modalidad del pedido: Textual, Gamificado, Multimedia o Kinestésico. Una modalidad es un grupo de tipos de recurso, no un modo distinto de generar. El Project Charter dejaba el audio fuera del alcance; HU-024 y HU-056 incorporan la imagen y el audio.

## Historia de pedido y recuperación

Como docente, quiero distinguir la generación individual de una secuencia 5E y recuperar un pedido tras una interrupción.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| GEN-C1 | Pido un tipo en modo individual | El recurso se verifica antes de entregarse y pasa a revisión como vigente o pendiente. |
| GEN-C2 | Pido una secuencia con Enganchar y Evaluar | El pedido se ejecuta en segundo plano. Los pasos aparecen en orden 5E, usan evidencia compartida y muestran el estado informado por el servidor. |
| GEN-C3 | Un paso se rechaza y otro termina | Se conserva lo válido para revisión y se muestra el motivo del rechazo. |
| GEN-C4 | Se interrumpe la conexión o recargo la pantalla | Puedo recuperar el pedido. Reenviar la misma clave con los mismos datos no duplica recursos. |
| GEN-C5 | Otro docente consulta el pedido o se reutiliza la clave con otros datos | La consulta ajena se rechaza y la reutilización con otros datos produce un conflicto. |
| GEN-C6 | Falta material procesado o fallan todos los pasos | Sin material procesado se rechaza el pedido. Si el pedido fue aceptado y todos los pasos fallan, se informa el motivo y queda consultable el estado final. |

## Historia de evidencia verificada

Como docente, quiero recibir en revisión recursos con su evidencia verificada para saber cuáles puedo aprobar.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| GEN-C7 | Revisión pide regenerar un recurso | Se ejecuta un pedido individual con los parámetros guardados y la evidencia actual. El anterior pasa a Descartados solo si la regeneración termina bien y sigue en la misma versión. Si no, se conserva y decide el docente. |
| GEN-C8 | Un borrador no alcanza el umbral de evidencia, o a un recurso le falta un fragmento referenciado | El borrador bajo el umbral se rechaza con su motivo y no llega a revisión. Si falta un fragmento referenciado o la verificación no puede completarse, el recurso llega a revisión como pendiente y no puede aprobarse ni exportarse, también si lo redactó el generador por reglas. |
| GEN-C9 | La búsqueda híbrida no está disponible | Material responde con `retrieval_mode` igual a `bm25_fallback`. El resultado distingue ese respaldo de búsqueda del respaldo de redacción por reglas. |

## Historia de modalidad

Como docente, quiero elegir la modalidad antes de generar para recibir solo los tipos de recurso que corresponden a la clase que preparo (HU-024).

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| GEN-C10 | Elijo una modalidad y pido recursos | Solo se ofrecen los tipos de esa modalidad. Si el pedido incluye un tipo que no pertenece a ella, se rechaza con `RESOURCE_TYPE_NOT_IN_MODALITY` antes de crearse. El pedido y sus recursos guardan la modalidad elegida. |
| GEN-C11 | Pido una actividad kinestésica | El recurso trae al menos 3 pasos con instrucción y pregunta, cada uno con su cita al material, y además materiales, tiempo estimado y espacio. Solo los pasos se verifican contra el material. Si la IA falla, la redacta el generador por reglas. |

## Interpretación de pedidos (HU-038)

Como docente, quiero describir con mis propias palabras los recursos que necesito y corregir el pedido interpretado antes de generar.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| GEN-C12 | Describo uno o más recursos desde la pestaña Generación | El chat muestra la unidad activa, los tipos reconocidos en orden 5E y sin repetirlos, sus etapas de solo lectura, la cantidad y los demás parámetros interpretados. Señala los valores faltantes, ambiguos o no permitidos. Puedo corregir el borrador en el formulario existente. El pedido solo se crea cuando confirmo con «Generar». |

## Requisitos funcionales

- **GEN-R1.** Ofrecer modos explícitos de generación individual y secuencia 5E. Ambos usan el mismo mecanismo de pedido en segundo plano.
- **GEN-R2.** Ordenar por etapa, compartir evidencia y aplicar el control de repetición vigente. Usar una cantidad común por tipo. Como punto de partida se conservan hasta ocho tipos distintos y de uno a cinco recursos por tipo, sujetos a validar la carga en el plan.
- **GEN-R3.** Ejecutar el pedido en segundo plano, devolver un identificador y exponer el estado y los resultados por paso. La interfaz muestra el progreso confirmado por el servidor.
- **GEN-R4.** Verificar todos los recursos antes de entregarlos, incluidos los del generador por reglas, y enviarlos a revisión como vigentes o pendientes. Un recurso pendiente no puede aprobarse ni exportarse. Informar rechazos y distinguir el respaldo de búsqueda (`retrieval_mode`) del respaldo de redacción por reglas.
- **GEN-R5.** Recibir una clave estable del cliente y asociarla al pedido del docente. Permitir recuperar ese pedido y reenviar la misma solicitud sin duplicar resultados. Rechazar el uso de la clave con datos distintos.
- **GEN-R6.** Regenerar un recurso a pedido de Revisión con su identificador y versión. Ejecutar un pedido individual con los parámetros guardados y la evidencia actual del material, no con la copia histórica. El recurso anterior pasa a Descartados solo si la regeneración termina bien y sigue en la misma versión (REV-C14).
- **GEN-R7.** Guardar en cada recurso la huella de contenido, calculada con la función compartida `domain/review/content_fingerprint.py`, y el resultado de verificación: estado, `evidenceThreshold` del pedido, `VERIFICATION_RULE_VERSION` y resumen. Sin ediciones, ese resultado no se recalcula.
- **GEN-R8.** Guardar la copia histórica de todos los fragmentos referenciados por citas, alternativas y elementos de estructura (pasos, predicciones y criterios): id, texto, ubicación, `documentId`, `documentName`, `sourceUrl`, licencia y fecha de recuperación. Si falta alguno, el recurso queda pendiente.
- **GEN-R9.** Ofrecer cuatro modalidades: Textual, Gamificado, Multimedia y Kinestésico. Cada una es un grupo de tipos de recurso; todo tipo pertenece al menos a una, y puede estar en más de una. El catálogo de tipos informa las modalidades de cada tipo. Un pedido admite una sola modalidad. Si la envía, todos sus tipos deben pertenecer a ella; si no la envía, no se filtran los tipos y el pedido se guarda sin modalidad. La modalidad elegida se guarda en el pedido y en los parámetros de cada recurso. La regeneración no comprueba la modalidad.
- **GEN-R10.** Agregar el tipo actividad kinestésica a la etapa Explorar: pasos guiados con la misma forma que la exploración guiada (mínimo 3, cada uno con sus fragmentos), más materiales, tiempo estimado y espacio. Solo los pasos se verifican contra el material; materiales, tiempo y espacio forman parte de la huella. Tiene un redactor del generador por reglas.

- **GEN-R11.** Interpretar el mensaje del docente mediante reglas deterministas y devolver un borrador editable para la unidad activa. Comprobar la pertenencia de la unidad antes de interpretar y aplicar las reglas del catálogo. La interpretación funciona con independencia del procesamiento de documentos, la recuperación de evidencia y la generación de recursos.

## Criterios de éxito

- Verificar los casos GEN-C1 a GEN-C12 con resultados observables en API e interfaz y enlazar su evidencia en las tareas.
- Validar el orden de etapas, la recuperación tras una desconexión y la conservación de resultados parciales.
- Comprobar que repetir un pedido con los mismos datos no duplica recursos y que otro docente no puede consultarlo.
- Comprobar que los recursos vigentes llegan a revisión con huella, resultado de verificación y copia histórica completa, y que los pendientes pueden llegar con el motivo registrado, pero no pueden aprobarse ni exportarse.
- Comprobar que una regeneración fallida, o sobre una versión que ya cambió, no descarta el recurso anterior.
- Comprobar un pedido por modalidad, el rechazo de un tipo que no pertenece a la modalidad elegida y la exportación de una actividad kinestésica.

- Para GEN-C12, interpretar «Para TCP/IP, quiero dos glosarios» desde la unidad TCP/IP y mostrar la etapa Explicar, el tipo Glosario y la cantidad 2. Cambiar la cantidad a 1 y comprobar que se crea un único pedido, con cantidad 1, al pulsar «Generar».

## Dependencias con otros módulos

| Módulo | Acuerdo |
| --- | --- |
| CC-01 · Cuentas y Cursos | Generación consulta el puerto de pertenencia antes de aceptar un pedido. Una unidad ajena o inexistente se rechaza sin revelar sus datos. |
| MAT-01 · Material y Evidencia | Entrada: `query`, `teacher_id`, `unit_id` y `limit`, solo con material listo. Salida por fragmento: `chunk_id`, `document_id`, `documentName`, `location`, `text` y `relevance` de 0 a 1, más `retrieval_mode`. Generación recupera una vez y comparte la evidencia entre etapas. La procedencia para la copia histórica (URL, licencia y fecha) se fija en el plan. |
| REV-01 · Revisión y Exportación | Revisión mantiene `content_fingerprint.py`. Generación mantiene `grounding.py`, `distractor_reliability.py`, `resource_catalog.py`, `resource_formats.py` y `VERIFICATION_RULE_VERSION`, que sube cuando cambia un mínimo por tipo. Los estados son vigente, insuficiente y pendiente. Los recursos antiguos sin evidencia quedan pendientes y solo se regeneran (REV-R11). Para HU-024, Revisión verifica los pasos de la actividad kinestésica, incluye materiales, tiempo y espacio en la huella y la exporta. En el sprint 2, REV-01 decide qué cuenta como elección explícita de Textual (Textual viene preseleccionado en el formulario); hasta entonces, todos los ítems de opción múltiple van a la evaluación por niveles ([research R11](research.md#r11-modalidades-hu-024)). |

## Alcance y decisiones de diseño

El lote independiente y las cantidades distintas por tipo quedan fuera de esta entrega. El plan debe concretar el contrato de inicio y consulta en OpenAPI, el alcance de la clave por docente, el almacenamiento del estado, los límites de carga y qué ocurre si el recurso se edita durante una regeneración. Si el servidor se reinicia, los pedidos en curso se marcan como interrumpidos y se conservan los recursos ya generados.

Para HU-024 quedan fuera de esta entrega: exportar a Moodle XML otros tipos además del ítem de opción múltiple (verdadero o falso y relacionar, en el sprint 2, a cargo de REV-01) y verificar el guion de audio oración por oración (tarea aparte de REV-01 para el sprint 2, que sube `VERIFICATION_RULE_VERSION`).
