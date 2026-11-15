# Corpus de evaluación RAG (TA-010, T067)

Sergio entregó este corpus y las respuestas de referencia de los casos de `evaluation/cases_t067.json`. Solo se usa
para evaluar la recuperación y la generación (`collect_samples.py` y `run_ragas.py`): no es material de la plataforma
ni se muestra a los docentes.

`collect_samples.py --corpus evaluation/corpus_t067` sube los archivos PDF, PPTX y TXT de esta carpeta y omite este
README.

| Archivo | Formato | Origen | Licencia o permiso | Papel en la evaluación |
|---|---|---|---|---|
| `Modelo OSI.txt` | TXT | Wikipedia en español, artículo «Modelo OSI»: <https://es.wikipedia.org/wiki/Modelo_OSI> | CC BY-SA 4.0 | Respuesta de C-01 |
| `Protocolo de datagramas de usuario.txt` | TXT | Wikipedia en español, artículo «Protocolo de datagramas de usuario»: <https://es.wikipedia.org/wiki/Protocolo_de_datagramas_de_usuario> | CC BY-SA 4.0 | Respuesta de C-02 |
| `protocolos_tcp_udp.pdf` | PDF | Material del curso | Uso autorizado. El archivo dice «Contenido original de libre uso educativo» | Respuesta de C-03 |
| `direccionamiento_ip_enrutamiento.pptx` | PPTX | Material del curso | Uso autorizado | Respuesta de C-04 |
| `guia_laboratorio_wireshark.docx.pdf` | PDF (exportado de Word) | Material del curso | Uso autorizado. El archivo dice «Contenido original de libre uso educativo» | Respuesta de C-05 |
| `bases_datos_relacionales.txt` | TXT | Material del curso, de otro tema | Uso autorizado. El archivo dice «Contenido original de libre uso educativo» | Distractor: ruido para `context_precision` en C-01 a C-05. C-06 pregunta por este tema en una unidad que no tiene el archivo |

## Textos de Wikipedia

Los dos textos de Wikipedia se usan solo para la evaluación. Se distribuyen con la licencia
[Creative Commons Atribución-CompartirIgual 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.es) (CC BY-SA 4.0).
La autoría es de los colaboradores de Wikipedia; el historial de cada artículo está en su página. Si se modifican, se
comparten con la misma licencia.

## Nombres de archivo

El backend acepta los nombres tal como están. Los espacios están permitidos, y el formato sale de la última extensión,
así que `guia_laboratorio_wireshark.docx.pdf` se procesa como PDF. Se comprobó el 2026-11-13 subiendo y procesando los
6 archivos en un servidor local con el generador por reglas: todos quedaron en estado `procesado`.
