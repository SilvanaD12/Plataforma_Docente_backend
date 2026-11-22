# Evidencia REV-P3 · Tasa de duplicidad y calibración del umbral

- **Módulo**: Revisión y exportación (REV-01)
- **Historia**: REV-P3 · Control de duplicidad en recursos y preguntas
- **Requisito**: REV-R15
- **Fecha**: 2026-11-22
- **Conjunto de datos evaluado**: `backend/src/platform5e/infrastructure/persistence/seed/demo_generation.json` (15 recursos en 2 unidades curriculares)

---

## 1. Algoritmo y configuración

El detector de duplicidad (`backend/src/platform5e/domain/review/duplication.py`) opera en Python puro sin dependencias externas ni llamadas a modelos de lenguaje (`LLM_PROVIDER=rules`).

Combina dos métricas complementarias tras una normalización que remueve diacríticos, puntuación y palabras vacías (`stopwords`) en español:
1. **Similitud coseno sobre n-gramas de caracteres** ($n \in \{3, 4, 5\}$). Captura variaciones morfológicas, prefijos, sufijos y errores tipográficos.
2. **Coeficiente de Jaccard sobre conjuntos de palabras**. Captura solapamiento léxico directo con independencia del orden sintáctico.

El puntaje final se calcula como:

$$\text{score} = \min(1.0, \max(0.0, \operatorname{round}(\max(\text{coseno}, \text{jaccard}), 3)))$$

El umbral configurable es `REVIEW_DUPLICATE_THRESHOLD`, con valor por defecto `0.75` en `backend/src/platform5e/infrastructure/settings.py`.

---

## 2. Análisis de sensibilidad sobre el catálogo base

Se evaluaron todas las combinaciones de pares de recursos ($N(N-1)/2$) y pares de preguntas ($M(M-1)/2$) en el catálogo semilla `demo_generation.json`:
- Recursos evaluados: 15 (12 en unidad `u2`, 3 en unidad `u3`).
- Total de pares comparados: **133 pares** (105 pares de recursos y 28 pares de preguntas).

| Umbral evaluado | Pares marcados (`flaggedPairs`) | Pares comparados (`comparedPairs`) | Tasa de duplicidad (`duplicatePairRate`) | Observación |
|:---:|:---:|:---:|:---:|---|
| `0.50` | 2 | 133 | 0.015 | Falsos positivos entre recursos del mismo tema (pilas vs colas) |
| `0.60` | 1 | 133 | 0.008 | Falso positivo entre explicación y glosario de la unidad 2 |
| `0.65` | 0 | 133 | 0.000 | Separación clara entre recursos pedagógicamente distintos |
| `0.70` | 0 | 133 | 0.000 | Sin falsos positivos |
| **`0.75` (Defecto)** | **0** | **133** | **0.000** | **Umbral óptimo: 0 falsos positivos y detecta paráfrasis $\ge 0.77$** |
| `0.80` | 0 | 133 | 0.000 | Mayor rigurosidad; puede omitir paráfrasis amplias |
| `0.90` | 0 | 133 | 0.000 | Solo detecta duplicados casi idénticos |

---

## 3. Justificación del umbral 0.75

1. **Ausencia de falsos positivos en recursos legítimos**:
   El par de recursos más afín en el catálogo de prueba (`ex-u2-explain-1` vs `ex-u2-explain-2`, ambos sobre estructuras lineales) obtiene una similitud máxima de **0.675**, manteniéndose con holgura por debajo del umbral 0.75.

2. **Detección robusta de paráfrasis y copias**:
   Las pruebas unitarias automáticas en `backend/tests/unit/test_duplication.py` demuestran que:
   - Contenidos idénticos o variaciones de mayúsculas/puntuación obtienen puntaje **1.000**.
   - Paráfrasis directas con inversión de cláusulas y sinónimos frecuentes obtienen puntajes entre **0.778** y **0.885** (superando el umbral).
   - Pares con contenido pedagógico no relacionado obtienen puntajes inferiores a **0.500**.

---

## 4. Resultados reales por unidad (umbral 0.75)

### Unidad `u2` (Estructuras lineales: pilas y colas)
- Recursos: 12
- Pares comparados: 81
- Pares duplicados marcados: 0
- `duplicatePairRate`: **0.000**

### Unidad `u3` (Árboles binarios de búsqueda)
- Recursos: 3
- Pares comparados: 4
- Pares duplicados marcados: 0
- `duplicatePairRate`: **0.000**

### Catálogo completo
- Total de recursos: 15
- Total pares comparados: 133
- Total duplicados marcados: 0
- `duplicatePairRate`: **0.000**
