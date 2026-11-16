# TA-006 · Matriz de compatibilidad de exportaciones

**Criterio** (guía de traspaso, «Pendientes de Revisión y Exportación»): registrar por LMS y formato el archivo probado,
la versión, el resultado y la captura, usando los paquetes de las pruebas funcionales.

Actualizado el 15 de noviembre de 2026 (Sprint 2, QA-03). Solo se anota lo comprobado; lo demás queda «Pendiente».

## Moodle

| Formato | Versión probada | Fecha | Archivo probado | Resultado | Evidencia | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| Moodle XML (3 tipos: opción múltiple, verdadero/falso, emparejamiento) | Moodle 5.3.1 (Build: 20261112), sandbox.moodledemo.net | 15/11/2026 | `docs/evidence/QA-03/qa03-20261115-moodle-all-types.xml` (7 preguntas: 1 emparejamiento de 6 pares, 5 verdadero/falso, 1 opción múltiple de 4 opciones) | **Importa sin errores**: «Importing 7 questions from file»; categoría `$course$/top/RED-402 · Unidad 1/Nivel 2 · Intermedio`. Cada tipo genera su formato XML correspondiente (`type="matching"` con `<subquestion>` y `<answer>`, `type="truefalse"` con `<answer fraction="100\|0">` de `true` y `false`, `type="multichoice"` con CDATA). Retroalimentación específica y general («Para repasar…») y calificación por defecto preservadas. | Archivo validado en `docs/evidence/QA-03/qa03-20261115-moodle-all-types.xml`. Validador del backend: OK (12 pruebas unitarias en `test_moodle_xml_exporter.py`). Capturas en `docs_equipo/capturas/QA-03/` | El sandbox de Moodle se reinicia cada hora. Emparejamiento exige al menos 3 pares; verdadero/falso genera una pregunta por afirmación. |
| Moodle XML (opción múltiple) | Moodle 5.3.1 (Build: 20261112), sandbox.moodledemo.net | 13 y 14/11/2026 | `docs_equipo/exports/HU-043/hu043-20261112230327-moodle.xml` (1 ítem de opción múltiple aprobado) | **Importa sin errores**: «Importing 1 questions from file»; categoría «HU043 · Unidad 1 / Nivel 2 · Intermedio»; «capa de transporte» con 100 % y UDP, TCP y SYN con 0 %, cada una con su retroalimentación. En la vista previa (retroalimentación inmediata), UDP se marca incorrecta con su retroalimentación y «capa de transporte» se marca correcta; en las dos aparece la general «Para repasar…» | `capturas/HU-043/hu043-b01-formulario-con-xml.png`, `hu043-b02-resultado-importacion.png`, `hu043-b03-*.png`, `hu043-b04-respuesta-incorrecta-udp.png`, `hu043-b05-respuesta-correcta.png`. Validador del backend: OK | Prueba base inicial de Sprint 1. |
| SCORM 1.2 | — | — | — | **Pendiente** | — | No probado en Moodle. |
| Documento de la unidad (HTML) | — | — | — | **Pendiente** | — | Se abre en el navegador (T060, T059); no se probó como recurso de un curso de Moodle. |

## Chamilo

| Formato | Versión probada | Fecha | Archivo probado | Resultado | Evidencia | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| SCORM 1.2 | Chamilo de campus.chamilo.net («Open Campus v2»; el sitio no muestra el número de versión) | 14/11/2026 | `docs_equipo/exports/HU-008/hu008-20261113061913-scorm.zip` (5 recursos, uno por etapa 5E) | **Importa sin errores**: en Lecciones → Importar aparece la lección «HU008 · Unidad 1: Capa de transporte» con los 5 elementos en orden. El elemento 1 (pregunta detonante) y el 3 (explicación) se abren con su contenido, estilos y fuentes; Chamilo registra el avance (20 % y 40 % completado, con marca en los vistos), así que la API SCORM responde | `capturas/HU-008/hu008-00` a `hu008-04` | Falta abrir el elemento 5 (evaluación por niveles) y responderlo. |
| Moodle XML | — | — | — | **Pendiente** | — | No evaluado. |
| Documento de la unidad (HTML) | — | — | — | **Pendiente** | — | No evaluado. |

## Canvas

| Formato | Versión probada | Fecha | Archivo probado | Resultado | Evidencia | Observaciones |
| --- | --- | --- | --- | --- | --- | --- |
| SCORM 1.2 | — | — | — | **Pendiente** | — | La pantalla de Exportación lo menciona («En Canvas: la herramienta SCORM del curso»), pero no se probó. |

## Fuera de un LMS (comprobado)

| Formato | Dónde | Fecha | Resultado | Evidencia |
| --- | --- | --- | --- | --- |
| SCORM 1.2 (SCO abierto en el navegador con una API SCORM simulada) | Chromium (Playwright), local | 14/11/2026 | La actividad kinestésica queda `incomplete` con 3 de 4 pasos y `completed` (100) con 4 de 4 | `capturas/T059/t059-02` a `t059-04` |
| Moodle XML descargado desde la interfaz | Recorrido Playwright con backend local (`npm run test:e2e:real`) | 14/11/2026 | Validador del backend OK; `fraction="100"` solo en la respuesta correcta | `e2e/real/moodle-export.spec.ts` en la rama del PR #17 del frontend (por subir) |

## Estado de soporte y limitaciones conocidas

- **Moodle XML**: en Sprint 2 (QA-03) soporta 3 tipos de preguntas:
  - Opción múltiple (`item_opcion_multiple` → `<question type="multichoice">`) con distractores calificados y retroalimentación individual y general.
  - Verdadero o falso (`verdadero_falso` → `<question type="truefalse">`) con una pregunta por cada afirmación del conjunto, calificando `true` o `false` con 100 % o 0 %, y retroalimentación contextual.
  - Emparejamiento (`emparejamiento` → `<question type="matching">`) con pares término-definición (`<subquestion>` y `<answer>`), `shuffleanswers=true` y un mínimo validado de 3 pares para cumplir el requisito de Moodle.
- En SCORM, una imagen sin archivo generado se muestra con su descripción (tarjeta de respaldo).
- `imsmanifest.xml` cita los esquemas `.xsd` en `xsi:schemaLocation`, pero no los incluye en el ZIP; algunos LMS podrían exigirlos.
- Todo ítem de opción múltiple va a la evaluación por niveles del SCORM hasta definir qué cuenta como Textual explícito.
