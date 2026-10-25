from __future__ import annotations

import scripts.benchmark_mailbox as benchmark_mailbox


def test_process_rss_is_unknown_without_resource_module(monkeypatch):
    monkeypatch.setattr(benchmark_mailbox, "resource", None)

    assert benchmark_mailbox.get_process_rss_mb() == 0.0
