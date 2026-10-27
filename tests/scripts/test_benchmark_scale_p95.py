"""A101: --scale/--runs lower bounds and nearest-rank p95."""
import pytest

import scripts.benchmark_mailbox as bench


def test_nearest_rank_p95():
    values = list(range(1, 21))  # 1..20, nearest-rank p95 = rank ceil(.95*20)=19
    assert bench._nearest_rank(values, 95) == 19
    assert bench._nearest_rank(values, 50) == 10
    assert bench._nearest_rank([7], 95) == 7
    assert bench._nearest_rank([1, 2, 3], 95) == 3


def test_measure_latencies_marks_p95_as_max_when_few_samples(monkeypatch):
    ticks = iter([0.0, 0.001] * 10)
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(ticks))
    metrics = bench.measure_latencies(lambda: None, runs=3, warmup=1)
    assert metrics["p95_ms"] == 1.0
    assert metrics.get("p95_is_max") is True


def test_measure_latencies_no_max_mark_with_enough_samples(monkeypatch):
    ticks = iter([float(i) for i in range(100)])
    monkeypatch.setattr(bench.time, "perf_counter", lambda: next(ticks))
    metrics = bench.measure_latencies(lambda: None, runs=20, warmup=1)
    assert "p95_is_max" not in metrics


@pytest.mark.parametrize("argv", [
    ["benchmark_mailbox.py", "--scale", "100"],
    ["benchmark_mailbox.py", "--scale", "249"],
    ["benchmark_mailbox.py", "--runs", "0"],
    ["benchmark_mailbox.py", "--runs", "-1"],
])
def test_main_rejects_too_small_scale_or_runs(monkeypatch, argv):
    monkeypatch.setenv(
        "MAIL_CORE_DATABASE_URL", "postgresql://u:p@127.0.0.1/kkmail_test_x"
    )
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(
        bench, "create_engine",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("engine must not be created for invalid scale/runs")
        ),
    )
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code == 2
