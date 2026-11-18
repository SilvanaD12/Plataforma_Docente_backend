# Evidencia de Prueba de Estrés Incremental — QA-18 (JMeter)

- **Tarea:** QA-18 (`specs/005-atributos-calidad/tasks.md`)
- **Tipo:** Backend / Desempeño y Fiabilidad
- **Atributos ISO/IEC 25010:** Eficiencia de desempeño / Fiabilidad
- **Medidas ISO/IEC 25023:** `PCa-1-G` (Capacidad de procesamiento de transacciones) y `RRe-1-G` (Tiempo medio de recuperación)
- **Fecha de ejecución:** 17 de noviembre de 2026 (11:49:50 a 11:54:46 GMT-05:00)
- **Objetivo:** Ejecutar prueba de estrés incremental en 5 escalones (50, 100, 200, 400 y 800 hilos concurrentes) sobre la pila local para identificar el primer punto de quiebre (`p95 > 2 s` o tasa de errores `> 5 %`) y medir el tiempo de recuperación de la API.

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
# 1. Generación previa de 800 docentes de prueba con unidades y material procesado
.\.venv\Scripts\python.exe performance\jmeter\prepare_users.py --users 800 --workers 16

# 2. Ejecución no interactiva de Apache JMeter con generación de reporte HTML
& "$env:USERPROFILE\tools\apache-jmeter-5.6.3\bin\jmeter.bat" -n `
  -t performance\jmeter\stress.jmx `
  -Jhost=localhost -Jport=8000 `
  -l performance\jmeter\results\run1.jtl `
  -e -o performance\jmeter\results\run1-report
```

---

## 3. Resultados por Escalón de Carga (Corrida 1 — Base)

| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | Latencia Media (ms) | Latencia P95 (ms) | Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | 50 | 2 153 | 114.2 s | 18.85 req/s | 390.3 ms | 1 362 ms | 0.05 % (1) | 4.23 % (91) | **Cumple SLA** (`p95 < 2 s`, err `< 5 %`) |
| **Tier 2** | 100 | 2 823 | 119.0 s | 23.71 req/s | 1 670.4 ms | **4 375 ms** | 0.11 % (3) | 3.33 % (94) | **Degradación SLA** (`p95 > 2 s`) |
| **Tier 3** | 200 | 522 | 30.2 s | 17.27 req/s | 3 327.4 ms | **7 514 ms** | 0.00 % (0) | 0.19 % (1) | **Punto de quiebre alcanzado** |
| **Tier 4** | 400 | — | — | — | — | — | — | — | No ejecutado (parada automática) |
| **Tier 5** | 800 | — | — | — | — | — | — | — | No ejecutado (parada automática) |

> **Nota sobre respuestas 429:** Las respuestas HTTP 429 corresponden al código de negocio `TOO_MANY_ACTIVE_REQUESTS` (máximo 2 solicitudes de generación en curso por docente), contempladas como comportamiento esperado en la especificación y validadas positivamente mediante la aserción de JMeter.

---

## 4. Desglose Global por Endpoint (Corrida 1)

Datos consolidados extraídos de `run1-statistics.json`:

| Endpoint | Muestras | Throughput (req/s) | Media (ms) | Mediana (ms) | P95 (ms) | Máximo (ms) | Errores (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `POST /api/v1/sessions` | 319 | 1.18 | 2 885.4 ms | 2 031 ms | 7 795 ms | 9 161 ms | 0.00 % |
| `GET /api/v1/courses` | 1 542 | 5.77 | 1 402.2 ms | 699 ms | 4 540 ms | 12 629 ms | 0.00 % |
| `GET /api/v1/documents/search` | 1 045 | 3.91 | 1 556.9 ms | 816 ms | 5 421 ms | 11 958 ms | 0.10 % |
| `POST /api/v1/generation-requests` | 501 | 1.88 | 1 890.3 ms | 1 345 ms | 4 924 ms | 13 406 ms | 0.00 % |
| `GET /health` | 2 091 | 7.87 | 782.5 ms | 305 ms | 2 756 ms | 9 494 ms | 0.14 % |
| **Total Global** | **5 498** | **20.36** | **1 326.5 ms** | **666 ms** | **4 629 ms** | **13 406 ms** | **0.07 %** |

---

## 5. Análisis del Punto de Quiebre y Recursos

1. **Identificación del Punto de Quiebre:**
   - En **Tier 1 (50 hilos)**, la API mantuvo un comportamiento estable con latencia `p95 = 1 362 ms` (< 2 000 ms) y tasa de fallos de 0.05 %.
   - El primer incumplimiento de SLA ocurrió al inicio de **Tier 2 (100 hilos)**, donde el `p95` ascendió a **4 375 ms** (superando el límite de 2 s), a pesar de que el throughput aumentó a 23.71 req/s (con picos instantáneos de 31.7 req/s).
   - En **Tier 3 (200 hilos)**, el sistema experimentó una degradación crítica: el `p95` llegó a **7 514 ms** y la media a **3 327.4 ms**, activando la compuerta de parada por estrés extremo (`SampleResult.setStopTest(true)`) para proteger la estabilidad de la pila local.

2. **Causa Raíz y Primer Error Observado:**
   - Durante la transición de Tier 1 a Tier 2 se registraron 3 errores de conexión: `org.apache.http.NoHttpResponseException: localhost:8000 failed to respond` y 1 error `java.net.SocketException: Connection reset`.
   - Según el registro de `run1-docker-stats.txt`, el contenedor de base de datos (`backend-db-1`) alcanzó un consumo de CPU de **350.61 %** (saturando los núcleos virtuales asignados a Docker Desktop). Uvicorn, al operar con un solo proceso worker, encoló las peticiones entrantes generando tiempos de espera acumulados en el socket.

---

## 6. Tiempo de Recuperación del Sistema (`RRe-1-G`)

Inmediatamente después de cesar la carga de JMeter, se realizaron consultas periódicas a `/health` para medir el tiempo necesario para volver a operar en niveles nominales (HTTP 200 con latencia < 1 000 ms):

- **Sondeo 1 (+2.81 s tras fin de ráfaga):** Código `200 OK`, latencia = **2 701 ms** (el servidor aún terminaba de procesar peticiones encoladas).
- **Sondeo 2 (+4.11 s tras fin de ráfaga):** Código `200 OK`, latencia = **74 ms** (< 1 000 ms).

El tiempo de recuperación medido es de **4.11 segundos**.

---

## 7. Conclusión de Medidas ISO/IEC 25023

| Medida ISO/IEC 25023 | Definición / Fórmula | Valor Medido | Evaluación |
| :--- | :--- | :---: | :--- |
| **PCa-1-G**<br>Capacidad de procesamiento de transacciones | Peticiones por segundo en el punto de quiebre | **23.71 req/s**<br>*(Tier 2 - degradación SLA p95 > 2s)*<br>**17.27 req/s**<br>*(Tier 3 - saturación extrema CPU)* | Pico máximo de 31.7 req/s sostenido en ventana de 30 s. |
| **RRe-1-G**<br>Tiempo medio de recuperación | Segundos hasta que `/health` vuelve a responder 200 en `< 1 s` | **4.11 s** | Recuperación rápida tras drenar la cola de conexiones. |

---

## 8. Corrida 2 (con QA-16)

- **Estado:** Pendiente.
- **Motivo:** En espera de la integración de la tarea QA-16 (Sergio), la cual implementa el middleware de protección contra denegación de servicio (rate limiting por IP y límite de tamaño de cuerpo). Una vez integrado dicho PR a `main`, se reejecutará esta misma batería para comparar el comportamiento de rechazo controlado (HTTP 429) y la preservación de CPU en la base de datos.

---

## 9. Archivos de Evidencia Adjuntos

- **Estadísticas completas:** [run1-statistics.json](run1-statistics.json)
- **Monitoreo de contenedores Docker:** [run1-docker-stats.txt](run1-docker-stats.txt)
- **Reporte interactivo HTML de JMeter:** El reporte HTML interactivo con gráficos de latencia, throughput y distribución temporal fue generado en `backend/performance/jmeter/results/run1-report/` y se adjunta comprimido al PR correspondiente.
