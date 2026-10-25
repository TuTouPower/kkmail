#!/usr/bin/env python3
"""Deterministic Mailbox Performance Baseline & Resource Benchmark (t022).

Generates synthetic deterministically seeded mailboxes (1k, 10k, 100k scale),
executes benchmark operations (first page keyset, deep keyset pagination,
FTS search, folder stats, blob streaming), captures latency percentiles (p50/p95),
throughput, process RSS, PostgreSQL disk footprints, and EXPLAIN plans.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import resource
except ImportError:  # Windows does not provide the resource module.
    resource = None

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("benchmark")


def get_process_rss_mb() -> float:
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024.0 * 1024.0)  # bytes -> MB
    return usage / 1024.0  # KB -> MB


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)
        return res.stdout.strip()[:12] if res.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_dir_size_bytes(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(f.stat().st_size for f in directory.glob("**/*") if f.is_file())


def generate_benchmark_data(session: Session, blob_root: Path, *, seed: int = 42, count: int = 1000) -> dict:
    from mail_core.blobs.store import BlobStore
    from mail_core.mail.storage.folder_stats import recompute_folder_stats
    from mail_core.mail.storage.models import (
        Account,
        Attachment,
        Folder,
        Message,
        MessageBlob,
        MessageBlobLink,
        MessageBody,
        MessageLocation,
    )
    from mail_core.search.index import upsert_message_search

    store = BlobStore(blob_root)
    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    # 1 Account, 1 Inbox
    acc_id = uuid.uuid5(uuid.NAMESPACE_URL, f"bench-account-{seed}")
    acc = Account(id=acc_id, email=f"bench-user-{seed}@example.test", provider="memory")
    session.add(acc)
    session.flush()

    inbox_id = uuid.uuid5(uuid.NAMESPACE_URL, f"bench-inbox-{seed}")
    inbox = Folder(id=inbox_id, account_id=acc.id, remote_id="INBOX", name="收件箱", role="inbox")
    session.add(inbox)
    session.flush()

    # Pre-generate a shared small payload to avoid disk bloat for metadata benchmarking
    sample_blob_payload = b"Sample benchmark payload bytes 1234567890"
    w_blob = store.put(sample_blob_payload)
    shared_mb = MessageBlob(
        content_sha256=w_blob.content_sha256,
        key_version=w_blob.key_version,
        size_bytes=w_blob.size_bytes,
        storage_path=w_blob.storage_path,
    )
    session.add(shared_mb)
    session.flush()

    batch_size = 500
    all_msg_ids = []
    keywords = ["项目审计", "季度财务", "合同签约", "安全凭证", "系统上线", "常规邮件"]

    for i in range(count):
        mid = uuid.uuid5(uuid.NAMESPACE_URL, f"bench-msg-{seed}-{i}")
        sort_t = base_time - timedelta(minutes=i)
        kw = keywords[i % len(keywords)]
        subj = f"[{kw}] 业务通知 {seed}-{i}"
        msg = Message(
            id=mid,
            account_id=acc.id,
            remote_id=f"r-{i}",
            internet_message_id=f"<bench-{seed}-{i}@test.com>",
            subject=subj,
            from_address="sender@company.test",
            sort_time=sort_t,
            is_read=i % 3 == 0,
            is_flagged=i % 10 == 0,
            has_attachments=i % 5 == 0,
        )
        session.add(msg)
        session.flush()

        session.add(MessageLocation(id=uuid.uuid5(uuid.NAMESPACE_URL, f"loc-{seed}-{i}"), message_id=mid, folder_id=inbox.id, uid=i + 1))
        body_text = f"这里是关于 {kw} 的重要细节说明内容 {i}。"
        session.add(MessageBody(message_id=mid, text_plain=body_text, text_html=f"<p>{body_text}</p>"))
        session.add(MessageBlobLink(message_id=mid, blob_id=shared_mb.id))

        if i % 5 == 0:
            att = Attachment(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"att-{seed}-{i}"),
                message_id=mid,
                blob_id=shared_mb.id,
                filename=f"附件_{i}.dat",
                content_type="application/octet-stream",
                size_bytes=len(sample_blob_payload),
                part_id="1",
            )
            session.add(att)

        upsert_message_search(session, message_id=mid, body_text=body_text)
        all_msg_ids.append(mid)

        if (i + 1) % batch_size == 0:
            session.flush()

    session.flush()
    recompute_folder_stats(session, inbox.id)
    session.commit()

    return {
        "account_id": acc.id,
        "folder_id": inbox.id,
        "count": count,
        "shared_blob_sha256": w_blob.content_sha256,
    }


def measure_latencies(func, runs: int = 3, warmup: int = 1) -> dict:
    for _ in range(warmup):
        func()
    latencies_ms = []
    for _ in range(runs):
        t0 = time.perf_counter()
        func()
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
    latencies_ms.sort()
    p50 = latencies_ms[len(latencies_ms) // 2]
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    avg = sum(latencies_ms) / len(latencies_ms)
    throughput = (1000.0 / avg) if avg > 0 else 0
    return {
        "samples": runs,
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "avg_ms": round(avg, 3),
        "throughput_qps": round(throughput, 1),
    }


def run_benchmark(engine, blob_root: Path, *, seed: int = 42, count: int = 1000, runs: int = 3) -> dict:
    from mail_core.blobs.store import BlobStore
    from mail_core.mail.application.queries import list_messages_keyset
    from mail_core.mail.storage.folder_stats import recompute_folder_stats
    from mail_core.search.index import search_messages

    Session = sessionmaker(bind=engine)
    with Session() as session:
        meta = generate_benchmark_data(session, blob_root, seed=seed, count=count)

    folder_id = meta["folder_id"]
    account_id = meta["account_id"]
    blob_store = BlobStore(blob_root)

    # 1. First Page Keyset Query
    def query_first_page():
        with Session() as session:
            page = list_messages_keyset(session, folder_ids=[folder_id], limit=50, sort_order="desc")
            assert len(page.items) == 50
            return page.next_cursor

    first_page_metrics = measure_latencies(query_first_page, runs=runs)

    # 2. Deep Keyset Pagination (step 5 pages)
    def query_deep_keyset():
        with Session() as session:
            cursor = None
            total_fetched = 0
            for _ in range(5):
                page = list_messages_keyset(session, folder_ids=[folder_id], limit=50, cursor=cursor, sort_order="desc")
                total_fetched += len(page.items)
                cursor = page.next_cursor
                if not cursor:
                    break
            assert total_fetched == 250

    deep_keyset_metrics = measure_latencies(query_deep_keyset, runs=runs)

    # 3. FTS Search
    def query_search():
        with Session() as session:
            res = search_messages(session, account_ids=[account_id], query="财务", limit=20)
            assert len(res) > 0

    search_metrics = measure_latencies(query_search, runs=runs)

    # 4. Folder Stats Recomputation
    def query_stats():
        with Session() as session:
            recompute_folder_stats(session, folder_id)

    stats_metrics = measure_latencies(query_stats, runs=runs)

    # 5. Blob Plaintext Retrieval
    def fetch_blob():
        data = blob_store.get(meta["shared_blob_sha256"])
        assert len(data) > 0

    blob_metrics = measure_latencies(fetch_blob, runs=runs)

    # Query Plan (EXPLAIN)
    with engine.connect() as conn:
        explain_sql = text("""
            EXPLAIN (FORMAT JSON)
            SELECT messages.id, messages.sort_time
            FROM messages
            JOIN message_locations ON message_locations.message_id = messages.id
            WHERE message_locations.folder_id = :fid
            ORDER BY messages.sort_time DESC, messages.id DESC
            LIMIT 50
        """)
        plan = conn.execute(explain_sql, {"fid": folder_id}).scalar()
        db_size_bytes = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()
        messages_table_size = conn.execute(text("SELECT pg_total_relation_size('messages')")).scalar()

    rss_mb = get_process_rss_mb()
    blob_dir_size = get_dir_size_bytes(blob_root)

    report = {
        "benchmark_meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "scale_count": count,
            "git_commit": get_git_commit(),
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "python_version": sys.version.split()[0],
        },
        "resources": {
            "peak_rss_mb": round(rss_mb, 2),
            "db_size_bytes": db_size_bytes,
            "messages_table_bytes": messages_table_size,
            "blob_dir_bytes": blob_dir_size,
        },
        "scenarios": {
            "first_page_keyset": first_page_metrics,
            "deep_keyset_pagination": deep_keyset_metrics,
            "fts_search": search_metrics,
            "folder_stats_recompute": stats_metrics,
            "blob_stream_read": blob_metrics,
        },
        "query_plan_summary": {
            "node_type": plan[0]["Plan"]["Node Type"] if plan else "Unknown",
            "total_cost": plan[0]["Plan"]["Total Cost"] if plan else 0,
        },
    }
    return report


def compare_reports(base_report: dict, candidate_report: dict) -> str:
    lines = [
        "========================= Performance Comparison =========================",
        f"Base Commit: {base_report['benchmark_meta']['git_commit']} | Scale: {base_report['benchmark_meta']['scale_count']}",
        f"Candidate:   {candidate_report['benchmark_meta']['git_commit']} | Scale: {candidate_report['benchmark_meta']['scale_count']}",
        "--------------------------------------------------------------------------",
    ]
    # Check platform match
    b_plat = base_report["benchmark_meta"]["platform"]
    c_plat = candidate_report["benchmark_meta"]["platform"]
    if b_plat != c_plat:
        lines.append(f"WARNING: Different host platforms ({b_plat} vs {c_plat}). Do not use for raw SLA evaluation.")

    # Scenarios diff
    lines.append(f"{'Scenario':<25} {'Base p50 (ms)':<15} {'Cand p50 (ms)':<15} {'Diff %':<10}")
    for sc, b_vals in base_report["scenarios"].items():
        c_vals = candidate_report["scenarios"].get(sc, {})
        b_p50 = b_vals.get("p50_ms", 0)
        c_p50 = c_vals.get("p50_ms", 0)
        diff_pct = ((c_p50 - b_p50) / b_p50 * 100.0) if b_p50 > 0 else 0.0
        lines.append(f"{sc:<25} {b_p50:<15.3f} {c_p50:<15.3f} {diff_pct:>+7.2f}%")

    # Resource diff
    lines.append("--------------------------------------------------------------------------")
    b_rss = base_report["resources"]["peak_rss_mb"]
    c_rss = candidate_report["resources"]["peak_rss_mb"]
    lines.append(f"Peak RSS: Base {b_rss} MB -> Candidate {c_rss} MB ({c_rss - b_rss:+.2f} MB)")
    b_db = base_report["resources"]["db_size_bytes"] / (1024 * 1024)
    c_db = candidate_report["resources"]["db_size_bytes"] / (1024 * 1024)
    lines.append(f"DB Size:  Base {b_db:.2f} MB -> Candidate {c_db:.2f} MB ({c_db - b_db:+.2f} MB)")
    lines.append("==========================================================================")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Mailbox performance baseline runner")
    parser.add_argument("--scale", type=int, default=1000, help="Number of messages to seed")
    parser.add_argument("--runs", type=int, default=3, help="Measurement iterations")
    parser.add_argument("--out", type=str, default=".scratch/benchmark_report.json", help="Output report JSON path")
    parser.add_argument("--compare", nargs=2, metavar=("BASE", "CAND"), help="Compare two report JSON files")
    args = parser.parse_args()

    if args.compare:
        b_path = Path(args.compare[0])
        c_path = Path(args.compare[1])
        b_data = json.loads(b_path.read_text(encoding="utf-8"))
        c_data = json.loads(c_path.read_text(encoding="utf-8"))
        print(compare_reports(b_data, c_data))
        return

    db_url = os.environ.get("MAIL_CORE_DATABASE_URL")
    if not db_url:
        print("MAIL_CORE_DATABASE_URL required for benchmark", file=sys.stderr)
        sys.exit(2)

    blob_dir = ROOT / ".scratch" / f"bench_blobs_{uuid.uuid4().hex[:8]}"
    blob_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(db_url)

    try:
        print(f"Starting mailbox benchmark scale={args.scale}...")
        report = run_benchmark(engine, blob_dir, seed=42, count=args.scale, runs=args.runs)
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report written to {out_p}")
        print(json.dumps(report["scenarios"], indent=2))
    finally:
        shutil.rmtree(blob_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
