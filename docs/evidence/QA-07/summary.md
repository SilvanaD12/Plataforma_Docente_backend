# Evidencia de Evaluación RAG — QA-07 (`pgvector` + Ragas)

- **Tarea:** QA-07 (`specs/005-atributos-calidad/tasks.md`)
- **Pull Request:** #51
- **Run ID:** `qa07-gemini38`
- **Corpus:** `corpus_t067` (5 casos evaluados: `C-01` a `C-05`)
- **Modo de recuperación:** `hybrid` (`pgvector` HNSW + BM25, límite 8 fragmentos por caso)
- **Modelo generador:** `gemini-3.8-flash`
- **Juez Ragas:** `gemini-3.8-flash` (`answer_relevancy_strictness: 1`)
- **Trazabilidad (I22):** `5/5` recursos citan el material fuente

## 1. Métricas Globales (sin redondear)

En Ragas sobre 5 muestras (`C-01` a `C-05`), `context_recall` obtuvo `1.0` en 3 casos (`C-01`, `C-02`, `C-04`) y `0.0` en 2 casos (`C-03`, `C-05`), dando como promedio exacto `(1.0 + 1.0 + 0.0 + 1.0 + 0.0) / 5 = 0.6` (`0.6000`, cumpliendo el umbral `≥ 0,60`):

| Métrica                        | Valor exacto (`summary.json`) | Umbral / Criterio | Estado |
| :------------------------------ | :-----------------------------: | :----------------: | :----: |
| **`context_recall`**    | **`0.6` (`0.6000`)** |    `≥ 0.60`    | Cumple |
| **`faithfulness`**      |      **`0.9778`**      | Referencia calidad | Cumple |
| **`answer_relevancy`**  |      **`0.8972`**      | Referencia calidad | Cumple |
| **`context_precision`** |      **`0.5758`**      | Referencia calidad | Cumple |

## 2. Resultados por Caso y Aislamiento del Documento Distractor (`C-01` a `C-05`)

La inspección de `samples.jsonl` confirma que los 8 fragmentos recuperados en cada caso pertenecen exclusivamente a los documentos técnicos de redes del corpus (TCP/UDP, IPv4/IPv6, Modelo OSI, enrutamiento y Wireshark), sin recuperar ningún fragmento del documento distractor:

| Caso               |    Modo    | Fragmentos recuperados | Fragmentos del distractor |   `faithfulness`   | `answer_relevancy` | `context_precision` |       `context_recall`       |
| :----------------- | :--------: | :--------------------: | :-----------------------: | :------------------: | :------------------: | :-------------------: | :----------------------------: |
| **C-01**     | `hybrid` |           8           |        **0**        |       `1.0`       |      `0.8251`      |      `0.3313`      |            `1.0`            |
| **C-02**     | `hybrid` |           8           |        **0**        |       `1.0`       |      `0.9133`      |      `0.6488`      |            `1.0`            |
| **C-03**     | `hybrid` |           8           |        **0**        |       `1.0`       |      `0.9409`      |      `0.6488`      |            `0.0`            |
| **C-04**     | `hybrid` |           8           |        **0**        |       `1.0`       |      `0.9064`      |        `1.0`        |            `1.0`            |
| **C-05**     | `hybrid` |           8           |        **0**        |      `0.8889`      |      `0.9003`      |       `0.25`       |            `0.0`            |
| **Promedio** |     —     |           —           |     **0 / 40**     | **`0.9778`** | **`0.8972`** | **`0.5758`** | **`0.6` (`0.6000`)** |
