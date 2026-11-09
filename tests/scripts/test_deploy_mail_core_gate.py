"""Deploy gate tests: preflight ordering, fail-fast behavior, and entrypoint structure.

Uses stub executables on PATH for git/docker/curl/rg while the preflight
gate itself always runs the real ``python -m mail_core --check-migrations``
against throwaway SQLite databases. Never touches production databases.
"""

from __future__ import annotations

import ast
import os
import stat
import subprocess
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_mail_core.sh"
PREFLIGHT_LIB = REPO_ROOT / "scripts" / "lib" / "preflight_schema_gate.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.mail-core.yml"
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"


def _run_bash(script: str, *, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    merged = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(cwd or REPO_ROOT),
        env=merged,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_stub_bin(stub_dir: Path, markers: Path) -> None:
    stub_dir.mkdir(parents=True, exist_ok=True)
    markers.mkdir(parents=True, exist_ok=True)
    _write_stub(
        stub_dir / "git",
        f"""MARKERS={markers}
        case "$1" in
          branch) echo "main" ;;
          status) : ;;
          fetch|merge-base|rev-parse) : ;;
          push) touch "$MARKERS/push" ;;
          *) : ;;
        esac
        exit 0""",
    )
    _write_stub(
        stub_dir / "docker",
        f"""MARKERS={markers}
        echo "$*" >> "$MARKERS/docker-calls.log"
        if [[ "$1" == "context" ]]; then
          echo "${{EXPECTED_DOCKER_CONTEXT:-orbstack}}"
          exit 0
        fi
        if [[ "$1" == "rm" ]]; then
          exit 0
        fi
        case " $* " in
          *push*) touch "$MARKERS/docker-push" ;;
          *build*) touch "$MARKERS/docker-build" ;;
          *" up "*|*" run "*|*" stop "*|*" cp "*|*" exec "*) touch "$MARKERS/docker-mutate" ;;
        esac
        exit 0""",
    )
    _write_stub(stub_dir / "curl", "exit 0")
    _write_stub(stub_dir / "rg", "exit 0")


def test_preflight_lib_source_has_no_side_effects():
    """Sourcing the lib defines the gate function and does nothing else."""
    proc = _run_bash(
        f"source {PREFLIGHT_LIB} && declare -F && echo SOURCE-OK",
        env={"MAIL_CORE_DATABASE_URL": "sqlite:////tmp/x.db"},
    )
    assert proc.returncode == 0, proc.stderr
    assert "mail_core_preflight_check" in proc.stdout
    assert "SOURCE-OK" in proc.stdout


def test_preflight_check_delegates_to_check_migrations(tmp_path: Path):
    """Gate success/failure follows the stub python exit code; credentials stay in env."""
    calls = tmp_path / "python-calls.log"
    stub_python = tmp_path / "stub-python"
    _write_stub(
        stub_python,
        f"""echo "ARGS:$*" >> {calls}
        echo "HAS_URL:${{MAIL_CORE_DATABASE_URL:+yes}}" >> {calls}
        echo "PYTHONPATH:$PYTHONPATH" >> {calls}
        exit "${{STUB_PYTHON_EXIT:-0}}" """,
    )
    secret_url = "postgresql+psycopg://kkmail:s3cr3t-pw@127.0.0.1:5433/kkmail_mail"
    proc = _run_bash(
        f"source {PREFLIGHT_LIB} && mail_core_preflight_check {REPO_ROOT} {stub_python}",
        env={"MAIL_CORE_DATABASE_URL": secret_url, "STUB_PYTHON_EXIT": "0"},
    )
    assert proc.returncode == 0, proc.stderr
    logged = calls.read_text(encoding="utf-8")
    assert "-m mail_core --check-migrations" in logged.replace("ARGS:", "")
    assert "HAS_URL:yes" in logged
    assert str(REPO_ROOT / "src") in logged
    assert "s3cr3t-pw" not in proc.stdout + proc.stderr + logged

    proc = _run_bash(
        f"source {PREFLIGHT_LIB} && mail_core_preflight_check {REPO_ROOT} {stub_python}",
        env={"MAIL_CORE_DATABASE_URL": secret_url, "STUB_PYTHON_EXIT": "3"},
    )
    assert proc.returncode == 3


def test_preflight_check_requires_url_from_environment(tmp_path: Path):
    """Without MAIL_CORE_DATABASE_URL the gate fails before invoking python."""
    calls = tmp_path / "python-calls.log"
    stub_python = tmp_path / "stub-python"
    _write_stub(stub_python, f"echo CALLED >> {calls}\nexit 0")
    proc = _run_bash(
        f"unset MAIL_CORE_DATABASE_URL; source {PREFLIGHT_LIB} && mail_core_preflight_check {REPO_ROOT} {stub_python}"
    )
    assert proc.returncode != 0
    assert not calls.exists()


def test_deploy_script_gate_runs_before_push_and_no_bare_alembic():
    """Static ordering: gate < push < backup < stop < foreground migrate < up api worker."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    gate_at = text.index("mail_core_preflight_check")
    push_at = text.index("git push origin main")
    backup_at = text.index("mail_core.backup.export")
    stop_at = text.index("stop api worker")
    migrate_at = text.index("--exit-code-from migrate")
    up_at = text.index("up -d api worker")
    assert gate_at < push_at < backup_at < stop_at < migrate_at < up_at
    assert "alembic" not in text


def test_migrate_wrapper_defines_no_business_logic():
    """The offline script is a thin wrapper: only main(), no moved constants/functions."""
    tree = ast.parse((REPO_ROOT / "scripts" / "migrate_to_unified_baseline.py").read_text(encoding="utf-8"))
    functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert functions == ["main"]
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    defined = {n.targets[0].id for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    for legacy_name in (
        "UNIFIED_BASELINE_REVISION",
        "KNOWN_LEGACY_REVISIONS",
        "REQUIRED_TABLES",
        "REQUIRED_COLUMNS",
        "CORE_CRITICAL_TABLES",
    ):
        assert legacy_name not in defined


def test_compose_migrate_service_uses_single_guarded_entrypoint():
    """The migrate service runs python -m mail_core --migrate-only; no bare alembic anywhere."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert compose["services"]["migrate"]["command"] == ["python", "-m", "mail_core", "--migrate-only"]
    assert "alembic" not in COMPOSE_FILE.read_text(encoding="utf-8")
    api_command = " ".join(compose["services"]["api"]["command"])
    assert "--migrate-only" not in api_command
    assert "--check-migrations" not in api_command


def _business_table_db(path: Path) -> str:
    db_url = f"sqlite:///{path}"
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE accounts (id VARCHAR(64) PRIMARY KEY)"))
    finally:
        engine.dispose()
    return db_url


def test_deploy_fails_before_push_when_gate_fails(tmp_path: Path):
    """Gate failure: real script exits non-zero with no push/build/backup/migrate markers."""
    stub_dir = tmp_path / "bin"
    markers = tmp_path / "markers"
    _make_stub_bin(stub_dir, markers)
    db_url = _business_table_db(tmp_path / "gate-fail.db")
    env = {
        "PATH": f"{stub_dir}:{os.environ['PATH']}",
        "POSTGRES_PASSWORD": "valid-pw_123",
        "MAIL_CORE_DATABASE_URL": db_url,
    }
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=str(REPO_ROOT),
        env={**{"PATH": env["PATH"], "HOME": os.environ.get("HOME", "/tmp")}, **{k: v for k, v in env.items() if k != "PATH"}},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode != 0
    assert "preflight schema check failed" in proc.stderr
    assert not (markers / "push").exists()
    assert not (markers / "docker-push").exists()
    assert not (markers / "docker-build").exists()
    assert not (markers / "docker-mutate").exists()
    calls_log = markers / "docker-calls.log"
    if calls_log.exists():
        logged = calls_log.read_text(encoding="utf-8")
        assert "push" not in logged
        assert "build" not in logged
        assert " up " not in logged
        assert " run " not in logged


def test_deploy_gate_pass_proceeds_but_backup_failure_never_migrates(tmp_path: Path):
    """Gate pass reaches push; a later backup failure still never starts migrate/up."""
    stub_dir = tmp_path / "bin"
    markers = tmp_path / "markers"
    _make_stub_bin(stub_dir, markers)
    db_url = f"sqlite:///{tmp_path / 'gate-pass.db'}"
    env_path = f"{stub_dir}:{os.environ['PATH']}"
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--no-push"],
        cwd=str(REPO_ROOT),
        env={
            "PATH": env_path,
            "HOME": os.environ.get("HOME", "/tmp"),
            "POSTGRES_PASSWORD": "valid-pw_123",
            "MAIL_CORE_DATABASE_URL": db_url,
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode != 0
    logged = (markers / "docker-calls.log").read_text(encoding="utf-8") if (markers / "docker-calls.log").exists() else ""
    assert "config" in logged
    assert " up " not in logged
    assert "migrate" not in logged
