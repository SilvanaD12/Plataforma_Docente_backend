| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | Latencia Media (ms) | Latencia P50 (ms) | Latencia P95 (ms) | Latencia Máx (ms) | Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | 50 | 2 042 | 116.0 s | 17.61 req/s | 602.1 ms | 157 ms | 3 640 ms | 9 070 ms | 1.18 % (24) | 3.53 % (72) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 2** | 100 | 55 | 9.2 s | 5.98 req/s | 2207.7 ms | 803 ms | **8 771 ms** | 10 579 ms | 7.27 % (4) | 0.00 % (0) | **Punto de quiebre alcanzado** (`p95 > 5 s`) |
| **Tier 3** | 200 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
| **Tier 4** | 400 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
| **Tier 5** | 800 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
