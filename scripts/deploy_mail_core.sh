#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
    printf 'deploy_mail_core: %s\n' "$1" >&2
    exit 1
}

for command_name in git docker curl python3 rg; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done

[[ "$(git branch --show-current)" == "main" ]] || fail "run from the main branch"
[[ -z "$(git status --porcelain=v1 --untracked-files=normal)" ]] || fail "worktree must be clean"
[[ "$(docker context show)" == "orbstack" ]] || fail "expected the OrbStack Docker context"

git fetch origin main
git merge-base --is-ancestor origin/main main || fail "main diverges from origin/main; reconcile branches before deployment"
docker compose version >/dev/null
docker compose -f docker-compose.mail-core.yml --profile distributed config --quiet
git push origin main

stamp="$(date +%Y%m%d_%H%M%S)"
commit="$(git rev-parse --short=8 HEAD)"
backup_dir="$repo_root/.scratch/deploy_backup_$stamp"
mkdir -p "$repo_root/.scratch"
mkdir "$backup_dir"
chmod 0777 "$backup_dir"
restore_backup_dir() {
    chmod 0700 "$backup_dir" 2>/dev/null || true
}
trap restore_backup_dir EXIT
export MAIL_CORE_DEPLOY_BACKUP_DIR="$backup_dir"

docker compose -f docker-compose.mail-core.yml --profile maintenance run --build --rm backup
[[ -s "$backup_dir/package/backup.kkbak" ]] || fail "sealed backup package is missing"
chmod 0700 "$backup_dir"

if docker inspect kkmail-mail-core-api >/dev/null 2>&1; then
    api_image="$(docker inspect --format '{{.Image}}' kkmail-mail-core-api)"
    docker image tag "$api_image" "kkmail-api:rollback-$stamp"
fi
if docker inspect kkmail-mail-core-worker >/dev/null 2>&1; then
    worker_image="$(docker inspect --format '{{.Image}}' kkmail-mail-core-worker)"
    docker image tag "$worker_image" "kkmail-worker:rollback-$stamp"
fi
if docker image inspect kkmail-migrate:latest >/dev/null 2>&1; then
    docker image tag kkmail-migrate:latest "kkmail-migrate:rollback-$stamp"
fi

docker compose -f docker-compose.mail-core.yml --profile distributed build api worker migrate
for service in api worker migrate; do
    docker image tag "kkmail-$service:latest" "kkmail-$service:$commit"
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

python3 - <<'PY'
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
