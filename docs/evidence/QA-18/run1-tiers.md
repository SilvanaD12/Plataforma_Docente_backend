| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | Latencia Media (ms) | Latencia P50 (ms) | Latencia P95 (ms) | Latencia Máx (ms) | Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tier 1** | 50 | 2 501 | 115.5 s | 21.66 req/s | 129.5 ms | 77 ms | 436 ms | 962 ms | 0.00 % (0) | 2.44 % (61) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 2** | 100 | 4 627 | 117.3 s | 39.43 req/s | 292.8 ms | 203 ms | 875 ms | 1 646 ms | 0.11 % (5) | 5.01 % (232) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 3** | 200 | 5 875 | 117.2 s | 50.12 req/s | 1604.6 ms | 1 451 ms | 3 236 ms | 7 568 ms | 0.07 % (4) | 3.86 % (227) | **Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`) |
| **Tier 4** | 400 | 1 126 | 30.6 s | 36.78 req/s | 5940.7 ms | 5 470 ms | **12 525 ms** | 14 268 ms | 0.00 % (0) | 0.80 % (9) | **Punto de quiebre alcanzado** (`p95 > 5 s`) |
| **Tier 5** | 800 | — | — | — | — | — | — | — | — | — | No ejecutado (parada automática) |
