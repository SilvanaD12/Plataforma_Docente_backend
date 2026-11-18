"""Service recovery measurement script for QA-18 (RRe-1-G).

Polls a target URL (typically /health) once per second for a specified duration
immediately following a load/stress test run, recording the timestamp, HTTP status
code, and latency in milliseconds for each probe.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import time
import urllib.error
import urllib.request


def probe_endpoint(url: str, timeout: float = 5.0) -> tuple[int, float]:
    """Execute a single HTTP GET probe and return (status_code, latency_ms)."""
    t0 = time.perf_counter()
    status_code = 0
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "QA-18-Recovery-Monitor/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
    except urllib.error.HTTPError as exc:
        status_code = exc.code
    except urllib.error.URLError:
        status_code = 0
    except Exception:
        status_code = 0
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return status_code, latency_ms


def run_recovery_monitoring(
    url: str = "http://127.0.0.1:8000/health",
    duration_s: int = 60,
    interval_s: float = 1.0,
    threshold_latency_ms: float = 1000.0,
) -> tuple[list[dict], float]:
    """Run sequential probes for duration_s and return (records, recovery_time_s)."""
    records = []
    start_time = time.perf_counter()
    recovery_time_s: float | None = None

    for i in range(duration_s):
        loop_start = time.perf_counter()
        elapsed_s = loop_start - start_time
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status_code, latency_ms = probe_endpoint(url)
        is_nominal = (status_code == 200) and (latency_ms < threshold_latency_ms)

        if is_nominal and recovery_time_s is None:
            # If the first probe is nominal, recovery time is 0.0 s
            recovery_time_s = 0.0 if i == 0 else max(round(elapsed_s, 2), round(i * interval_s, 2))

        record = {
            "probe": i + 1,
            "timestamp": timestamp_str,
            "elapsed_s": round(elapsed_s, 2),
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "nominal": is_nominal,
        }
        records.append(record)

        # Sleep remaining time to align with next interval
        spent = time.perf_counter() - loop_start
        sleep_time = max(0.0, interval_s - spent)
        if i < duration_s - 1:
            time.sleep(sleep_time)

    if recovery_time_s is None:
        recovery_time_s = float(duration_s)

    return records, recovery_time_s


def write_recovery_report(records: list[dict], recovery_time_s: float, output_path: Path, url: str) -> None:
    """Format and write probe records to an evidence text file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Evidencia de Recuperacion del Servicio — QA-18 (RRe-1-G)",
        f"# Fecha y hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# URL monitoreada: {url}",
        f"# Duracion total del sondeo: {len(records)} s (1 sondeo/s)",
        f"# Criterio nominal: HTTP 200 con latencia < 1000 ms",
        f"# RRe-1-G (Tiempo medio de recuperacion): {recovery_time_s:.2f} s",
        "#",
        f"{'Sondeo':<8}{'Hora':<22}{'Offset':<12}{'HTTP':<8}{'Latencia':<16}{'Nominal':<10}",
        "-" * 76,
    ]
    for r in records:
        nominal_str = "SI" if r["nominal"] else "NO"
        lines.append(
            f"{r['probe']:<8}{r['timestamp']:<22}+{r['elapsed_s']:.1f} s{'':<6}{r['status_code']:<8}{r['latency_ms']:.1f} ms{'':<8}{nominal_str:<10}"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor /health recovery after stress test (QA-18 RRe-1-G)")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health", help="Target URL to probe")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds (default: 60)")
    parser.add_argument("--interval", type=float, default=1.0, help="Interval in seconds (default: 1.0)")
    parser.add_argument("--out", required=True, help="Output file path (e.g. docs/evidence/QA-18/run1-recovery.txt)")
    args = parser.parse_args()

    out_path = Path(args.out)
    records, recovery_time_s = run_recovery_monitoring(
        url=args.url,
        duration_s=args.duration,
        interval_s=args.interval,
    )
    write_recovery_report(records, recovery_time_s, out_path, args.url)
    print(f"Recovery monitoring completed: RRe-1-G = {recovery_time_s:.2f} s. Report written to {out_path}")


if __name__ == "__main__":
    main()
