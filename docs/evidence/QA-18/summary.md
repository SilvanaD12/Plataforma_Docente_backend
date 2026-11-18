# Evidencia de Prueba de Estrés Incremental — QA-18 (JMeter)

- **Tarea:** QA-18 (`specs/005-atributos-calidad/tasks.md`)
- **Tipo:** Backend / Desempeño y Fiabilidad
- **Atributos ISO/IEC 25010:** Eficiencia de desempeño / Fiabilidad
- **Medidas ISO/IEC 25023:** `PCa-1-G` (Capacidad de procesamiento de transacciones) y `RRe-1-G` (Tiempo medio de recuperación)
- **Fecha de ejecución:** 18 de noviembre de 2026 (00:29:57 a 00:32:15 GMT-05:00)
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
# 1. Generación previa de 800 docentes de prueba con unidades y material procesado
.\.venv\Scripts\python.exe performance\jmeter\prepare_users.py --users 800 --workers 16

# 2. Ejecución no interactiva de Apache JMeter con generación de reporte HTML
& "$env:USERPROFILE\tools\apache-jmeter-5.6.3\bin\jmeter.bat" -n `
  -t performance\jmeter\stress.jmx `
  -Jhost=localhost -Jport=8000 `
  -l performance\jmeter\results\run1.jtl `
  -e -o performance\jmeter\results\run1-report

# 3. Cálculo de métricas por escalón
python performance\jmeter\summarize_jtl.py --jtl performance\jmeter\results\run1.jtl --out ..\docs\evidence\QA-18
```

---

## 3. Resultados por Escalón de Carga (Corrida 1 — Base)

Tabla consolidada generada automáticamente por `summarize_jtl.py` a partir de `run1.jtl`:

| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | Latencia Media (ms) | Latencia P50 (ms) | Latencia P95 (ms) | Latencia Máx (ms) | Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | 50 | 2 042 | 116.0 s | 17.61 req/s | 602.1 ms | 157 ms | 3 640 ms | 9 070 ms | 1.18 % (24) | 3.53 % (72) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 2** | 100 | 55 | 9.2 s | 5.98 req/s | 2 207.7 ms | 803 ms | **8 771 ms** | 10 579 ms | 7.27 % (4) | 0.00 % (0) | **Punto de quiebre alcanzado** (`p95 > 5 s`) |
| **Tier 3** | 200 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
| **Tier 4** | 400 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
| **Tier 5** | 800 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |

> **Nota sobre respuestas 429:** Las respuestas HTTP 429 corresponden al código de negocio `TOO_MANY_ACTIVE_REQUESTS` (máximo 2 solicitudes de generación en curso por docente), contempladas como comportamiento esperado en la especificación y validadas positivamente mediante la aserción de JMeter.

---

## 4. Desglose Global por Endpoint (Corrida 1)

Datos consolidados extraídos de `run1-statistics.json`:

| Endpoint | Muestras | Throughput (req/s) | Media (ms) | Mediana (ms) | P95 (ms) | Máximo (ms) | Errores (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `POST /api/v1/sessions` | 83 | 0.62 | 1 965.8 ms | 803.0 ms | 10 579.0 ms | 10 579.0 ms | 6.02 % |
| `GET /api/v1/courses` | 567 | 4.51 | 794.7 ms | 247.0 ms | 7 150.2 ms | 7 676.0 ms | 1.59 % |
| `GET /api/v1/documents/search` | 385 | 3.03 | 843.1 ms | 331.0 ms | 7 267.0 ms | 7 745.0 ms | 1.56 % |
| `POST /api/v1/generation-requests` | 187 | 1.67 | 1 723.7 ms | 842.0 ms | 9 008.4 ms | 9 070.0 ms | 3.74 % |
| `GET /api/v1/generation-requests/{id}` | 107 | 1.01 | 634.6 ms | 313.0 ms | 7 523.6 ms | 7 526.0 ms | 0.00 % |
| `GET /health` | 768 | 6.08 | 29.0 ms | 3.0 ms | 319.3 ms | 2 768.0 ms | 0.13 % |
| **Total Global** | **2 097** | **15.71** | **644.2 ms** | **165.0 ms** | **7 472.5 ms** | **10 579.0 ms** | **1.34 %** |

---

## 5. Análisis del Punto de Quiebre y Recursos

1. **Identificación del Punto de Quiebre:**
   - En **Tier 1 (50 hilos)**, la API mantuvo el cumplimiento del SLA con latencia `p95 = 3 640 ms` (≤ 5 000 ms) y tasa de fallos de 1.18 % (≤ 5 %).
   - El punto de quiebre ocurrió al inicio de **Tier 2 (100 hilos)**, donde el `p95` ascendió a **8 771 ms** (superando el límite de 5 s) y la tasa de errores alcanzó **7.27 %** (superando el límite del 5 %), activando la compuerta de parada automática del Breaking Point Monitor.
   - En consecuencia, los escalones de mayor concurrencia (Tier 3 a Tier 5) no se ejecutaron para proteger la integridad del entorno local.

2. **Causa Raíz y Primer Error Observado:**
   - Durante la rampa hacia 100 hilos concurrentes, la alta concurrencia de inicios de sesión y pedidos de generación saturó el pool de conexiones de la base de datos PostgreSQL, generando errores 503 (`PersistenceUnavailableError`) en `POST /api/v1/sessions` y tiempos de respuesta elevados que dispararon el monitor de quiebre.

---

## 6. Tiempo de Recuperación del Sistema (`RRe-1-G`)

Inmediatamente después de cesar la carga de JMeter, se realizaron sondeos a `/health` (vía `http://127.0.0.1:8000/health`) para medir el tiempo necesario para operar en niveles nominales (HTTP 200 con latencia < 1 000 ms):

- **Sondeo 1 (+0.0 s tras fin de ráfaga):** Código `200 OK`, latencia = **33.4 ms** (< 1 000 ms).

El tiempo de recuperación medido es de **0.0 segundos**, cumpliendo de forma inmediata con la meta de recuperación en menos de 10 segundos.

---

## 7. Conclusión de Medidas ISO/IEC 25023

| Medida ISO/IEC 25023 | Definición / Fórmula | Valor Medido | Evaluación |
| :--- | :--- | :---: | :--- |
| **PCa-1-G**<br>Capacidad de procesamiento de transacciones | Peticiones por segundo del último escalón que cumple | **17.61 req/s** | Último escalón conforme: Tier 1 (50 hilos concurrentes) |
| **RRe-1-G**<br>Tiempo medio de recuperación | Segundos hasta que `/health` vuelve a responder 200 en `< 1 s` | **0.0 s** | Meta < 10 s superada ampliamente |

---

## 8. Corrida 2 (con QA-16)

- **Estado:** Pendiente.
- **Motivo:** En espera de la integración de la tarea QA-16 (Sergio), la cual implementa el middleware de protección contra denegación de servicio (rate limiting por IP y límite de tamaño de cuerpo). Una vez integrado dicho PR a `main`, se reejecutará esta misma batería para comparar el comportamiento de rechazo controlado (HTTP 429) y la preservación de CPU en la base de datos.

---

## 9. Archivos de Evidencia Adjuntos

- **Resumen por escalón (CSV):** [run1-tiers.csv](run1-tiers.csv)
- **Resumen por escalón (Markdown):** [run1-tiers.md](run1-tiers.md)
- **Estadísticas completas por ruta:** [run1-statistics.json](run1-statistics.json)
- **Monitoreo de contenedores Docker:** [run1-docker-stats.txt](run1-docker-stats.txt)
- **Reporte interactivo HTML de JMeter:** Generado en `backend/performance/jmeter/results/run1-report/`.
