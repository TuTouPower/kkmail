#!/usr/bin/env bash
# Deploy the mail-core distributed stack from this checkout.
#
# Prerequisites (single-operator machine):
#   - Run from a clean `main` worktree.
#   - Docker context: this script was written for OrbStack and expects the
#     `orbstack` context by default. On a plain Docker / Docker Desktop
#     machine set EXPECTED_DOCKER_CONTEXT to the context `docker context
#     show` prints there (for example `desktop-linux` or `default`).
#   - Unless --no-push is given, deploying first pushes `main` to
#     `origin/main` (an explicit, announced step below, not a side effect).
#
# Usage: scripts/deploy_mail_core.sh [--no-push]
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="$repo_root/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
    python_bin="python3"
fi

fail() {
    printf 'deploy_mail_core: %s\n' "$1" >&2
    exit 1
}

no_push=0
for arg in "$@"; do
    case "$arg" in
        --no-push) no_push=1 ;;
        *) fail "unknown argument: $arg (usage: deploy_mail_core.sh [--no-push])" ;;
    esac
done

for command_name in git docker curl python3 rg; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done

# POSTGRES_PASSWORD is interpolated unescaped into DATABASE_URL in
# docker-compose.mail-core.yml (four services). Characters such as
# @ : / # % would corrupt the URL (wrong host/db or a truncated password),
# so reject anything outside the URL-safe charset before doing any work.
[[ "${POSTGRES_PASSWORD:-}" =~ ^[A-Za-z0-9_-]+$ ]] || fail "POSTGRES_PASSWORD must be set and match ^[A-Za-z0-9_-]+\$ (it is embedded unescaped in DATABASE_URL; regenerate it URL-safe, e.g. openssl rand -hex 24)"

[[ "$(git branch --show-current)" == "main" ]] || fail "run from the main branch"
[[ -z "$(git status --porcelain=v1 --untracked-files=normal)" ]] || fail "worktree must be clean"
expected_context="${EXPECTED_DOCKER_CONTEXT:-orbstack}"
[[ "$(docker context show)" == "$expected_context" ]] || fail "expected Docker context '$expected_context' (set EXPECTED_DOCKER_CONTEXT to override; see script header)"

git fetch origin main
git merge-base --is-ancestor origin/main main || fail "main diverges from origin/main; reconcile branches before deployment"
docker compose version >/dev/null
docker compose -f docker-compose.mail-core.yml --profile distributed config --quiet
if [[ "$no_push" == "1" ]]; then
    printf 'deploy_mail_core: --no-push given; skipping git push of main to origin/main\n'
else
    printf 'deploy_mail_core: pushing main to origin/main (pass --no-push to skip this step)\n'
    git push origin main
fi

stamp="$(date +%Y%m%d_%H%M%S)"
commit="$(git rev-parse --short=8 HEAD)"
backup_dir="$repo_root/.scratch/deploy_backup_$stamp"
mkdir -p "$repo_root/.scratch"
mkdir "$backup_dir"
# Keep the backup dir private (0700) for its whole lifetime: the backup
# container below runs as the host user (--user), so it can write into a
# 0700 directory owned by that user. Never widen this to world-writable —
# during that window any local user could replace the sealed package
# that a later rollback would trust.
chmod 0700 "$backup_dir"
export MAIL_CORE_DEPLOY_BACKUP_DIR="$backup_dir"

docker compose -f docker-compose.mail-core.yml --profile maintenance run --user "$(id -u):$(id -g)" --build --rm backup
[[ -s "$backup_dir/package/backup.kkbak" ]] || fail "sealed backup package is missing"
# Existence is not integrity: verify the sealed package (MANIFEST.json /
# MANIFEST.sha256 and every member checksum, incl. backup.kkbak) with the
# same verifier restores use before treating it as a rollback source.
MAIL_CORE_DEPLOY_BACKUP_DIR="$backup_dir" "$python_bin" - <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))
from mail_core.backup import verify_backup_package

package_dir = Path(os.environ["MAIL_CORE_DEPLOY_BACKUP_DIR"]) / "package"
result = verify_backup_package(package_dir)
if not result.ok:
    raise SystemExit(
        "sealed backup package failed verification: " + "; ".join(result.errors)
    )
print(
    f"verified sealed backup package: {result.members_checked} members checked"
)
PY

# Image names are NOT "<clone-dir>-<service>": Compose derives the project
# name from the checkout directory, so a renamed clone would break every
# hard-coded image-prefix tag below mid-deploy (after push + backup).
# Always resolve the actual image for a service from the Compose model,
# and derive rollback/commit tags from that resolved repository name.
resolve_compose_image() {
    local service="$1"
    docker compose -f docker-compose.mail-core.yml --profile distributed config --images \
        | grep -E -- "-${service}(:|$)" | head -n 1
}

image_repo() {
    local image="$1"
    if [[ "$image" == *"@"* ]]; then
        printf '%s' "${image%%@*}"
    elif [[ "$image" == *:* && "${image##*/}" == *:* ]]; then
        printf '%s' "${image%:*}"
    else
        printf '%s' "$image"
    fi
}

if docker inspect kkmail-mail-core-api >/dev/null 2>&1; then
    api_image="$(docker inspect --format '{{.Image}}' kkmail-mail-core-api)"
    api_image_name="$(docker inspect --format '{{.Config.Image}}' kkmail-mail-core-api)"
    docker image tag "$api_image" "$(image_repo "$api_image_name"):rollback-$stamp"
fi
if docker inspect kkmail-mail-core-worker >/dev/null 2>&1; then
    worker_image="$(docker inspect --format '{{.Image}}' kkmail-mail-core-worker)"
    worker_image_name="$(docker inspect --format '{{.Config.Image}}' kkmail-mail-core-worker)"
    docker image tag "$worker_image" "$(image_repo "$worker_image_name"):rollback-$stamp"
fi

migrate_image="$(resolve_compose_image migrate)"
if [[ -n "$migrate_image" ]] && docker image inspect "$migrate_image" >/dev/null 2>&1; then
    docker image tag "$migrate_image" "$(image_repo "$migrate_image"):rollback-$stamp"
fi

docker compose -f docker-compose.mail-core.yml --profile distributed build api worker migrate
for service in api worker migrate; do
    service_image="$(resolve_compose_image "$service")"
    [[ -n "$service_image" ]] || fail "could not resolve built image for service: $service"
    docker image tag "$service_image" "$(image_repo "$service_image"):$commit"
done
docker compose -f docker-compose.mail-core.yml --profile distributed up -d api worker

ready=0
for _ in {1..60}; do
    if curl --fail --silent http://127.0.0.1:37281/ready >/dev/null; then
        ready=1
        break
    fi
    sleep 2
done
[[ "$ready" == "1" ]] || fail "API did not become ready; keep backup and rollback images"
curl --fail --silent http://127.0.0.1:37281/health >/dev/null || fail "API health check failed"
docker inspect --format '{{.State.Running}}' kkmail-mail-core-worker | rg -q '^true$' || fail "worker is not running"

"$python_bin" - <<'PY'
from pathlib import PurePosixPath
from subprocess import check_output
from urllib.request import urlopen
import re

container = "kkmail-mail-core-api"
base_url = "http://127.0.0.1:37281"
container_index = check_output(
    ["docker", "exec", container, "cat", "/app/frontend/dist/index.html"]
)
served_index = urlopen(base_url + "/", timeout=10).read()
if container_index != served_index:
    raise SystemExit("served index does not match the deployed image")

assets = re.findall(rb'(?:src|href)="(/assets/[^\"]+)"', served_index)
if not assets:
    raise SystemExit("served index has no static asset references")
for raw_path in assets:
    asset_path = raw_path.decode("utf-8")
    relative = PurePosixPath(asset_path.lstrip("/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("unsafe asset path in served index")
    image_asset = check_output(
        ["docker", "exec", container, "cat", f"/app/frontend/dist/{relative.as_posix()}"]
    )
    served_asset = urlopen(base_url + asset_path, timeout=10).read()
    if image_asset != served_asset:
        raise SystemExit(f"served asset differs from image: {relative.name}")
    print(f"verified {relative.name}: {len(served_asset)} bytes")
PY

docker compose -f docker-compose.mail-core.yml --profile distributed ps
printf 'deployed_commit=%s\nbackup=%s/package\nrollback_tag=rollback-%s\n' \
    "$commit" "$backup_dir" "$stamp"
