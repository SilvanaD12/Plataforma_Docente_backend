# Revisión y exportación

**Ficha** REV-01 · RN-004 P01 y HU-016  
**Responsable** Juan  
**Estado** Borrador con acuerdos del equipo (8 de noviembre de 2026)  
**Fuente** Especificaciones de Plataforma 5E, versión 0.4, y acuerdos con Generación (GEN-01) y Cuentas y cursos (CC-01)

## Objetivo y alcance

Revalidar al guardar contra la evidencia histórica y exigir aprobación manual cuando cambie contenido respaldado. La comprobación vigente es condición para exportar. El módulo también cubre la exportación a Moodle XML, SCORM y documento de unidad, el historial de descargas y la invalidación de archivos multimedia editados.

## Clarificaciones

### Sesión 2026-11-08

- P: ¿Cómo se tratan al migrar los recursos antiguos que no tienen huella? → R: Al migrar se calcula su huella. Una copia antigua cuenta como evidencia estructurada si cada fragmento que el recurso referencia tiene su texto en la copia; si falta la fecha de recuperación, se registra como desconocida. Con evidencia estructurada se ejecuta la comprobación local con el `evidenceThreshold` guardado, si existe, o con `DEFAULT_THRESHOLD`. El resultado queda registrado como cualquier otro. Los aprobados con resultado vigente siguen aprobados. Si el resultado es insuficiente o pendiente, vuelven a revisión. Solo los recursos sin copia histórica o con algún fragmento referenciado sin texto en la copia quedan pendientes y fuera de exportación, y su única salida es regenerarlos (confirmado por Sergio).
- P: ¿Dónde se decide qué campos de cada tipo de recurso entran en la normalización y la huella? → R: Se definen en el plan revisando `docs/api/contracts/resource-*.v1.json`.
- P: ¿Está confirmado el contenido de la copia histórica que entrega Material y evidencia (MAT-01)? → R: Sí, acordado con Sergio y Yan. Generación la guarda al crear el recurso con todos los fragmentos que referencia. Cada fragmento guarda su identificador, texto, ubicación, identificador y nombre del documento, URL de origen, licencia y fecha de recuperación. El reproceso del material no la modifica (MAT-C5).
- P: Si la comprobación no se pudo completar y el recurso queda pendiente, ¿cómo sale de ese estado sin cambiar el texto? → R: Con un reintento manual. El docente pide «Reintentar comprobación» desde Revisión y se verifica la misma versión con la regla vigente y el `evidenceThreshold` guardado en el resultado de verificación del recurso, usando solo la copia histórica guardada en el recurso y sin consultar servicios externos. Si el recurso no tiene copia histórica o falta en ella algún fragmento que el recurso referencia, el reintento no se ofrece y la pantalla indica que debe regenerarse el recurso.
- P: Si el mismo recurso se guarda dos veces casi a la vez, ¿qué pasa con el segundo guardado? → R: Se rechaza con un conflicto si parte de una versión anterior a la vigente, y el docente debe recargar.
- P: ¿Qué significa que el archivo multimedia «pasa a respaldo» cuando cambia su `prompt` o su `script` (REV-C8)? → R: El archivo generado deja de usarse. Se muestra la descripción de la imagen o se lee el guion con la voz del navegador, y la aprobación se bloquea hasta generar el archivo de nuevo. Si cambian solo `alt` o `caption`, el archivo se conserva.

## Historias de usuario y escenarios de prueba

### Historia 1. Editar un recurso sin perder el control del respaldo
Como docente, quiero saber si las fuentes siguen respaldando el contenido que guardé para poder aprobar una versión verificada.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C1 | Se guarda un cambio en una afirmación respaldada | Se comprueba al guardar contra la evidencia histórica, con el umbral registrado en el resultado de verificación del recurso, y se registra el resultado para la versión editada. Un recurso previamente aprobado vuelve a revisión y requiere una nueva aprobación manual. |
| REV-C2 | Se modifica solo el formato o el orden de alternativas con identificadores estables | La huella y la comprobación se conservan. Cambiar la respuesta correcta sí activa una nueva evaluación. |
| REV-C3 | El respaldo es insuficiente o la comprobación no pudo completarse | Se muestra el estado y su motivo. Se bloquean la aprobación y las exportaciones nuevas. El docente puede corregir el texto o regenerar el recurso. Si la comprobación no pudo completarse, también puede pedir «Reintentar comprobación», que verifica la misma versión con la regla vigente y el `evidenceThreshold` guardado en el resultado de verificación del recurso. El reintento usa solo la copia histórica guardada en el recurso y no consulta servicios externos. Si el recurso no tiene copia histórica o falta en ella algún fragmento que el recurso referencia, el reintento no se ofrece y la pantalla indica que debe regenerarse el recurso. |
| REV-C4 | Se modifica el texto de un distractor | Se evalúa su fiabilidad y se señala si la evidencia lo hace defendible. Cambiar solo su decisión de revisión aplica las reglas de aprobación vigentes. |
| REV-C5 | Llega un resultado de verificación de una versión anterior | Ese resultado no habilita la aprobación de la versión actual. |
| REV-C6 | Se reprocesa el material original | La evidencia histórica permanece vinculada. Se conserva la comprobación si el contenido y las fuentes vinculadas siguen iguales. |
| REV-C10 | Cambia la regla de verificación en el código y el recurso no se edita | El recurso conserva su estado y sigue exportable. Si después se edita, se verifica con la regla vigente y, si el resultado cambia, el motivo indica que la regla es otra. |
| REV-C11 | Generación entrega un recurso cuya verificación no se pudo completar, incluso con la redacción por reglas, o un recurso que referencia un fragmento que falta en su copia histórica | El recurso llega a Revisión como pendiente y no se puede aprobar ni exportar mientras siga así. |
| REV-C14 | Se guarda un recurso a partir de una versión que ya no es la vigente, por ejemplo desde otra pestaña | El guardado se rechaza con un conflicto, no se modifica la versión vigente ni su verificación, y se pide al docente recargar el recurso. |

### Historia 2. Regenerar un recurso sin perder el anterior
Como docente, quiero regenerar un recurso cuyo respaldo es insuficiente sin perder la versión que tenía si la regeneración falla.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C12 | El docente pide regenerar un recurso desde Revisión y la regeneración termina bien | El recurso nuevo queda para revisión con su huella y su verificación. Al pedir la regeneración se registra la versión del recurso anterior. Si sigue en esa versión, pasa a Descartados con el motivo «regenerado». Si el docente lo editó mientras tanto, no se descarta y ambos quedan en Revisión para que el docente decida. |
| REV-C13 | La regeneración falla | El recurso anterior queda como estaba y se informa el motivo. |

### Historia 3. Exportar solo lo verificado y consultar lo descargado
Como docente, quiero que mis descargas incluyan solo recursos aprobados y verificados, y poder consultar después qué descargué.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C7 | Una nueva exportación incluye recursos con distintos estados de revisión | El archivo incluye solo los recursos aprobados, con comprobación vigente y compatibles con el formato. Si ninguno cumple, se informa el motivo y no se genera el archivo. |
| REV-C8 | Se edita un recurso con imagen o audio ya generado | Si cambia el `prompt` normalizado de una imagen o el `script` normalizado de un audio, el archivo generado deja de usarse: se muestra la descripción de la imagen o se lee el guion con la voz del navegador. La aprobación se bloquea hasta generar el archivo de nuevo. Si cambian solo `alt` o `caption`, el archivo se conserva. |
| REV-C9 | El docente elimina un curso con descargas registradas | El docente sigue viendo en su historial la fecha, el formato, el nombre del archivo, el curso y la unidad. Volver a descargar el archivo queda fuera de esta entrega. Se conserva solo el registro, no el archivo exportado. |

## Requisitos funcionales

- **REV-R1.** Detectar cambios en contenido verificable, incluidos el enunciado, el cuerpo, las explicaciones, la respuesta correcta, los distractores y las afirmaciones de campos estructurados.
- **REV-R2.** Distinguir cambios de contenido de cambios visuales, espacios equivalentes, metadatos internos y reordenamiento con identificadores estables. La huella y la normalización por tipo viven en una función de dominio compartida, `domain/review/content_fingerprint.py`, cuyo responsable es Revisión. Generación la usa al crear y Revisión al guardar.
- **REV-R3.** Verificar localmente al guardar contra la evidencia histórica disponible, con las funciones de `domain/generation/grounding.py` y el umbral registrado en el resultado de verificación del recurso. Aplicar la regla de fiabilidad a los distractores. La comprobación al guardar usa la copia histórica guardada en el recurso y no consulta servicios externos.
- **REV-R4.** Asociar el resultado a la versión de contenido que se verificó. El resultado guarda la huella, el `evidenceThreshold` del pedido y la versión de la regla de verificación. Descartar resultados desactualizados. Sin edición, el resultado guardado no se recalcula.
- **REV-R5.** Distinguir comprobación vigente, insuficiente y pendiente. Exigir aprobación manual y comprobación vigente para exportaciones nuevas. Un recurso que llega pendiente desde Generación se trata igual que uno editado sin verificar. Un recurso pendiente admite un reintento manual de la comprobación, «Reintentar comprobación», sobre la misma versión y sin edición. El reintento usa la regla vigente y el `evidenceThreshold` guardado en el resultado de verificación del recurso. «Reintentar comprobación» usa solo la copia histórica guardada en el recurso y no consulta servicios externos. Si el recurso no tiene copia histórica o falta en ella algún fragmento que el recurso referencia, el reintento no se ofrece y la pantalla indica que debe regenerarse el recurso.
- **REV-R6.** Conservar la copia histórica. Si cambian las fuentes vinculadas, es decir, los `fragmentIds` que referencia el recurso, comprobar nuevamente el respaldo. Si algún fragmento que el recurso referencia no está en la copia, el recurso no puede quedar vigente y queda pendiente.
- **REV-R7.** Aplicar el mismo criterio de elegibilidad en el backend para las nuevas exportaciones a Moodle XML, SCORM y documento de unidad.
- **REV-R8.** Invalidar el archivo multimedia solo cuando cambie el campo con que se generó: el `prompt` normalizado de una imagen o el `script` normalizado de un audio. Mientras no se genere de nuevo, se muestra la descripción de la imagen o se lee el guion con la voz del navegador, y la aprobación queda bloqueada.
- **REV-R9.** Registrar cada descarga con fecha, formato, nombre del archivo y los nombres del curso y la unidad. Permitir consultar el historial por docente, de modo que se conserve al eliminar el curso. Se conserva solo el registro, no el archivo exportado.
- **REV-R10.** Pedir la regeneración a Generación con el identificador y la versión del recurso. Pasar el anterior a Descartados solo si la regeneración termina bien y el recurso sigue en la versión registrada.
- **REV-R11.** Al migrar, calcular la huella de cada recurso antiguo que no la tenga. Una copia antigua cuenta como evidencia estructurada si cada fragmento que el recurso referencia tiene su texto en la copia. La falta de fecha de recuperación no la invalida: al migrar, esa fecha se registra como desconocida. Si el recurso tiene evidencia estructurada, ejecutar la comprobación local con el `evidenceThreshold` guardado, si existe, o con `DEFAULT_THRESHOLD` en caso contrario. Registrar el resultado como cualquier otro. Los recursos aprobados con resultado vigente siguen aprobados. Si el resultado es insuficiente o pendiente, vuelven a revisión. Solo los recursos sin copia histórica o con algún fragmento referenciado sin texto en la copia quedan pendientes y fuera de exportación, y su única salida es regenerarlos (confirmado por Sergio).
- **REV-R12.** Cada guardado indica la versión de contenido de la que parte. Si no coincide con la vigente, rechazarlo con un conflicto sin modificar el recurso ni su verificación.

## Criterios de éxito

- Todos los escenarios REV-C1 a REV-C14 pasan en el nivel de prueba que corresponda.
- La API y el recorrido de interfaz demuestran que un recurso pendiente o insuficiente queda fuera de nuevas exportaciones. El archivo final excluye esos recursos.
- Las pruebas existentes de multimedia editada, historial de descargas y exportadores siguen pasando con las reglas nuevas, salvo `test_edited_media.py::test_editing_the_script_drops_the_old_audio_everywhere`, que se actualiza para exigir el bloqueo de la aprobación de REV-C8.

## Dependencias con otros módulos

- **Generación (GEN-01).** Cada recurso llega con su huella, su resultado de verificación (estado, `evidenceThreshold` del pedido, versión de la regla y resumen de lo verificado, corregido o quitado) y su copia de evidencia. La regeneración se pide con el identificador del recurso (GEN-R6 y GEN-C7), usa la evidencia vigente del material y su estado se consulta como cualquier pedido.
- **Regla de verificación compartida.** El umbral y los mínimos por tipo pertenecen a `grounding.py`, que usan Generación y Revisión. La constante `VERIFICATION_RULE_VERSION` se incrementa cuando cambia algún mínimo.
- **Cuentas y cursos (CC-01).** Al eliminar un curso se eliminan sus unidades, recursos, resultados de verificación y archivos multimedia (`media_assets`). El historial de descargas se conserva.
- **Material y evidencia (MAT-01).** Acordado con Sergio y Yan. Generación guarda la copia histórica al crear el recurso, con todos los fragmentos que el recurso referencia: citas, alternativas y elementos de la estructura, como pasos, predicciones y criterios. Cada fragmento guarda su identificador, texto, ubicación, identificador y nombre del documento, URL de origen, licencia y fecha de recuperación. El reproceso del material no modifica la copia (MAT-C5). Los nombres exactos de los campos se fijan en el contrato OpenAPI del plan.

## Fuera del alcance de esta entrega

- Buscar fuentes nuevas desde la edición.
- Volver a descargar un archivo desde el historial.
- La aprobación masiva («Aceptar todos»).

## Definido en el plan

- Qué campos de cada tipo de recurso entran en la normalización y la huella: decisión D1 de [research.md](research.md#d1-huella-del-contenido-verificable-rev-r1-rev-r2--rev-c2-c4-c5) y la tabla por tipo de [data-model.md](data-model.md#normalización-para-la-huella). Se definen sobre el recurso guardado, porque `docs/api/contracts/resource-*.v1.json` describe otro modelo (hallazgo H11).
- Los nombres de los campos de la copia histórica y del resultado de verificación están en [contracts/review-export.openapi.yaml](contracts/review-export.openapi.yaml). La fecha de recuperación (`retrievedAt`) admite `null`, que significa desconocida, para los recursos migrados.
