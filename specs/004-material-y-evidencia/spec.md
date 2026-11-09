# Material y Evidencia

**Ficha** MAT-01
**Responsable** Sergio Celi
**Estado** En revisión
**Fuente** Especificaciones de Plataforma 5E, versión 0.4

## Objetivo y alcance

Entregar la carga, el procesamiento y la recuperación de evidencia (PDF o TXT) con aislamiento estricto por docente y unidad. Se incluye la extracción de texto, fragmentación y generación de embeddings usando PostgreSQL y pgvector para el adaptador híbrido.

## Historia de usuario y escenarios de prueba

### Historia 1. Cargar, procesar y recuperar evidencia con aislamiento

Como docente, quiero cargar documentos en mis unidades y que el sistema los procese y recupere sin mezclar mi información con la de otros, garantizando una respuesta de búsqueda incluso si la base de datos se demora.

| Caso   | Dado y cuando                                                                             | Entonces                                                                                                                              |
| ------ | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| MAT-C1 | Se carga un archivo válido (PDF o TXT)                                                   | El sistema acepta el archivo, valida la unidad (puerto de Cuentas) y lo procesa.                                                      |
| MAT-C2 | Se intenta cargar un archivo en una unidad ajena real o en una unidad inexistente         | El sistema devuelve el mismo error 404 Not Found en ambos casos (para no revelar información) y no guarda ningún material en la BD. |
| MAT-C3 | Se buscan datos teniendo dos docentes con texto parecido o dos unidades del mismo docente | La recuperación (vectorial y BM25) aísla los resultados aplicando `teacher_id` y `unit_id`.                                     |
| MAT-C4 | Se agota el timeout en la búsqueda semántica o se agota la cuota                        | El adaptador devuelve `bm25_fallback` cancelando tareas pendientes sin bloquear el retorno.                                         |
| MAT-C5 | Se reprocesa un material existente                                                        | Se actualiza el índice para peticiones nuevas, dejando la copia histórica de Generación intacta.                                   |
| MAT-C6 | Se borra un curso desde el módulo de Cuentas (Integración Silvana)                      | No quedan fragmentos ni vectores huérfanos asociados a ese curso en la base de datos.                                                |

## Requisitos funcionales

- **Validación**: Conectar el `UnitMembershipPort` (reutilizado de Generación) llamando a `get_unit_context(teacher_id, unit_id)`. Se usará la lista de `outcomes` recibida (id, code, text) para validar los `outcomeIds` asociados al archivo antes de procesarlo.
- **Procesamiento**: Excluir de la recuperación cualquier documento sin estado "listo".
- **Contrato Yan**: El puerto recibe `query`, `teacher_id`, `unit_id` y `limit`; devuelve fragmentos con IDs, nombre, ubicación, texto, relevancia (0 a 1) y modo de recuperación.
- **Métricas**: La integración vectorial debe alcanzar un Recall@10 ≥ 0.80.

## Decisiones técnicas (Arquitectura)

- **Estrategia de fragmentación**: Se utilizarán fragmentos de 512 tokens con 50 de solapamiento (overlap), optimizado para el modelo `multilingual-e5-base`.
- **Límite de Timeout**: Se establece un límite duro de 1500ms (1.5 segundos) para la consulta vectorial en PostgreSQL antes de hacer fallback a BM25.
