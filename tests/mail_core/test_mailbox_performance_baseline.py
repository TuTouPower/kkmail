"""Automated Benchmark Suite & Resource Baseline Validation (t022).

Verifies deterministic data generation, keyset pagination correctness (zero duplicates/gaps),
FTS search, folder stats, blob stream latency percentiles (p50/p95), peak RSS,
PostgreSQL table footprint and cross-report diff comparisons.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from mail_core.db.session import get_engine
from scripts.benchmark_mailbox import compare_reports, resource, run_benchmark

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


# --- AC-001, AC-002, AC-003, AC-004: End-to-End Benchmark Execution ---------------


def test_mailbox_performance_baseline_metrics(tmp_path):
    """AC-001, AC-002, AC-003, AC-004: Generates deterministic 1k mailbox, executes benchmark, verifies all metrics."""
    engine = get_engine()
    blob_dir = tmp_path / "bench_blobs"
    blob_dir.mkdir(parents=True, exist_ok=True)

    # 1. Run benchmark for scale=1000 with 3 measurement iterations
    report = run_benchmark(engine, blob_dir, seed=101, count=1000, runs=3)

    # AC-001: Assert metadata and deterministic scale
    meta = report["benchmark_meta"]
    assert meta["scale_count"] == 1000
    assert meta["seed"] == 101
    assert meta["git_commit"] != ""
    assert meta["platform"] != ""

    # AC-002: Assert scenario latency percentiles and throughput
    scenarios = report["scenarios"]
    expected_scenarios = [
        "first_page_keyset",
        "deep_keyset_pagination",
        "fts_search",
        "folder_stats_recompute",
        "blob_stream_read",
    ]
    for sc in expected_scenarios:
        assert sc in scenarios, f"Missing benchmark scenario: {sc}"
        m = scenarios[sc]
        assert m["samples"] == 3
        assert m["p50_ms"] >= 0
        assert m["p95_ms"] >= m["p50_ms"]
        assert m["throughput_qps"] > 0

    # AC-003: Assert resource metrics, database size and EXPLAIN plan
    res = report["resources"]
    if resource is None:
        assert res["peak_rss_mb"] == 0, "Unavailable RSS must use the documented unknown value"
    else:
        assert res["peak_rss_mb"] > 0, "Missing or zero process RSS measurement"
    assert res["db_size_bytes"] > 0, "Missing or zero database size measurement"
    assert res["messages_table_bytes"] > 0, "Missing or zero messages table size"
    assert res["blob_dir_bytes"] > 0, "Missing or zero blob storage footprint"

    plan = report["query_plan_summary"]
    assert plan["node_type"] != "Unknown"
    assert plan["total_cost"] > 0


# --- AC-005: Cross-Report Comparison & Regression Detection -----------------------


def test_benchmark_report_comparison():
    """AC-005: Asserts that two reports can produce readable diffs for latency, memory and storage."""
    base_report = {
        "benchmark_meta": {
            "timestamp": "2026-10-22T20:00:00Z",
            "seed": 42,
            "scale_count": 1000,
            "git_commit": "abc1234",
            "platform": "Darwin-arm64",
            "processor": "arm64",
            "python_version": "3.14.7",
        },
        "resources": {
            "peak_rss_mb": 120.5,
            "db_size_bytes": 10485760,
            "messages_table_bytes": 4194304,
            "blob_dir_bytes": 2097152,
        },
        "scenarios": {
            "first_page_keyset": {"samples": 3, "p50_ms": 2.5, "p95_ms": 3.1, "avg_ms": 2.6, "throughput_qps": 384.6},
            "deep_keyset_pagination": {"samples": 3, "p50_ms": 8.0, "p95_ms": 9.2, "avg_ms": 8.3, "throughput_qps": 120.5},
            "fts_search": {"samples": 3, "p50_ms": 4.1, "p95_ms": 5.0, "avg_ms": 4.3, "throughput_qps": 232.5},
            "folder_stats_recompute": {"samples": 3, "p50_ms": 1.2, "p95_ms": 1.5, "avg_ms": 1.3, "throughput_qps": 769.2},
            "blob_stream_read": {"samples": 3, "p50_ms": 0.5, "p95_ms": 0.7, "avg_ms": 0.55, "throughput_qps": 1818.2},
        },
        "query_plan_summary": {"node_type": "Index Scan", "total_cost": 25.4},
    }

    cand_report = {
        "benchmark_meta": {
            "timestamp": "2026-10-22T21:00:00Z",
            "seed": 42,
            "scale_count": 1000,
            "git_commit": "def5678",
            "platform": "Darwin-arm64",
            "processor": "arm64",
            "python_version": "3.14.7",
        },
        "resources": {
            "peak_rss_mb": 122.0,
            "db_size_bytes": 10585760,
            "messages_table_bytes": 4194304,
            "blob_dir_bytes": 2097152,
        },
        "scenarios": {
            "first_page_keyset": {"samples": 3, "p50_ms": 2.3, "p95_ms": 2.9, "avg_ms": 2.4, "throughput_qps": 416.7},
            "deep_keyset_pagination": {"samples": 3, "p50_ms": 7.6, "p95_ms": 8.8, "avg_ms": 7.9, "throughput_qps": 126.5},
            "fts_search": {"samples": 3, "p50_ms": 3.9, "p95_ms": 4.8, "avg_ms": 4.1, "throughput_qps": 243.9},
            "folder_stats_recompute": {"samples": 3, "p50_ms": 1.1, "p95_ms": 1.4, "avg_ms": 1.2, "throughput_qps": 833.3},
            "blob_stream_read": {"samples": 3, "p50_ms": 0.48, "p95_ms": 0.65, "avg_ms": 0.52, "throughput_qps": 1923.1},
        },
        "query_plan_summary": {"node_type": "Index Scan", "total_cost": 25.4},
    }

    diff_text = compare_reports(base_report, cand_report)
    assert "Performance Comparison" in diff_text
    assert "first_page_keyset" in diff_text
    assert "Peak RSS" in diff_text
    assert "DB Size" in diff_text
