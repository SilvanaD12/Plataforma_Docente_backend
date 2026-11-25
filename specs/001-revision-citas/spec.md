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
- **REV-R13.** Permitir la edición con formato enriquecido (`bodyHtml`) restringido a etiquetas y atributos seguros (`p`, `br`, `strong`, `b`, `em`, `i`, `u`, `s`, `h1`, `h2`, `h3`, `ul`, `ol`, `li`, `a`, `blockquote`). Si el texto plano normalizado no cambia respecto al guardado, conservar el `body` original para no alterar la huella ni la verificación.
- **REV-R14.** Proveer un endpoint de vista previa para paquetes SCORM que devuelva las páginas HTML construidas en memoria y el desglose de recursos excluidos, reutilizando el filtro de elegibilidad sin registrar descargas en el historial.
- **REV-R15.** Implementar la detección de duplicidad y parafraseo entre recursos de una unidad sin dependencias externas ni modelos de lenguaje, reportando pares que superan el umbral configurado (`REVIEW_DUPLICATE_THRESHOLD`) a nivel de recurso y de pregunta con su puntaje de similitud y tasa de duplicidad.
- **REV-R16.** Cuando se solicite la regeneración de un recurso originado de un plan pedagógico y algún fragmento de su ítem ya no exista en la unidad (se borró o reprocesó un documento), responder con 409 `PLAN_EVIDENCE_STALE` y el detalle estructurado de documentos afectados (`StaleDocument`), manteniendo el recurso y el plan sin modificaciones (T014).
<<<<<<< Updated upstream
=======
- **REV-R17 (REV-P4).** Extender de forma aditiva y retrocompatible el reporte de duplicidad (`GET /api/v1/units/{unit_id}/duplication-report`) mediante el parámetro opcional `includeCourse=true` para comparar también cada recurso y pregunta de la unidad actual contra los recursos y preguntas de las restantes unidades del mismo curso del docente (sin comparar unidades ajenas entre sí). Sin el parámetro, la respuesta conserva exactamente el formato y los pares actuales. Con `includeCourse=true`, los pares entre unidades devuelven `crossUnit: true`, `unitIdB` y `unitTitleB`, mientras los internos llevan `crossUnit: false` y `unitIdB`/`unitTitleB` nulos, ordenados por puntaje descendente y recalculando `comparedPairs` y `duplicatePairRate` sobre el total.
- **REV-R18 (REV-P5).** Reorganizar la presentación de la pestaña Revisión en el frontend agrupando los recursos por estado en secciones plegables con contadores (`Pendientes de revisión`, `Aprobados` y `Descartados`), ordenados por etapa pedagógica y fecha de creación, mediante tarjetas plegables con cabecera resumida, insignia de verificación compacta sin botones anidados, resguardo ante cambios sin guardar al intentar cerrar, transición automática de foco al aprobar o descartar, sección plegable `Fuentes citadas (n)` con fragmentos enlazados y sello `Aprobado el {fecha}` cuando un recurso ya aprobado no presenta ediciones pendientes; además actualizar en Exportación la etiqueta SCORM (`SCORM (Moodle, Chamilo o Canvas)`) y su guía en Moodle, sin modificar el backend ni el contrato de la API.
>>>>>>> Stashed changes

## Cambios solicitados en la asesoría del 21/11

### REV-P1 · Editor de texto enriquecido en la revisión
Como docente, quiero editar el contenido del recurso con formato (negrita, cursiva, subrayado, tachado, títulos, listas, cita y enlaces) y eliminar texto redundante antes de exportar, para que el material pedagógico tenga la presentación adecuada.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C15 | El docente aplica o modifica únicamente el formato (`bodyHtml`) sin alterar el texto verificable (`body`) | La huella (`content_fingerprint`) y el resultado de verificación (`verification`) se conservan sin cambios, sin disparar una nueva evaluación contra la evidencia. |

### REV-P2 · Vista previa y validación del paquete SCORM
Como docente, quiero ver cada página del paquete SCORM tal como saldrá antes de descargarlo, para validar la secuencia y la presentación sin generar un registro en mi historial de descargas.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C16 | El docente solicita la vista previa de exportación SCORM para una unidad con recursos aprobados | El sistema genera las páginas en memoria con su HTML, incrustando estilos, scripts y medios en base64 para su renderizado fiel en iframes aislados (`sandbox="allow-scripts"` sin `allow-same-origin`), y el listado de recursos excluidos con motivos legibles, sin registrar una descarga en el historial. Si no hay recursos elegibles, devuelve 422 `NO_APPROVED_RESOURCES`. |

### REV-P3 · Control de duplicidad entre recursos
Como docente, quiero identificar recursos o preguntas con contenido repetido o parafraseado dentro de la unidad, para evitar redundancias antes de publicar o exportar.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C17 | Se consulta el reporte de duplicidad de una unidad con recursos generados | El sistema compara los textos completos de los recursos y los enunciados de las preguntas mediante raíz ligera (`stem`), similitud combinada de n-gramas de caracteres y Jaccard de palabras; reporta los pares que superan el umbral configurado (`REVIEW_DUPLICATE_THRESHOLD`, por defecto `0.70`) y la tasa de duplicidad (`duplicatePairRate`), como un aviso no bloqueante que no impide la aprobación ni la exportación. |

### T014 · Regeneración con plan y evidencia modificada (GEN-P2)
Como docente, cuando pido regenerar un recurso originado de un plan cuya evidencia ya no existe en la unidad (porque se eliminó o reprocesó un documento), quiero recibir una respuesta clara que indique qué documentos y fragmentos faltan, conservando el recurso actual intacto.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C18 | El docente pide regenerar desde Revisión un recurso originado de un plan y algún fragmento de su ítem ya no existe en la unidad (se borró o reprocesó un documento) | El sistema responde 409 `PLAN_EVIDENCE_STALE` con el detalle de documentos afectados (`details` con `documentId`, `documentName`, `missingFragmentIds`); el recurso previo no se modifica (conserva versión y contenido) y el plan permanece en su estado previo sin alteraciones. |

<<<<<<< Updated upstream
## Criterios de éxito

- Todos los escenarios REV-C1 a REV-C18 pasan en el nivel de prueba que corresponda.
=======
### REV-P4 · Control de duplicidad entre unidades del curso
Como docente, quiero detectar en Revisión si un recurso o pregunta de mi unidad repite o parafrasea contenido ya existente en otras unidades del mismo curso, sin perder la compatibilidad con los reportes por unidad ni bloquear la edición, aprobación o exportación.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C19 | Un curso tiene dos o más unidades con recursos equivalentes o parafraseados y se consulta `GET /api/v1/units/{unit_id}/duplication-report` | Sin `includeCourse=true`, el reporte devuelve solo los pares internos de la unidad actual con los mismos campos de REV-P3. Con `includeCourse=true`, incluye además los pares entre la unidad actual y las demás unidades del curso (`crossUnit: true`, `unitIdB`, `unitTitleB`), ordenados descendentemente y recalculando `comparedPairs` y `duplicatePairRate`; la interfaz los muestra en un bloque informativo separado («Posible contenido repetido en otras unidades») sin bloquear guardado, aprobación ni exportación. Una unidad ajena al docente responde 404. |

### REV-P5 · Secciones por estado, tarjetas plegables y fuentes citadas en Revisión
Como docente, quiero ver los recursos de Revisión agrupados por estado en tarjetas plegables con sus fuentes citadas accesibles, para enfocarme en lo pendiente sin perder los recursos ya decididos ni cambios sin guardar.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C20 | El docente abre la pestaña Revisión con recursos en distintos estados (`pendiente`, `aprobado`, `descartado`) | La barra superior resume `Pendientes (n) · Aprobados (n) · Descartados (n)` y muestra tres secciones plegables con su contador (`Pendientes de revisión` abierta por defecto; `Aprobados` y `Descartados` cerradas), ordenadas internamente por etapa (`Enganchar → Explorar → Explicar → Elaborar → Evaluar`) y fecha de creación. Cada tarjeta muestra cabecera compacta (título, tipo legible, etapa, insignia de verificación sin botón anidado, motivo de descarte si aplica e indicador de cambios sin guardar) y resiste el plegado mientras tenga cambios locales; al abrir `Fuentes citadas (n)` lista los fragmentos citados (ocultando nombres de documento con enciclopedias externas mediante su dominio o `Fuente web`). Al aprobar o descartar, la tarjeta se pliega, cambia de sección y traslada el foco al siguiente pendiente o al aviso «Todo revisado. Ya puedes ir a Exportación.»; un recurso aprobado sin cambios pendientes muestra `Aprobado el {fecha}` en lugar del botón `Aprobar`. |

## Criterios de éxito

- Todos los escenarios REV-C1 a REV-C20 pasan en el nivel de prueba que corresponda.
>>>>>>> Stashed changes
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

## Historias del Sprint 1

Cierre y evidencias de las historias y tareas asociadas al módulo de Revisión y Exportación (REV-01) en el Sprint 1:

### HU-043 · Exportación a Moodle XML
- **Estado:** Hecha.
- **Alcance comprobado:** Exportación de ítems de opción múltiple con enunciado, distractores calificados (fracciones 100 % en la respuesta correcta y 0 % en las erróneas), retroalimentación específica y general («Para repasar…»), categorización `$course$/top/...` y penalización.
- **Entorno de prueba:** Moodle 5.3.1 (Build: 20261112), `sandbox.moodledemo.net`.
- **Evidencias en el repositorio (`docs/evidence/HU-043/`):**
  - Archivo XML exportado y validado: [hu043-20261112230327-moodle.xml](../../docs/evidence/HU-043/hu043-20261112230327-moodle.xml).
  - Captura del formulario de importación: [hu043-b01-formulario-con-xml.png](../../docs/evidence/HU-043/hu043-b01-formulario-con-xml.png).
  - Captura del resultado exitoso («Importing 1 questions from file»): [hu043-b02-resultado-importacion.png](../../docs/evidence/HU-043/hu043-b02-resultado-importacion.png).
  - Capturas de la categoría en el banco: [hu043-b03-selector-de-categorias.png](../../docs/evidence/HU-043/hu043-b03-selector-de-categorias.png) y [hu043-b03-pregunta-en-categoria.png](../../docs/evidence/HU-043/hu043-b03-pregunta-en-categoria.png).
  - Capturas de la vista previa interactiva respondida:
    - Distractor incorrecto con su retroalimentación: [hu043-b04-respuesta-incorrecta-udp.png](../../docs/evidence/HU-043/hu043-b04-respuesta-incorrecta-udp.png).
    - Opción correcta con su retroalimentación: [hu043-b05-respuesta-correcta.png](../../docs/evidence/HU-043/hu043-b05-respuesta-correcta.png).

### HU-009 · Orden de la secuencia 5E en el paquete SCORM 1.2
- **Estado:** Hecha.
- **Alcance comprobado:** En un paquete SCORM exportado a partir de una secuencia de las 5 etapas (Enganchar, Explorar, Explicar, Elaborar y Evaluar), el manifiesto `imsmanifest.xml` organiza los elementos en el orden pedagógico estricto: `engage` → `explore` → `explain` → `elaborate` → `evaluate`. Cada elemento apunta a un recurso SCO con su archivo correspondiente presente en el paquete ZIP, llamando a la API SCORM (`LMSInitialize` y `LMSFinish`).
- **Prueba automatizada:** fijada en `tests/unit/test_scorm_package_exporter.py::test_manifest_orders_all_five_5e_stages_correctly`, que verifica la ordenación incluso si los recursos se entregan desordenados.
- **Evidencia en el repositorio (`docs/evidence/HU-009/`):**
  - Paquete SCORM generado con secuencia 5E completa: [hu009-scorm-5e-sequence.zip](../../docs/evidence/HU-009/hu009-scorm-5e-sequence.zip) (5 SCOs en orden: `¿Qué sabes sobre capa de transporte?`, `Guía de exploración...`, `Capa de transporte: explicación...`, `Ejercicio de aplicación...`, `Evaluación por niveles`).

### HU-008 · Compatibilidad con LMS Chamilo (SCORM 1.2)
- **Estado:** Comprobada en Chamilo (importación y navegación de lección verificadas; evaluación por niveles pendiente de responder).
- **Alcance comprobado:** Exportación de paquete SCORM 1.2 e importación en Chamilo. La lección se crea con los 5 elementos en orden; los elementos se abren con contenido, estilos y fuentes, y la API SCORM responde registrando el avance del estudiante.
- **Entorno de prueba:** Campus Chamilo (`campus.chamilo.net`, Open Campus v2), cuenta de profesor de Juan, curso «HU-008 SCORM».
- **Evidencias en el repositorio (`docs/evidence/HU-008/`):**
  - Paquete SCORM probado: [hu008-20261113061913-scorm.zip](../../docs/evidence/HU-008/hu008-20261113061913-scorm.zip).
  - Capturas de la importación y navegación:
    - Curso del profesor: [hu008-00-curso-profesor.png](../../docs/evidence/HU-008/hu008-00-curso-profesor.png).
    - Formulario de importación de lección: [hu008-01-importar-zip.png](../../docs/evidence/HU-008/hu008-01-importar-zip.png).
    - Lección importada en el listado: [hu008-02-leccion-importada.png](../../docs/evidence/HU-008/hu008-02-leccion-importada.png).
    - Elemento 1 (Enganchar) abierto con avance registrado: [hu008-03-indice-y-recurso-1.png](../../docs/evidence/HU-008/hu008-03-indice-y-recurso-1.png).
    - Elemento 3 (Explicar) con estilos y avance registrado: [hu008-04-recurso-3.png](../../docs/evidence/HU-008/hu008-04-recurso-3.png).

### TA-006 · Matriz de compatibilidad de exportaciones
- La matriz completa de compatibilidad por LMS y formato se encuentra documentada en [docs/compatibility/TA-006-matriz.md](../../docs/compatibility/TA-006-matriz.md).
