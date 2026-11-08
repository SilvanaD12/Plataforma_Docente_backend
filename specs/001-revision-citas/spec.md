# Revisión y citas

**Ficha** REV-01 · RN-004 P01 y HU-016  
**Responsable** Juan  
**Fuente** Especificaciones de Plataforma 5E, versión 0.4

## Historia de usuario y escenarios de prueba

### Historia 1. Editar un recurso sin perder el control del respaldo
Como docente, quiero saber si las fuentes siguen respaldando el contenido que guardé para poder aprobar una versión verificada.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| REV-C1 | Se guarda un cambio en una afirmación respaldada | Se comprueba al guardar contra la evidencia histórica y se registra el resultado para la versión editada. Un recurso previamente aprobado vuelve a revisión y requiere una nueva aprobación manual. |
| REV-C2 | Se modifica solo el formato o el orden de alternativas con identificadores estables | La comprobación se conserva. Cambiar la respuesta correcta sí activa una nueva evaluación. |
| REV-C3 | El respaldo es insuficiente o la comprobación no pudo completarse | Se muestra el estado y su motivo. Se bloquean la aprobación y las exportaciones nuevas. El docente puede corregir el texto o regenerar el recurso. |
| REV-C4 | Se modifica el texto de un distractor | Se evalúa su fiabilidad y se señala si la evidencia lo hace defendible. Cambiar solo su decisión de revisión aplica las reglas de aprobación vigentes. |
| REV-C5 | Llega un resultado de verificación de una versión anterior | Ese resultado no habilita la aprobación de la versión actual. |
| REV-C6 | Se reprocesa el material original | La evidencia histórica permanece vinculada. Se conserva la comprobación si el contenido y las fuentes vinculadas siguen iguales. |

## Requisitos funcionales

- **REV-R1.** Detectar cambios en contenido verificable, incluidos el enunciado, cuerpo, explicaciones, respuesta correcta, distractores y afirmaciones de campos estructurados.
- **REV-R2.** Distinguir cambios de contenido de cambios visuales, espacios equivalentes, metadatos internos y reordenamiento con identificadores estables.
- **REV-R3.** Verificar localmente al guardar contra la evidencia histórica disponible. Aplicar la regla de fiabilidad a los distractores.
- **REV-R4.** Asociar el resultado a la versión de contenido que se verificó. Descartar resultados desactualizados.
- **REV-R5.** Distinguir comprobación vigente, insuficiente y pendiente. Exigir aprobación manual y comprobación vigente para exportaciones nuevas.
- **REV-R6.** Conservar la copia histórica. Si cambian las fuentes vinculadas, comprobar nuevamente el respaldo.

## Criterios de éxito

- Todos los escenarios REV-C1 a REV-C6 pasan en el nivel de prueba que corresponda.
- La API y el recorrido de interfaz demuestran que un recurso pendiente o insuficiente queda fuera de nuevas exportaciones.

## Alcance y decisiones de diseño

Buscar fuentes nuevas desde la edición queda fuera de esta entrega. En el plan se concreta la huella del contenido normalizado y el tratamiento de los recursos antiguos que ya estaban aprobados sin huella. Una nueva aprobación debe poder comprobar la vigencia del respaldo.
