# Generación individual y secuencia 5E

**Ficha** GEN-01 · HU-003  
**Responsable** Yan  
**Fuente** Especificaciones de Plataforma 5E, versión 0.4

## Historia de usuario y escenarios de prueba

### Historia 1. Pedir recursos y recuperar su resultado
Como docente, quiero distinguir la generación individual de una secuencia 5E, y recuperar el resultado de un pedido tras una interrupción.

| Caso | Dado y cuando | Entonces |
|---|---|---|
| GEN-C1 | Se pide un tipo en modo individual | Los recursos válidos pasan a revisión. |
| GEN-C2 | Se solicita una secuencia con Enganchar y Evaluar | El pedido se ejecuta en segundo plano. Los pasos aparecen en orden 5E, usan evidencia compartida y muestran el estado informado por el servidor. |
| GEN-C3 | Un paso se rechaza y otro termina | Se conserva lo válido para revisión y se muestra el motivo del rechazo. |
| GEN-C4 | Se interrumpe la conexión o se recarga la pantalla | El docente puede recuperar el pedido. Reenviar la misma clave con los mismos datos no duplica recursos. |
| GEN-C5 | Otro docente consulta el pedido o se reutiliza la clave con otros datos | La consulta ajena se rechaza y la reutilización con otros datos produce un conflicto. |
| GEN-C6 | Falta material procesado o fallan todos los pasos | Se informa el motivo. Si el pedido ya fue aceptado y todos los pasos fallan, su estado final queda consultable. |

## Requisitos funcionales

- **GEN-R1.** Ofrecer modos explícitos de generación individual y secuencia 5E.
- **GEN-R2.** Ordenar por etapa, compartir evidencia y aplicar el control de repetición vigente. Usar una cantidad común por tipo. Como punto de partida se conservan hasta ocho tipos distintos y de uno a cinco recursos por tipo, sujetos a validar la carga en el plan.
- **GEN-R3.** Ejecutar la secuencia en segundo plano, devolver un identificador y exponer el estado y los resultados por paso. La interfaz muestra el progreso confirmado por el servidor.
- **GEN-R4.** Enviar los recursos válidos a revisión. Informar rechazos y distinguir los respaldos de búsqueda y de redacción cuando correspondan.
- **GEN-R5.** Recibir una clave estable del cliente y asociarla al pedido del docente. Permitir recuperar ese pedido y reenviar la misma solicitud sin duplicar resultados. Rechazar el uso de la clave con datos distintos.

## Criterios de éxito

- Los escenarios GEN-C1 a GEN-C6 pasan con resultados observables en API e interfaz.
- Una desconexión simulada permite recuperar el pedido y sus recursos sin duplicados.

## Alcance y decisiones de diseño

El lote independiente y las cantidades distintas por tipo quedan fuera de esta entrega. El plan debe concretar el contrato de inicio y consulta, el almacenamiento del estado, la recuperación tras un reinicio y los límites de carga.
