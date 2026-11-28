"""Tests for Q1 compose topology exclusivity, /tmp tmpfs, and safe mode switching."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EMBEDDED_COMPOSE = REPO_ROOT / "docker-compose.embedded.yml"
DISTRIBUTED_COMPOSE = REPO_ROOT / "docker-compose.mail-core.yml"
DEPLOY_EMBEDDED = REPO_ROOT / "scripts" / "deploy_embedded.sh"
DEPLOY_DISTRIBUTED = REPO_ROOT / "scripts" / "deploy_mail_core.sh"
DEPLOYMENT_DOC = REPO_ROOT / "docs" / "guides" / "deployment.md"

_DUMMY_COMPOSE_ENV = {
    "POSTGRES_PASSWORD": "test_pg_password_123",
    "MAIL_CORE_SECRET_KEY": "test_secret_key_for_compose_config_123456",
    "MAIL_CORE_BLOB_KEY_V1": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    "MAIL_CORE_BACKUP_KEY": "ZmVkY2JhOTg3NjU0MzIxMGZlZGNiYTk4NzY1NDMyMTA=",
}


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -Eeuo pipefail\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _compose_config(compose_file: Path, *, extra_args: list[str] | None = None, env_overrides: dict[str, str] | None = None) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not installed")
    env = {**os.environ, **_DUMMY_COMPOSE_ENV}
    if env_overrides:
        env.update(env_overrides)
    cmd = ["docker", "compose", "-f", str(compose_file), *(extra_args or []), "config"]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"{' '.join(cmd)} failed:\n{proc.stderr}"
    return yaml.safe_load(proc.stdout)


def test_distributed_compose_hardcodes_api_flags_and_removes_override_comment():
    raw_text = DISTRIBUTED_COMPOSE.read_text(encoding="utf-8")
    assert "${MAIL_CORE_EMBEDDED_WORKER" not in raw_text
    assert "${MAIL_CORE_SKIP_MIGRATIONS" not in raw_text
    assert "Standalone single-process override" not in raw_text

    raw_doc = yaml.safe_load(raw_text)
    api_env = raw_doc["services"]["api"]["environment"]
    assert api_env["MAIL_CORE_SKIP_MIGRATIONS"] == "1"
    assert api_env["MAIL_CORE_EMBEDDED_WORKER"] == "0"

    rendered = _compose_config(
        DISTRIBUTED_COMPOSE,
        extra_args=["--profile", "distributed"],
        env_overrides={
            "MAIL_CORE_EMBEDDED_WORKER": "1",
            "MAIL_CORE_SKIP_MIGRATIONS": "0",
        },
    )
    rendered_env = rendered["services"]["api"]["environment"]
    assert str(rendered_env["MAIL_CORE_EMBEDDED_WORKER"]) == "0"
    assert str(rendered_env["MAIL_CORE_SKIP_MIGRATIONS"]) == "1"


def test_both_compose_files_declare_tmpfs_and_fixed_topology():
    embedded_raw = yaml.safe_load(EMBEDDED_COMPOSE.read_text(encoding="utf-8"))
    distributed_raw = yaml.safe_load(DISTRIBUTED_COMPOSE.read_text(encoding="utf-8"))

    assert embedded_raw["services"]["postgres"]["container_name"] == "kkmail-mail-core-pg"
    assert embedded_raw["services"]["app"]["container_name"] == "kkmail-mail-core-app"
    assert distributed_raw["services"]["postgres"]["container_name"] == "kkmail-mail-core-pg"
    assert distributed_raw["services"]["api"]["container_name"] == "kkmail-mail-core-api"
    assert distributed_raw["services"]["worker"]["container_name"] == "kkmail-mail-core-worker"

    assert embedded_raw["services"]["postgres"]["ports"] == ["127.0.0.1:5433:5432"]
    assert distributed_raw["services"]["postgres"]["ports"] == ["127.0.0.1:5433:5432"]
    assert "37281:8000" in embedded_raw["services"]["app"]["ports"][0]
    assert "37281:8000" in distributed_raw["services"]["api"]["ports"][0]
    assert set(embedded_raw["volumes"]) == {"kkmail_mail_core_pg", "kkmail_mail_core_blobs"}
    assert set(distributed_raw["volumes"]) == {"kkmail_mail_core_pg", "kkmail_mail_core_blobs"}

    assert embedded_raw["services"]["app"].get("tmpfs") == ["/tmp:rw,nosuid,nodev,size=16m"]
    assert distributed_raw["services"]["api"].get("tmpfs") == ["/tmp:rw,nosuid,nodev,size=16m"]
    assert distributed_raw["services"]["worker"].get("tmpfs") == ["/tmp:rw,nosuid,nodev,size=16m"]

    embedded_rendered = _compose_config(EMBEDDED_COMPOSE)
    distributed_rendered = _compose_config(DISTRIBUTED_COMPOSE, extra_args=["--profile", "distributed"])
    for service_cfg in (
        embedded_rendered["services"]["app"],
        distributed_rendered["services"]["api"],
        distributed_rendered["services"]["worker"],
    ):
        tmpfs_list = service_cfg.get("tmpfs") or []
        assert any(str(entry).startswith("/tmp") for entry in tmpfs_list), service_cfg


def test_deploy_embedded_builds_before_retiring_compute_and_preserves_postgres(tmp_path: Path):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    call_log = tmp_path / "calls.log"

    _write_executable(
        stub_bin / "docker",
        f"""
echo "docker $*" >> "{call_log}"
if [[ "$1" == "compose" ]]; then
  case " $* " in
    *" config --quiet "*) exit 0 ;;
    *" config --services "*) printf 'postgres\\napp\\n'; exit 0 ;;
    *" build app "*) exit 0 ;;
    *" up -d"*) exit 0 ;;
  esac
fi
if [[ "$1" == "inspect" ]]; then
  if [[ "$2" == "kkmail-mail-core-api" || "$2" == "kkmail-mail-core-worker" ]]; then
    exit 0
  fi
  exit 1
fi
exit 0
""",
    )
    _write_executable(
        stub_bin / "curl",
        f"""
echo "curl $*" >> "{call_log}"
exit 0
""",
    )
    _write_executable(
        stub_bin / "rg",
        """
exec grep -E "$@"
""",
    )

    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        **_DUMMY_COMPOSE_ENV,
    }
    proc = subprocess.run(
        ["bash", str(DEPLOY_EMBEDDED)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    lines = call_log.read_text(encoding="utf-8").splitlines()

    build_idx = next(i for i, line in enumerate(lines) if "compose -f docker-compose.embedded.yml build app" in line)
    stop_api_idx = next(i for i, line in enumerate(lines) if line == "docker stop kkmail-mail-core-api")
    rm_api_idx = next(i for i, line in enumerate(lines) if line == "docker rm -f kkmail-mail-core-api")
    stop_worker_idx = next(i for i, line in enumerate(lines) if line == "docker stop kkmail-mail-core-worker")
    rm_worker_idx = next(i for i, line in enumerate(lines) if line == "docker rm -f kkmail-mail-core-worker")
    up_idx = next(i for i, line in enumerate(lines) if "compose -f docker-compose.embedded.yml up -d" in line)
    ready_idx = next(i for i, line in enumerate(lines) if line.startswith("curl ") and "/ready" in line)

    assert build_idx < stop_api_idx < rm_api_idx < up_idx < ready_idx
    assert build_idx < stop_worker_idx < rm_worker_idx < up_idx < ready_idx
    assert not any("--profile distributed down" in line for line in lines)
    assert not any("--remove-orphans" in line for line in lines)
    assert not any("kkmail-mail-core-pg" in line and ("stop" in line or "rm" in line) for line in lines)


def test_deploy_embedded_build_failure_causes_zero_downtime(tmp_path: Path):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    call_log = tmp_path / "calls.log"

    _write_executable(
        stub_bin / "docker",
        f"""
echo "docker $*" >> "{call_log}"
if [[ "$1" == "compose" ]]; then
  case " $* " in
    *" config --quiet "*) exit 0 ;;
    *" config --services "*) printf 'postgres\\napp\\n'; exit 0 ;;
    *" build app "*) exit 1 ;;
  esac
fi
exit 0
""",
    )
    _write_executable(stub_bin / "curl", "exit 0")
    _write_executable(stub_bin / "rg", 'exec grep -E "$@"')

    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        **_DUMMY_COMPOSE_ENV,
    }
    proc = subprocess.run(
        ["bash", str(DEPLOY_EMBEDDED)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    lines = call_log.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("docker stop ") for line in lines)
    assert not any(line.startswith("docker rm ") for line in lines)
    assert not any(" up " in f" {line} " for line in lines)


def test_deploy_mail_core_stops_and_removes_embedded_app_before_migrate(tmp_path: Path):
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts" / "lib").mkdir(parents=True)
    (fake_repo / "config").mkdir(parents=True)
    shutil.copy2(DEPLOY_DISTRIBUTED, fake_repo / "scripts" / "deploy_mail_core.sh")
    shutil.copy2(
        REPO_ROOT / "scripts" / "lib" / "preflight_schema_gate.sh",
        fake_repo / "scripts" / "lib" / "preflight_schema_gate.sh",
    )
    shutil.copy2(REPO_ROOT / "config" / "base_images.lock", fake_repo / "config" / "base_images.lock")
    shutil.copy2(DISTRIBUTED_COMPOSE, fake_repo / "docker-compose.mail-core.yml")

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    call_log = tmp_path / "calls.log"
    real_python = shutil.which("python3")
    assert real_python is not None

    _write_executable(
        stub_bin / "git",
        """
case "$1" in
  branch) echo "main" ;;
  status) : ;;
  fetch|merge-base) : ;;
  rev-parse) echo "deadbeef" ;;
  *) : ;;
esac
exit 0
""",
    )
    _write_executable(
        stub_bin / "docker",
        f"""
echo "docker $*" >> "{call_log}"
if [[ "$1" == "context" ]]; then
  echo "orbstack"
  exit 0
fi
if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  exit 0
fi
if [[ "$1" == "inspect" ]]; then
  if [[ "$2" == "--format" && "$3" == "{{{{.State.Running}}}}" ]]; then
    echo "true"
    exit 0
  fi
  if [[ "$2" == "kkmail-mail-core-app" ]]; then
    exit 0
  fi
  exit 1
fi
if [[ "$1" == "exec" ]]; then
  printf '<html><script src="/assets/app.js"></script></html>'
  exit 0
fi
if [[ "$1" == "compose" ]]; then
  case " $* " in
    *" config --images "*)
      printf 'kkmail-api:latest\\nkkmail-worker:latest\\nkkmail-migrate:latest\\n'
      exit 0
      ;;
  esac
fi
exit 0
""",
    )
    _write_executable(stub_bin / "curl", "exit 0")
    _write_executable(stub_bin / "rg", 'exec grep -E "$@"')
    _write_executable(
        stub_bin / "python3",
        f"""
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "mail_core" && "${{3:-}}" == "--check-migrations" ]]; then
  echo "docker-check-migrations" >> "{call_log}"
  exit 0
fi
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "mail_core.backup.export" ]]; then
  backup_dir=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--backup-dir" ]]; then
      backup_dir="$2"
      shift 2
      continue
    fi
    shift
  done
  mkdir -p "$backup_dir/package"
  printf 'sealed' > "$backup_dir/package/backup.kkbak"
  exit 0
fi
if [[ "${{1:-}}" == "-" && -z "${{2:-}}" ]]; then
  cat >/dev/null
  echo "verified app.js: 42 bytes"
  exit 0
fi
exec "{real_python}" "$@"
""",
    )

    env = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "POSTGRES_PASSWORD": "valid-pw_123",
    }
    proc = subprocess.run(
        ["bash", str(fake_repo / "scripts" / "deploy_mail_core.sh"), "--no-push"],
        cwd=str(fake_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = call_log.read_text(encoding="utf-8").splitlines()

    build_idx = next(i for i, line in enumerate(lines) if "build api worker migrate" in line)
    stop_app_idx = next(i for i, line in enumerate(lines) if line == "docker stop kkmail-mail-core-app")
    rm_app_idx = next(i for i, line in enumerate(lines) if line == "docker rm -f kkmail-mail-core-app")
    stop_api_worker_idx = next(i for i, line in enumerate(lines) if "stop api worker" in line)
    migrate_idx = next(i for i, line in enumerate(lines) if "--exit-code-from migrate migrate" in line)
    up_idx = next(i for i, line in enumerate(lines) if "up -d api worker" in line)

    assert build_idx < stop_app_idx < rm_app_idx < migrate_idx < up_idx
    assert build_idx < stop_api_worker_idx < migrate_idx < up_idx


def test_deployment_doc_forbids_distributed_embedded_override_and_documents_recovery():
    doc = DEPLOYMENT_DOC.read_text(encoding="utf-8")
    assert "MAIL_CORE_SKIP_MIGRATIONS=0 MAIL_CORE_EMBEDDED_WORKER=1" not in doc
    assert "MAIL_CORE_EMBEDDED_WORKER=1" not in doc
    assert "scripts/deploy_embedded.sh" in doc
    assert "scripts/deploy_mail_core.sh" in doc
    assert "kkmail_mail_core_pg" in doc
    assert "kkmail_mail_core_blobs" in doc
    assert "unless-stopped" in doc
    assert "unhealthy" in doc
    assert "watchdog" in doc.lower() or "看门狗" in doc
