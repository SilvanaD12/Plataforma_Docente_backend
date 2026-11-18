# Evidencia de Prueba de Estrés Incremental — QA-18 (JMeter)

- **Tarea:** QA-18 (`specs/005-atributos-calidad/tasks.md`)
- **Tipo:** Backend / Desempeño y Fiabilidad
- **Atributos ISO/IEC 25010:** Eficiencia de desempeño / Fiabilidad
- **Medidas ISO/IEC 25023:** `PCa-1-G` (Capacidad de procesamiento de transacciones) y `RRe-1-G` (Tiempo medio de recuperación)
- **Fecha de ejecución:** 18 de noviembre de 2026 (08:26:09 a 08:33:06 GMT-05:00)
- **Objetivo:** Ejecutar prueba de estrés incremental en 5 escalones (50, 100, 200, 400 y 800 hilos concurrentes) sobre la pila local para identificar el primer punto de quiebre (`p95 > 5 s` o tasa de errores `> 5 %`) y medir el tiempo de recuperación de la API.

---

## 1. Entorno de Ejecución

Todas las mediciones se realizaron en entorno estrictamente local sin consumo de cuotas externas ni dominios públicos:

| Parámetro | Valor / Especificación |
| :--- | :--- |
| **Sistema Operativo** | Microsoft Windows 10 Pro (Build 19045, 64-bit) |
| **CPU** | Intel(R) Core(TM) i3-1005G1 CPU @ 1.20GHz (2 núcleos físicos, 4 procesadores lógicos) |
| **Memoria RAM** | 7.79 GB física total |
| **Versión de Python** | Python 3.12.16 (entorno virtual `.venv`) |
| **Base de Datos** | PostgreSQL 17.8 con extensión `pgvector 0.8.1` (contenedor Docker `backend-db-1`) |
| **Herramienta de Carga** | Apache JMeter 5.6.3 (Java SE Runtime Environment 25.0.1 LTS) |
| **Proveedor LLM** | `LLM_PROVIDER=rules` (generador determinista por reglas locales) |
| **Servidor API** | Uvicorn (`platform5e.main:app`) en `http://localhost:8000` (1 worker) |

---

## 2. Comando Exacto de Ejecución

Desde la carpeta `backend/`:

```powershell
# 1. Generación y sincronización de 800 docentes de prueba con unidades y material procesado
.\.venv\Scripts\python.exe performance\jmeter\prepare_users.py --users 800 --workers 16

# 2. Ejecución no interactiva de Apache JMeter con generación de reporte HTML
& "$env:USERPROFILE\tools\apache-jmeter-5.6.3\bin\jmeter.bat" -n `
  -t performance\jmeter\stress.jmx `
  -Jhost=localhost -Jport=8000 `
  -l performance\jmeter\results\run1.jtl `
  -e -o performance\jmeter\results\run1-report

# 3. Sondeo inmediato de recuperación de /health durante 60 s (1 sondeo/s)
python performance\jmeter\measure_recovery.py --url http://127.0.0.1:8000/health --duration 60 --out ..\docs\evidence\QA-18\run1-recovery.txt

# 4. Cálculo de métricas por escalón a partir de run1.jtl
python performance\jmeter\summarize_jtl.py --jtl performance\jmeter\results\run1.jtl --out ..\docs\evidence\QA-18
```

---

## 3. Resultados por Escalón de Carga (Corrida 1 — Base)

Tabla consolidada generada automáticamente por `summarize_jtl.py` a partir de `run1.jtl` (`docs/evidence/QA-18/run1-tiers.csv`):

| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | Latencia Media (ms) | Latencia P50 (ms) | Latencia P95 (ms) | Latencia Máx (ms) | Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | 50 | 2 501 | 115.5 s | 21.66 req/s | 129.5 ms | 77 ms | 436 ms | 962 ms | 0.00 % (0) | 2.44 % (61) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 2** | 100 | 4 627 | 117.3 s | 39.43 req/s | 292.8 ms | 203 ms | 875 ms | 1 646 ms | 0.11 % (5) | 5.01 % (232) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 3** | 200 | 5 875 | 117.2 s | 50.12 req/s | 1 604.6 ms | 1 451 ms | 3 236 ms | 7 568 ms | 0.07 % (4) | 3.86 % (227) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 4** | 400 | 1 126 | 30.6 s | 36.78 req/s | 5 940.7 ms | 5 470 ms | **12 525 ms** | 14 268 ms | 0.00 % (0) | 0.80 % (9) | **Punto de quiebre alcanzado** (`p95 > 5 s`) |
| **Tier 5** | 800 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |

> **Nota sobre respuestas 429:** Las respuestas HTTP 429 corresponden al código de negocio `TOO_MANY_ACTIVE_REQUESTS` (máximo 2 solicitudes de generación simultáneas por docente), contempladas como comportamiento esperado en la especificación y validadas positivamente mediante la aserción de JMeter.

---

## 4. Desglose Global por Endpoint (Corrida 1)

Datos consolidados extraídos de `docs/evidence/QA-18/run1-statistics.json`:

| Endpoint | Muestras | Throughput (req/s) | Media (ms) | Mediana (ms) | P95 (ms) | Máximo (ms) | Errores (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `POST /api/v1/sessions` | 748 | 1.87 | 3 876.4 ms | 2 554.0 ms | 11 970.3 ms | 13 705.0 ms | 0.00 % |
| `GET /api/v1/courses` | 3 780 | 9.48 | 1 322.7 ms | 561.0 ms | 4 207.4 ms | 14 268.0 ms | 0.03 % |
| `GET /api/v1/documents/search` | 2 559 | 6.41 | 1 402.9 ms | 649.0 ms | 4 320.0 ms | 14 060.0 ms | 0.16 % |
| `POST /api/v1/generation-requests` | 1 223 | 3.07 | 1 463.2 ms | 863.0 ms | 4 328.4 ms | 11 370.0 ms | 0.00 % |
| `GET /api/v1/generation-requests/{id}` | 676 | 1.70 | 1 200.6 ms | 512.5 ms | 3 274.8 ms | 12 989.0 ms | 0.00 % |
| `GET /health` | 5 143 | 12.93 | 720.3 ms | 304.0 ms | 2 106.6 ms | 10 284.0 ms | 0.08 % |
| **Total Global** | **14 129** | **35.22** | **1 259.5 ms** | **541.0 ms** | **5 160.0 ms** | **14 268.0 ms** | **0.06 %** |

---

## 5. Análisis del Punto de Quiebre, Recursos y Diferencia con Corrida Previa

1. **Identificación del Punto de Quiebre:**
   - En **Tier 1 (50 hilos)**, **Tier 2 (100 hilos)** y **Tier 3 (200 hilos)**, la API cumplió plenamente el SLA acordado (`p95 ≤ 5 s` y tasa de fallos `≤ 5 %`). En Tier 3 la latencia `p95` se mantuvo en **3 236 ms** con solo 0.07 % de errores de conexión.
   - El punto de quiebre real se alcanzó en **Tier 4 (400 hilos)** tras 30.6 segundos y 1 126 muestras evaluadas (cumpliendo con la ventana mínima configurada de `${__P(min_tier_seconds,30)}` y `${__P(min_tier_samples,300)}`). En este escalón, la latencia `p95` escaló a **12 525 ms** (superando el límite de 5 s), activando la parada automática del plan de prueba.
   - El escalón final (Tier 5 con 800 hilos) no se ejecutó para proteger la estabilidad de la pila local.

2. **Causa Probable y Análisis de Errores Observados:**
   - En `docs/evidence/QA-18/run1-server-errors.txt` se constata que **no se produjeron errores 5xx del servidor** en los registros de Uvicorn. Todas las peticiones atendidas respondieron 200 OK, 202 Accepted o 429 Too Many Requests (control de negocio `TOO_MANY_ACTIVE_REQUESTS`).
   - Los 9 fallos registrados en JMeter (5 en Tier 2 y 4 en Tier 3, tasa global de 0.06 %) corresponden a excepciones a nivel de socket de red del cliente (`NoHttpResponseException` y `SocketException: Connection reset`). La causa probable observada es la saturación transitoria del backlog de sockets TCP del sistema operativo Windows durante la rampa de conexiones concurrentes hacia el puerto 8000.

3. **Uso de Recursos en Contenedores Docker:**
   - Durante la ejecución máxima (Tier 3 y Tier 4), el contenedor `backend-db-1` registró un pico de CPU de **204.75 %** (a las `08:30:28`) aprovechando múltiples núcleos lógicos para la persistencia concurrente, y un consumo de memoria máximo de **89.23 MiB** (a las `08:31:02`), operando de manera estable sin desbordes de memoria ni reinicios de contenedor (`docs/evidence/QA-18/run1-docker-stats.txt`).

4. **Explicación de Diferencias con la Corrida Anterior:**
   - **Ventana mínima de observación:** En la corrida anterior, el Breaking Point Monitor evaluaba el corte con solo 40 muestras y sin ventana mínima de tiempo, lo que provocó una parada prematura en Tier 2 a los 9.2 segundos (con apenas 55 muestras). Al incorporar las propiedades `${__P(min_tier_seconds,30)}` y `${__P(min_tier_samples,300)}`, cada escalón dispone del tiempo y volumen de muestras necesarios para estabilizar la rampa antes de evaluar el quiebre.
   - **Sondeo del estado del pedido (`GET /api/v1/generation-requests/{id}`):** Se corrigió la expresión Groovy en el IfController y el reseteo de `request_id`, registrándose 676 muestras válidas con latencia nominal `p95 = 3 274.8 ms` y 0 errores.
   - **Sincronización de datos de prueba:** Al sincronizar previamente los 800 docentes con `prepare_users.py`, se eliminaron los errores 404 de unidades inexistentes.
   - **Desplazamiento del punto de quiebre y capacidad:** El punto de quiebre real se desplazó de Tier 2 a **Tier 4 (400 hilos)**, incrementando la capacidad medida de procesamiento conforme (`PCa-1-G`) de 17.61 req/s a **50.12 req/s** (Tier 3).

---

## 6. Tiempo de Recuperación del Servicio (`RRe-1-G`)

A partir de la finalización de la carga de JMeter, se ejecutó `measure_recovery.py` realizando 60 sondeos consecutivos a `/health` (uno cada segundo) durante un minuto completo. La evidencia íntegra se encuentra en `docs/evidence/QA-18/run1-recovery.txt`:

- **Sondeo 1 (+0.0 s tras fin de ráfaga):** Código `200 OK`, latencia = **227.4 ms** (< 1 000 ms).
- **Sondeos 2 a 60 (+1.0 s a +59.0 s):** El 100 % de los sondeos respondieron `200 OK` con latencias estabilizadas entre **4.8 ms** y **152.2 ms**.

El tiempo de recuperación medido es de **0.00 segundos** (`RRe-1-G = 0.00 s`), superando holgadamente la meta acordada de recuperación en menos de 10 segundos.

---

## 7. Conclusión de Medidas ISO/IEC 25023

| Medida ISO/IEC 25023 | Definición / Fórmula | Valor Medido | Evaluación |
| :--- | :--- | :---: | :--- |
| **PCa-1-G**<br>Capacidad de procesamiento de transacciones | Peticiones por segundo del último escalón que cumple SLA (`p95 ≤ 5 s`, err `≤ 5 %`) | **50.12 req/s** | Último escalón conforme: Tier 3 (200 hilos concurrentes) |
| **RRe-1-G**<br>Tiempo medio de recuperación | Segundos hasta que `/health` responde 200 en `< 1 s` tras cesar la sobrecarga | **0.00 s** | Meta < 10 s cumplida inmediatamente al sondeo 1 (227.4 ms) |

---

## 8. Corrida 2 (con QA-16)

- **Estado:** Pendiente.
- **Motivo:** En espera de la integración de la tarea QA-16 (Sergio), la cual implementa el middleware de protección contra denegación de servicio (rate limiting por IP y límite de tamaño de cuerpo). Una vez integrado dicho PR a `main`, se reejecutará esta misma batería para comparar el comportamiento de rechazo controlado (HTTP 429) y la preservación de CPU en la base de datos.

---

## 9. Archivos de Evidencia Adjuntos

- **Resumen por escalón (CSV):** [run1-tiers.csv](run1-tiers.csv)
- **Resumen por escalón (Markdown):** [run1-tiers.md](run1-tiers.md)
- **Estadísticas completas por endpoint:** [run1-statistics.json](run1-statistics.json)
- **Monitoreo de contenedores Docker:** [run1-docker-stats.txt](run1-docker-stats.txt)
- **Evidencia del sondeo de recuperación (60 s):** [run1-recovery.txt](run1-recovery.txt)
- **Registro de errores del servidor:** [run1-server-errors.txt](run1-server-errors.txt)
- **Reporte interactivo HTML de JMeter:** Generado en `backend/performance/jmeter/results/run1-report/`.
