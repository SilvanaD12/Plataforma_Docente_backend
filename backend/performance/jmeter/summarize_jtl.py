"""Calcula métricas agregadas por escalón a partir de un archivo JTL de JMeter.

Genera run<N>-tiers.csv y run<N>-tiers.md en la carpeta indicada.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence


TIER_DEFINITIONS = [
    ("Tier 1", 50, "Tier-1-50-Threads"),
    ("Tier 2", 100, "Tier-2-100-Threads"),
    ("Tier 3", 200, "Tier-3-200-Threads"),
    ("Tier 4", 400, "Tier-4-400-Threads"),
    ("Tier 5", 800, "Tier-5-800-Threads"),
]


@dataclass
class TierMetrics:
    tier: str
    threads: int
    samples: int
    duration_s: float
    rps: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    error_pct: float
    error_count: int
    expected_429_pct: float
    expected_429_count: int
    sla_status: str


def is_expected_429(response_code: str) -> bool:
    return response_code.strip() == "429"


def is_server_or_network_error(response_code: str, success_str: str) -> bool:
    code = response_code.strip()
    success = success_str.strip().lower() == "true"
    if is_expected_429(code):
        return False
    if code.startswith("5"):
        return True
    if not success:
        return True
    return False


def calculate_percentile(sorted_values: Sequence[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    index = int(n * percentile)
    return sorted_values[min(index, n - 1)]


def format_thousand(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def format_ms(value: float) -> str:
    return f"{int(round(value)):,} ms".replace(",", " ")


def parse_jtl_file(jtl_path: Path) -> dict[str, list[dict[str, str]]]:
    grouped_rows: dict[str, list[dict[str, str]]] = {
        prefix: [] for _, _, prefix in TIER_DEFINITIONS
    }

    with open(jtl_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            thread_name = row.get("threadName", "").strip()
            for _, _, prefix in TIER_DEFINITIONS:
                if thread_name.startswith(prefix):
                    grouped_rows[prefix].append(row)
                    break

    return grouped_rows


def compute_tier_metrics(
    tier_name: str,
    threads: int,
    rows: list[dict[str, str]],
    p95_limit_ms: float = 5000.0,
    error_limit_pct: float = 5.0,
) -> TierMetrics:
    samples = len(rows)
    if samples == 0:
        return TierMetrics(
            tier=tier_name,
            threads=threads,
            samples=0,
            duration_s=0.0,
            rps=0.0,
            mean_ms=0.0,
            p50_ms=0.0,
            p95_ms=0.0,
            max_ms=0.0,
            error_pct=0.0,
            error_count=0,
            expected_429_pct=0.0,
            expected_429_count=0,
            sla_status="No ejecutado (parada automática)",
        )

    timestamps = [int(r["timeStamp"]) for r in rows if r.get("timeStamp")]
    elapsed_times = [float(r["elapsed"]) for r in rows if r.get("elapsed")]

    first_ts = min(timestamps) if timestamps else 0
    last_ts = max(timestamps) if timestamps else 0
    duration_s = (last_ts - first_ts) / 1000.0 if last_ts > first_ts else 0.0

    rps = samples / duration_s if duration_s > 0 else 0.0

    elapsed_sorted = sorted(elapsed_times)
    mean_ms = sum(elapsed_sorted) / samples if samples > 0 else 0.0
    p50_ms = calculate_percentile(elapsed_sorted, 0.50)
    p95_ms = calculate_percentile(elapsed_sorted, 0.95)
    max_ms = max(elapsed_sorted) if elapsed_sorted else 0.0

    error_count = 0
    expected_429_count = 0

    for r in rows:
        code = r.get("responseCode", "")
        success = r.get("success", "true")
        if is_expected_429(code):
            expected_429_count += 1
        elif is_server_or_network_error(code, success):
            error_count += 1

    error_pct = (error_count * 100.0) / samples
    expected_429_pct = (expected_429_count * 100.0) / samples

    if p95_ms > p95_limit_ms or error_pct > error_limit_pct:
        sla_status = "**Punto de quiebre alcanzado** (`p95 > 5 s`)"
    else:
        sla_status = "**Cumple SLA** (`p95 ≤ 5 s`, err `≤ 5 %`)"

    return TierMetrics(
        tier=tier_name,
        threads=threads,
        samples=samples,
        duration_s=duration_s,
        rps=rps,
        mean_ms=mean_ms,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        max_ms=max_ms,
        error_pct=error_pct,
        error_count=error_count,
        expected_429_pct=expected_429_pct,
        expected_429_count=expected_429_count,
        sla_status=sla_status,
    )


def summarize_jtl(
    jtl_path: Path | str,
    output_dir: Path | str,
) -> list[TierMetrics]:
    jtl_file = Path(jtl_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    match = re.search(r"run(\d+)", jtl_file.name, re.IGNORECASE)
    run_prefix = f"run{match.group(1)}" if match else jtl_file.stem

    grouped_rows = parse_jtl_file(jtl_file)

    metrics_list: list[TierMetrics] = []
    for tier_name, threads, prefix in TIER_DEFINITIONS:
        metrics = compute_tier_metrics(
            tier_name=tier_name,
            threads=threads,
            rows=grouped_rows.get(prefix, []),
        )
        metrics_list.append(metrics)

    csv_path = out_dir / f"{run_prefix}-tiers.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tier",
            "threads",
            "samples",
            "duration_s",
            "rps",
            "mean_ms",
            "p50_ms",
            "p95_ms",
            "max_ms",
            "error_pct",
            "error_count",
            "expected_429_pct",
            "expected_429_count",
            "sla_status",
        ])
        for m in metrics_list:
            writer.writerow([
                m.tier,
                m.threads,
                m.samples,
                f"{m.duration_s:.2f}",
                f"{m.rps:.2f}",
                f"{m.mean_ms:.2f}",
                f"{m.p50_ms:.2f}",
                f"{m.p95_ms:.2f}",
                f"{m.max_ms:.2f}",
                f"{m.error_pct:.2f}",
                m.error_count,
                f"{m.expected_429_pct:.2f}",
                m.expected_429_count,
                m.sla_status.replace("*", "").replace("`", ""),
            ])

    md_path = out_dir / f"{run_prefix}-tiers.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(
            "| Escalón (Tier) | Hilos concurrentes | Peticiones totales | Duración (s) | Throughput (RPS) | "
            "Latencia Media (ms) | Latencia P50 (ms) | Latencia P95 (ms) | Latencia Máx (ms) | "
            "Errores 5xx/Timeout (%) | 429 Esperados (%) | Estado SLA |\n"
        )
        f.write(
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n"
        )
        for m in metrics_list:
            if m.samples == 0:
                f.write(
                    f"| **{m.tier}** | {m.threads} | — | — | — | — | — | — | — | — | — | {m.sla_status} |\n"
                )
            else:
                p95_str = format_ms(m.p95_ms)
                p95_fmt = f"**{p95_str}**" if m.p95_ms > 5000.0 else p95_str
                f.write(
                    f"| **{m.tier}** | {m.threads} | {format_thousand(m.samples)} | {m.duration_s:.1f} s | "
                    f"{m.rps:.2f} req/s | {m.mean_ms:.1f} ms | {format_ms(m.p50_ms)} | {p95_fmt} | "
                    f"{format_ms(m.max_ms)} | {m.error_pct:.2f} % ({m.error_count}) | "
                    f"{m.expected_429_pct:.2f} % ({m.expected_429_count}) | {m.sla_status} |\n"
                )

    return metrics_list


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume resultados de JMeter agrupados por escalón.")
    parser.add_argument("--jtl", required=True, type=Path, help="Ruta al archivo JTL en formato CSV.")
    parser.add_argument("--out", required=True, type=Path, help="Carpeta de salida para CSV y MD.")
    args = parser.parse_args()

    summarize_jtl(args.jtl, args.out)
    print(f"Resumen generado exitosamente en {args.out}")


if __name__ == "__main__":
    main()
