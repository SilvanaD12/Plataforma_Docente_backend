# Evidencia REV-P3 · Tasa de duplicidad y calibración del umbral

- **Módulo**: Revisión y exportación (`REV-01`)
- **Historia**: REV-P3 · Control de duplicidad en recursos y preguntas
- **Requisito**: REV-R15
- **Fecha**: 2026-11-22
- **Conjunto de datos evaluado**: `backend/src/platform5e/infrastructure/persistence/seed/demo_generation.json`

---

## 1. Algoritmo y configuración

El detector de duplicidad (`backend/src/platform5e/domain/review/duplication.py`) opera en Python puro sin dependencias externas ni consumo de modelos de lenguaje (`LLM_PROVIDER=rules`).

El pipeline de similitud consta de:
1. **Normalización base**: remueve diacríticos, puntuación, mayúsculas y palabras vacías (`stopwords`) en español.
2. **Raíz ligera (`stem`)**: remueve el sufijo más largo de la lista canónica para español si la raíz resultante mantiene al menos 3 caracteres (`ariamos`, `arian`, `aria`, `ando`, `iendo`, `aciones`, `acion`, `ciones`, `cion`, `mente`, `ados`, `adas`, `ado`, `ada`, `idos`, `ido`, `an`, `en`, `ar`, `er`, `ir`, `as`, `es`, `os`, `s`, `a`, `o`, `e`).
3. **Métricas combinadas**:
   - Similitud coseno sobre n-gramas de caracteres ($n \in \{3, 4, 5\}$) sobre los tokens con raíz.
   - Coeficiente de Jaccard sobre el conjunto de palabras con raíz.
4. **Puntaje final equilibrado**:

$$\text{score} = \frac{\text{coseno} + \text{jaccard}}{2}$$

Si los textos normalizados con raíz son idénticos, retorna `1.0`. El umbral por defecto es `0.70`, configurable mediante la variable de entorno `REVIEW_DUPLICATE_THRESHOLD`.

---

## 2. Casos fijos de calibración y puntaje real

Los siguientes casos fijos evalúan la capacidad del algoritmo para separar duplicados y paráfrasis de frases-plantilla y conceptos distintos:

| Caso de prueba | Texto A | Texto B | Puntaje real | Umbral `0.70` |
|---|---|---|:---:|:---:|
| **Ejemplo profesor** | `¿Cómo se gestionan los paquetes de redes?` | `¿Cómo se gestionaría los paquetes en una red?` | **1.000** | **Marcado** |
| **Par UDP** | `El protocolo UDP no ofrece garantías sobre la entrega o el orden de los paquetes.` | `UDP no ofrece garantías para la entrega o el orden de los paquetes en la red.` | **0.727** | **Marcado** |
| **Pila vs Cola (LIFO / FIFO)** | `Una pila es una estructura LIFO donde el último elemento en entrar es el primero en salir.` | `Una cola es una estructura FIFO donde el primer elemento en entrar es el primero en salir.` | **0.638** | **No marcado** |
| **Modelo OSI (enrutar vs cifrar)** | `¿Qué capa del modelo OSI enruta los paquetes?` | `¿Qué capa del modelo OSI cifra los datos?` | **0.477** | **No marcado** |
| **Pila vs Cola (pregunta simple)** | `¿Qué es una pila?` | `¿Qué es una cola?` | **0.000** | **No marcado** |

---

## 3. Análisis de sensibilidad por unidad curricular

El cálculo se ejecuta estrictamente por unidad curricular (tal como opera el endpoint de la aplicación):

### Unidad `u2`: Estructuras lineales: pilas y colas (12 recursos)
- Recursos evaluados: 12
- Pares comparados: 81 (66 de recursos y 15 de preguntas)

| Umbral evaluado | Pares marcados | duplicatePairRate | Detalle de hallazgos |
|:---:|:---:|:---:|---|
| `0.50` | 1 | 0.012 | `ex-u2-explain-1` vs `ex-u2-explain-2` (0.503, explicación y glosario del mismo tema) |
| `0.60` | 0 | 0.000 | Sin falsos positivos |
| `0.65` | 0 | 0.000 | Sin falsos positivos |
| **`0.70` (Defecto)** | **0** | **0.000** | **Separación nítida: 0 falsos positivos en recursos legítimos** |
| `0.75` | 0 | 0.000 | Sin falsos positivos |
| `0.80` | 0 | 0.000 | Sin falsos positivos |
| `0.90` | 0 | 0.000 | Sin falsos positivos |

### Unidad `u3`: Árboles binarios de búsqueda (3 recursos)
- Recursos evaluados: 3
- Pares comparados: 4 (3 de recursos y 1 de preguntas)

| Umbral evaluado | Pares marcados | duplicatePairRate | Detalle de hallazgos |
|:---:|:---:|:---:|---|
| `0.50` | 0 | 0.000 | Sin falsos positivos |
| `0.60` | 0 | 0.000 | Sin falsos positivos |
| `0.65` | 0 | 0.000 | Sin falsos positivos |
| **`0.70` (Defecto)** | **0** | **0.000** | **Separación nítida: 0 falsos positivos en recursos legítimos** |
| `0.75` | 0 | 0.000 | Sin falsos positivos |
| `0.80` | 0 | 0.000 | Sin falsos positivos |
| `0.90` | 0 | 0.000 | Sin falsos positivos |

---

## 4. Reproducción del análisis

Para ejecutar y reproducir las cifras reales reportadas en este documento, ejecute en PowerShell:

```powershell
python docs/evidence/REV-P3/calculate_duplicate_rate.py
```
