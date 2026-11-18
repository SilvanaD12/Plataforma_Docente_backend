"""Unit tests for the JMeter JTL summarizer script (QA-18)."""
from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest

# Ensure performance/jmeter is importable
JMETER_DIR = Path(__file__).resolve().parents[2] / "performance" / "jmeter"
if str(JMETER_DIR) not in sys.path:
    sys.path.insert(0, str(JMETER_DIR))

import summarize_jtl  # noqa: E402


def create_sample_jtl_file(path: Path) -> None:
    headers = [
        "timeStamp",
        "elapsed",
        "label",
        "responseCode",
        "responseMessage",
        "threadName",
        "dataType",
        "success",
        "failureMessage",
        "bytes",
        "sentBytes",
        "grpThreads",
        "allThreads",
        "URL",
        "Latency",
        "IdleTime",
        "Connect",
    ]

    rows = [
        # Tier 1 samples: 10 samples over 2000 ms (2.0s) -> RPS = 5.0
        # 8 successes (200), 1 expected 429, 1 error (500)
        # Latencies: 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000
        ["1000", "100", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "100", "0", "1"],
        ["1200", "200", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "200", "0", "1"],
        ["1400", "300", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "300", "0", "1"],
        ["1600", "400", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "400", "0", "1"],
        ["1800", "500", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "500", "0", "1"],
        ["2000", "600", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "600", "0", "1"],
        ["2200", "700", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "700", "0", "1"],
        ["2400", "800", "GET /health", "200", "OK", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "800", "0", "1"],
        ["2600", "900", "POST /req", "429", "Too Many Requests", "Tier-1-50-Threads 1-1", "text", "true", "", "10", "10", "1", "1", "http://localhost", "900", "0", "1"],
        ["3000", "1000", "POST /req", "500", "Internal Server Error", "Tier-1-50-Threads 1-1", "text", "false", "Boom", "10", "10", "1", "1", "http://localhost", "1000", "0", "1"],

        # Tier 2 sample: 1 connection reset error
        ["4000", "6000", "GET /courses", "Non HTTP response", "Connection reset", "Tier-2-100-Threads 2-1", "text", "false", "Reset", "0", "0", "1", "1", "http://localhost", "0", "0", "1"],
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def test_summarize_jtl_computes_metrics_and_classifications(tmp_path: Path) -> None:
    jtl_file = tmp_path / "run1.jtl"
    out_dir = tmp_path / "evidence"
    create_sample_jtl_file(jtl_file)

    metrics = summarize_jtl.summarize_jtl(jtl_file, out_dir)

    assert len(metrics) == 5

    # Check Tier 1
    tier1 = metrics[0]
    assert tier1.tier == "Tier 1"
    assert tier1.threads == 50
    assert tier1.samples == 10
    # Duration: 3000 - 1000 = 2000 ms = 2.0s
    assert pytest.approx(tier1.duration_s, 0.01) == 2.0
    # RPS: 10 samples / 2.0s = 5.0 req/s
    assert pytest.approx(tier1.rps, 0.01) == 5.0
    # Mean latency: (100+200+300+400+500+600+700+800+900+1000) / 10 = 550.0 ms
    assert pytest.approx(tier1.mean_ms, 0.01) == 550.0
    # P50 (index 5): 600.0 ms
    assert tier1.p50_ms == 600.0
    # P95 (index 9): 1000.0 ms
    assert tier1.p95_ms == 1000.0
    # Errors: exactly 1 error (500)
    assert tier1.error_count == 1
    assert pytest.approx(tier1.error_pct, 0.01) == 10.0
    # Expected 429: exactly 1
    assert tier1.expected_429_count == 1
    assert pytest.approx(tier1.expected_429_pct, 0.01) == 10.0

    # Check Tier 2
    tier2 = metrics[1]
    assert tier2.tier == "Tier 2"
    assert tier2.threads == 100
    assert tier2.samples == 1
    assert tier2.error_count == 1
    assert tier2.p95_ms == 6000.0
    # Since p95_ms > 5000 and error_pct > 5%, breaking point is triggered
    assert "Punto de quiebre alcanzado" in tier2.sla_status

    # Check Tier 3 (empty tier)
    tier3 = metrics[2]
    assert tier3.tier == "Tier 3"
    assert tier3.samples == 0
    assert "No ejecutado" in tier3.sla_status

    # Check generated files
    csv_file = out_dir / "run1-tiers.csv"
    md_file = out_dir / "run1-tiers.md"
    assert csv_file.exists()
    assert md_file.exists()

    csv_content = csv_file.read_text(encoding="utf-8")
    assert "Tier 1,50,10" in csv_content

    md_content = md_file.read_text(encoding="utf-8")
    assert "| **Tier 1** | 50 | 10 |" in md_content
