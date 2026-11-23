# Material y Evidencia

**Ficha** MAT-01 (Actualizada para Iteración P2: MAT-P1, MAT-P2, MAT-P3)
**Responsable** Sergio Celi
**Estado** En desarrollo (Iteración P2)
**Fuente** Especificaciones de Plataforma 5E, versión 0.4 + Alcance P2 (Pedidos P6, P7, P8)

---

# PARTE I — Entrega Base (MAT-01: Carga, Procesamiento y Recuperación Híbrida)

## Objetivo y alcance (Base)

Entregar la carga, el procesamiento y la recuperación de evidencia (PDF o TXT) con aislamiento estricto por docente y unidad. Se incluye la extracción de texto, fragmentación y generación de embeddings usando PostgreSQL y pgvector para el adaptador híbrido.

## Historia de usuario y escenarios de prueba (Base)

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

## Requisitos funcionales (Base)

- **Validación**: Conectar el `UnitMembershipPort` (reutilizado de Generación) llamando a `get_unit_context(teacher_id, unit_id)`. Se usará la lista de `outcomes` recibida (id, code, text) para validar los `outcomeIds` asociados al archivo antes de procesarlo.
- **Procesamiento**: Excluir de la recuperación cualquier documento sin estado "listo".
- **Contrato Yan**: El puerto recibe `query`, `teacher_id`, `unit_id` y `limit`; devuelve fragmentos con IDs, nombre, ubicación, texto, relevancia (0 a 1) y modo de recuperación.
- **Métricas**: La integración vectorial debe alcanzar un Recall@10 ≥ 0.80.

## Decisiones técnicas (Arquitectura Base)

- **Estrategia de fragmentación**: Se utilizarán fragmentos de 512 tokens con 50 de solapamiento (overlap), optimizado para el modelo `multilingual-e5-base`.
- **Límite de Timeout**: Se establece un límite duro de 1500ms (1.5 segundos) para la consulta vectorial en PostgreSQL antes de hacer fallback a BM25.

---

# PARTE II — Nueva Entrega / Iteración P2 (MAT-P1, MAT-P2, MAT-P3)

## Objetivo y alcance (Iteración P2)

Ampliar las fuentes de evidencia y la trazabilidad académica del módulo mediante:

1. **MAT-P1 (Pedido P6):** Ingesta de material didáctico desde una URL web pública.
2. **MAT-P2 (Pedido P7):** Identificación automática de autores/referentes principales del tema con el modelo, persistencia junto a la evidencia y exposición hacia el plan de generación (`GEN-P1` / `ReferentsPort`).
3. **MAT-P3 (Pedido P8):** Manejo explícito de fallos de IA en el flujo RAG mediante reintento acotado y aviso visible al docente, evitando degradación silenciosa.

> **Nota de producto (UI):** Ningún mensaje, etiqueta o respuesta expuesta al docente debe mencionar la metodología "5E".

## Historias de usuario y escenarios de prueba (Iteración P2)

### Historia 2 (MAT-P1 / Pedido P6). Ingesta de material desde URL

Como docente, quiero registrar una URL pública como material de mi unidad para que el sistema descargue su contenido, extraiga el texto limpio y lo indexe en la base vectorial igual que un documento subido.

| Caso   | Dado y cuando                                                                                   | Entonces                                                                                                                                              |
| ------ | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| MAT-C7 | Se envía una URL HTTP/HTTPS válida y accesible perteneciente a una unidad del docente         | El sistema descarga la página, extrae el texto principal limpio, guarda el origen (`url`), fragmenta e indexa los vectores dejando estado "listo". |
| MAT-C8 | Se envía una URL con esquema inválido, destino local/privado (SSRF), caída o sin texto útil | El sistema rechaza la ingesta con error controlado (400/422) sin crear fragmentos corruptos ni revelar detalles internos.                             |
| MAT-C9 | Se intenta ingerir una URL en una unidad ajena o inexistente                                    | Se aplica la misma regla de seguridad que en MAT-C2 devolviendo `404 Not Found` indistinguible.                                                     |

### Historia 3 (MAT-P2 / Pedido P7). Identificación y entrega de referentes al Plan de Generación

Como docente, quiero que el sistema identifique los autores y referentes principales de la evidencia de mi unidad y los entregue al planificador (`GEN-P1`) para enriquecer la fundamentación de los recursos generados.

| Caso    | Dado y cuando                                                                              | Entonces                                                                                                                                                     |
| ------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| MAT-C10 | Existe evidencia procesada en la unidad y se solicita identificar/obtener referentes       | El modelo extrae autores/referentes principales vinculados a la evidencia de la unidad (con `fragmentIds` de respaldo cuando aplique) y los persiste.      |
| MAT-C11 | El módulo de Planificación (`GEN-P1`) consulta `ReferentsPort` al crear un plan      | El adaptador devuelve los referentes persistidos de la unidad aislados por `teacher_id` y `unit_id`, compatibles con el filtrado de evidencia congelada. |
| MAT-C12 | El material no menciona autores explícitos o la extracción no arroja referentes válidos | El sistema retorna una lista vacía `[]` sin bloquear la indexación del material ni la creación del plan de generación.                                 |

### Historia 4 (MAT-P3 / Pedido P8). Reintento y aviso al docente ante fallo de IA en RAG

Como docente, quiero que si el servicio de IA falla durante el procesamiento o recuperación asistida (RAG), el sistema realice un reintento controlado y me informe explícitamente del incidente en lugar de devolver resultados silenciosamente degradados.

| Caso    | Dado y cuando                                                        | Entonces                                                                                                                                     |
| ------- | -------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| MAT-C13 | Ocurre un error transitorio del proveedor de IA durante el flujo RAG | El sistema ejecuta un reintento acotado antes de dar por fallida la operación.                                                              |
| MAT-C14 | Persiste el fallo de IA tras agotarse el reintento                   | El sistema devuelve un estado/aviso explícito para el docente indicando que la IA falló, evitando silenciar el error con solo texto plano. |

## Clarificaciones y Puntos Abiertos (`/speckit-clarify`)

- **Contrato con `006-plan-de-generacion` (MAT-P2):** Se alinea con el puerto `ReferentsPort` integrado en PR #69. Cada referente expone identificador/nombre de autor o fuente, descripción/aporte y `fragment_ids` asociados; el planificador filtra automáticamente `fragment_ids` contra `evidence.fragments` congelados.
- **[NEEDS CLARIFICATION — P8 / MAT-P3]:** En la sesión con el profesor se mencionó ajustar un comportamiento del RAG junto con "los referentes", pero el audio fue poco claro en ese tramo. La implementación actual cubre reintento acotado + aviso explícito al docente como interpretación base, sujeta a confirmación final con el profesor.
