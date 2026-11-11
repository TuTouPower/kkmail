#!/usr/bin/env bash
# Seed the local Docker daemon with the pinned base images declared in
# config/base_images.lock.
#
# This is the ONLY step in the build/deploy pipeline that reaches Docker Hub,
# and it deliberately runs from inside a throwaway container: the container
# gets HTTP(S)_PROXY injected by ~/.docker/config.json (proxies.default ->
# host.docker.internal:7890), so skopeo can resolve the registry through the
# host proxy. The Docker daemon itself never needs registry access -- that is
# essential under the reverse-isolation setup (orb network_proxy none), where
# daemon-side pulls have no proxy path.
#
# The image is copied by immutable index digest, then tagged with the platform
# neutral name the Dockerfile consumes. BuildKit resolves a locally present
# tag without any network request, so deployments become fully offline-capable
# and reproducible regardless of the host's gateway/agent configuration.
set -Eeuo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock="$repo_root/config/base_images.lock"
python_bin="$repo_root/.venv/bin/python"
[[ -x "$python_bin" ]] || python_bin=python3

fail() { printf 'pin_base_images: %s\n' "$1" >&2; exit 1; }

[[ -S /var/run/docker.sock ]] || fail "docker daemon socket not found at /var/run/docker.sock"
[[ -f "$lock" ]] || fail "missing $lock"
command -v docker >/dev/null 2>&1 || fail "docker not found"

count=0
while read -r tag digest; do
    [[ -n "$tag" ]] || continue
    repo="${tag%%:*}"
    printf 'pin_base_images: importing %s @ %s\n' "$tag" "$digest"
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine:latest sh -c \
        "apk add --no-cache skopeo >/dev/null 2>&1 \
         && skopeo copy --retry-times 3 'docker://${repo}@${digest}' 'docker-daemon:${tag}'" \
        || fail "failed to import ${tag}; is the container proxy reachable at host.docker.internal:7890?"
    docker image inspect "$tag" >/dev/null 2>&1 \
        || fail "imported image ${tag} is not visible to the daemon"
    count=$((count + 1))
done < <("$python_bin" - "$lock" <<'PY'
import json, sys
for tag, digest in json.load(open(sys.argv[1])).items():
    if not tag.startswith("_"):
        print(tag, digest)
PY
)

[[ "$count" -gt 0 ]] || fail "no base images declared in $lock"
printf 'pin_base_images: pinned %d base image(s), all resolvable locally:\n' "$count"
while read -r tag _digest; do
    [[ -n "$tag" ]] || continue
    printf '  %s -> %s\n' "$tag" "$(docker image inspect --format '{{index .RepoDigests 0}}' "$tag")"
done < <("$python_bin" - "$lock" <<'PY'
import json, sys
for tag, digest in json.load(open(sys.argv[1])).items():
    if not tag.startswith("_"):
        print(tag, digest)
PY
)
