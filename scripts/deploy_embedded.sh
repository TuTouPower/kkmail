#!/usr/bin/env bash
# Deploy the single-host embedded stack (API + embedded Worker in one process).
# Mutually exclusive with deploy_mail_core.sh (distributed stack); never run
# both against the same data volume at once.
#
# Usage: scripts/deploy_embedded.sh
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

fail() {
    printf 'deploy_embedded: %s\n' "$1" >&2
    exit 1
}

for command_name in docker; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done

compose_file="docker-compose.embedded.yml"
# Secrets are never defaulted; the process refuses to start without them.
for var in POSTGRES_PASSWORD MAIL_CORE_SECRET_KEY MAIL_CORE_BLOB_KEY_V1 MAIL_CORE_BACKUP_KEY; do
    [[ -n "${!var:-}" ]] || fail "$var must be set (see docs/guides/deployment.md)"
done
[[ "${POSTGRES_PASSWORD:-}" =~ ^[A-Za-z0-9_-]+$ ]] || fail "POSTGRES_PASSWORD must match ^[A-Za-z0-9_-]+\$ (embedded unescaped in DATABASE_URL)"

# Validate the embedded manifest and prove the two modes cannot clash: this
# stack owns only 'app'+'postgres'; the distributed stack owns api/worker.
docker compose -f "$compose_file" config --quiet
docker compose -f "$compose_file" config --services | rg -q '^app$' || fail "embedded stack must define a single 'app' service"
docker compose -f "$compose_file" config --services | rg -q '^worker$' && fail "embedded stack must not define a standalone worker"

# Stop any distributed stack first so the two modes never run together.
if docker compose -f docker-compose.mail-core.yml --profile distributed ps -q 2>/dev/null | rg -q .; then
    docker compose -f docker-compose.mail-core.yml --profile distributed down --remove-orphans
fi

docker compose -f "$compose_file" build app
docker compose -f "$compose_file" up -d --remove-orphans

# Readiness gate: the single process runs migrations before serving, so /ready
# must reach ready within a bounded window.
for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:37281/ready >/dev/null 2>&1; then
        printf 'embedded stack ready\n'
        exit 0
    fi
    sleep 2
done
fail "embedded stack did not become ready; see 'docker compose -f $compose_file logs'"
