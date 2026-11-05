"""R4 adoption P51 (deploy script + compose): A266/A13/A161/A72/A98/A154.

Each test targets one adoption item in
``docs/reviews/review_20261027_021416/adoption_decision.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts" / "deploy_mail_core.sh"
COMPOSE = ROOT / "docker-compose.mail-core.yml"


def _deploy_text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


# --- A266: OrbStack context must be env-overridable; push must be explicit ---


def test_a266_context_is_env_overridable_with_documented_default():
    text = _deploy_text()
    assert "EXPECTED_DOCKER_CONTEXT" in text
    assert "orbstack" in text
    # The expected context must come from the environment, not a bare literal
    # comparison against a hard-coded string.
    assert re.search(
        r'\$\{EXPECTED_DOCKER_CONTEXT:-orbstack\}', text
    ), "context expectation must default via EXPECTED_DOCKER_CONTEXT env var"
    assert '[[ "$(docker context show)" == "orbstack" ]]' not in text


def test_a266_push_is_opt_out_and_announced():
    text = _deploy_text()
    assert "--no-push" in text, "deploy must support an explicit --no-push switch"
    # Push must be guarded by the switch and announced before it runs.
    assert re.search(r"no_push|NO_PUSH", text)
    push_idx = text.index("git push origin main")
    announce_idx = text.rindex("printf", 0, push_idx)
    announce_chunk = text[announce_idx:push_idx]
    assert "push" in announce_chunk.lower(), (
        "the git push step must print what it is about to do before running"
    )


# --- A13: backup dir stays 0700; package is verified, not just present ---


def test_a13_backup_dir_and_staging_are_never_world_accessible():
    text = _deploy_text()
    assert "0777" not in text, "backup dir must never be chmod 0777"
    assert 'chmod 0700 "$backup_dir" "$staging_dir"' in text


def test_a13_backup_runs_as_application_identity_without_host_user_override():
    text = _deploy_text()
    backup_run = re.search(r"docker compose[^\n]*--profile maintenance run[^\n]*backup", text)
    assert backup_run, "deploy must run the backup service"
    run_line = backup_run.group(0)
    assert "--user" not in run_line, (
        "the backup process must keep the image application uid so it can read "
        "private 0600 blobs; forcing the host uid recreates the cross-owner bug"
    )
    assert "--name" in run_line, "the stopped container must remain for host export"
    assert "--rm" not in run_line, "removing the container before export loses the package"


def test_a13_deploy_uses_host_side_backup_export_module():
    text = _deploy_text()
    assert "mail_core.backup.export" in text, (
        "deploy must call the tested host-side export module, not inline "
        "docker cp/verification logic that no behavioral test can execute"
    )
    assert "--container \"$backup_container\"" in text
    assert "--staging-dir \"$staging_dir\"" in text
    assert "--backup-dir \"$backup_dir\"" in text


def test_a13_compose_backup_has_no_host_bind_and_blob_is_read_only():
    import yaml

    services = yaml.safe_load(_compose_text())["services"]
    volumes = services["backup"].get("volumes") or []
    assert volumes == ["kkmail_mail_core_blobs:/var/lib/kkmail/blobs:ro"], (
        "the backup container must read blobs read-only and keep its package "
        "in a container-private directory, not a host bind mount"
    )
    assert "MAIL_CORE_DEPLOY_BACKUP_DIR" not in _compose_text()


def test_a13_backup_image_owns_private_workdir():
    dockerfile = (ROOT / "Dockerfile.mail-core-backup").read_text(encoding="utf-8")
    assert "mkdir -p /backup" in dockerfile
    assert "chown 10001:999 /backup" in dockerfile
    assert "chmod 0700 /backup" in dockerfile
    assert "USER 10001:999" in dockerfile


# --- A161: image names must be discovered, not assumed from a prefix ---


def test_a161_image_names_come_from_compose_config():
    text = _deploy_text()
    assert "config --images" in text, (
        "deploy must discover built image names via `docker compose config "
        "--images` instead of assuming a <project>-<service> prefix"
    )
    assert "resolve_compose_image" in text


def test_a161_no_hardcoded_kkmail_image_prefix():
    text = _deploy_text()
    assert "kkmail-$service" not in text
    assert "kkmail-migrate:latest" not in text
    assert '"kkmail-api:' not in text
    assert '"kkmail-worker:' not in text


# --- A72: POSTGRES_PASSWORD is embedded unescaped in DATABASE_URL (x4) ---


def test_a72_deploy_validates_postgres_password_charset():
    text = _deploy_text()
    assert "POSTGRES_PASSWORD" in text
    assert "^[A-Za-z0-9_-]+$" in text, (
        "deploy must reject POSTGRES_PASSWORD values outside the URL-safe "
        "charset before they are interpolated into DATABASE_URL"
    )


def test_a72_compose_sites_state_the_charset_restriction():
    text = _compose_text()
    assert text.count("postgresql+psycopg://kkmail:${POSTGRES_PASSWORD}@") == 4
    # Every interpolation site must carry the restriction, not a vague hint.
    assert text.count("[A-Za-z0-9_-]") >= 4
    assert "use URL-safe hex/base64url characters" not in text


# --- A98: session cookie Secure must default on ---


def test_a98_cookie_secure_defaults_to_on():
    text = _compose_text()
    assert 'MAIL_CORE_COOKIE_SECURE: "${MAIL_CORE_COOKIE_SECURE:-1}"' in text
    assert 'MAIL_CORE_COOKIE_SECURE:-0' not in text


def test_a98_compose_comment_explains_local_http_opt_out():
    text = _compose_text()
    idx = text.index('MAIL_CORE_COOKIE_SECURE: "${MAIL_CORE_COOKIE_SECURE:-1}"')
    context = text[max(0, idx - 600):idx + 200]
    assert "MAIL_CORE_COOKIE_SECURE=0" in context and "HTTP" in context, (
        "the Secure default must be documented with the explicit local "
        "HTTP debugging opt-out (set MAIL_CORE_COOKIE_SECURE=0)"
    )


# --- A154: bare `up` must not start an api that never runs migrations ---


def test_a154_api_is_gated_behind_distributed_profile():
    import yaml

    doc = yaml.safe_load(_compose_text())
    services = doc["services"]
    assert services["api"].get("profiles") == ["distributed"], (
        "api has no profile while migrate/worker sit behind `distributed` "
        "and api defaults SKIP_MIGRATIONS=1 with a required:false migrate "
        "dependency: a bare `up` starts an api against an unmigrated DB"
    )
    assert services["migrate"].get("profiles") == ["distributed"]
    assert services["worker"].get("profiles") == ["distributed"]


def test_a154_header_warns_bare_up_is_unsupported():
    text = _compose_text()
    header = text.split("services:")[0]
    assert "distributed" in header
    assert "up -d" in header or "bare" in header.lower()
    assert "migrat" in header.lower(), (
        "file header must warn that a bare up is not the supported path "
        "and state what happens to migrations"
    )
