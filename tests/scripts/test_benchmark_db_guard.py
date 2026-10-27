"""A73: benchmark CLI must refuse non-test targets before connecting."""
import pytest

import scripts.benchmark_mailbox as bench


def test_rejects_remote_host_even_with_test_db_name():
    with pytest.raises(ValueError, match="loopback|test|bench"):
        bench.validate_benchmark_db_url(
            "postgresql://u:p@db.prod.example:5432/kkmail_test_x"
        )


def test_rejects_loopback_with_production_db_name():
    with pytest.raises(ValueError, match="loopback|test|bench"):
        bench.validate_benchmark_db_url(
            "postgresql://u:p@127.0.0.1:5432/kkmail_production"
        )


def test_accepts_loopback_test_or_bench_db():
    bench.validate_benchmark_db_url("postgresql://u:p@127.0.0.1:5432/kkmail_test_x")
    bench.validate_benchmark_db_url("postgresql://u:p@localhost:5432/bench_mail")
    bench.validate_benchmark_db_url("postgresql://u:p@[::1]:5432/my_bench")


def test_allow_flag_overrides_guard():
    bench.validate_benchmark_db_url(
        "postgresql://u:p@db.prod.example/kkmail_production",
        allow_non_test_db=True,
    )


def test_main_exits_before_engine_creation_on_unsafe_url(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://u:p@db.prod.example/kkmail")
    monkeypatch.setattr("sys.argv", ["benchmark_mailbox.py"])

    def _boom(*a, **kw):
        raise AssertionError("create_engine must not be called for unsafe target")

    monkeypatch.setattr(bench, "create_engine", _boom)
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code == 2
