#!/usr/bin/env bash
# Seed the local Docker daemon with the pinned base images declared in
# config/base_images.lock.
#
# The bootstrap must obey the same invariant as the build: the daemon never
# reaches a registry. A checksum-pinned host-side skopeo copies each image by
# immutable digest straight into docker-daemon. No bootstrap container, no
# unpinned `alpine:latest`, no pre-existing image required.
#
# Host registry/proxy access is the only network hop. Set KKMAIL_PIN_PROXY to
# override the default host proxy (http://127.0.0.1:7890), or to an empty
# value when the host has direct registry access.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock="$repo_root/config/base_images.lock"
policy="$repo_root/config/containers/skopeo-policy.json"
python_bin="$repo_root/.venv/bin/python"
[[ -x "$python_bin" ]] || python_bin=python3

fail() { printf 'pin_base_images: %s\n' "$1" >&2; exit 1; }

for command_name in docker curl python3; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done
[[ -S /var/run/docker.sock ]] || fail "docker daemon socket not found at /var/run/docker.sock"
[[ -f "$lock" ]] || fail "missing $lock"
[[ -f "$policy" ]] || fail "missing $policy"

if command -v shasum >/dev/null 2>&1; then
    checksum() { shasum -a 256 "$1" | cut -d' ' -f1; }
elif command -v sha256sum >/dev/null 2>&1; then
    checksum() { sha256sum "$1" | cut -d' ' -f1; }
else
    fail "need shasum or sha256sum to verify the pinned tool"
fi

host_os="$(uname -s | tr '[:upper:]' '[:lower:]')"
host_arch="$(uname -m)"
case "$host_arch" in
    arm64|aarch64) host_arch=arm64 ;;
    x86_64) host_arch=amd64 ;;
esac
host_key="${host_os}_${host_arch}"

tool_info="$("$python_bin" - "$lock" "$host_key" <<'PY'
import json, sys
tools = json.load(open(sys.argv[1]))["_tools"]["skopeo"]
key = sys.argv[2]
if key not in tools["sha256"]:
    raise SystemExit(f"no pinned skopeo checksum for host {key}")
print(tools["version"])
print(tools["base_url"].format(os=key.split("_")[0], arch=key.split("_")[1]))
print(tools["sha256"][key])
PY
)" || fail "cannot read pinned skopeo metadata from $lock"
{ read -r version; read -r url; read -r expected_sha; } <<<"$tool_info"
[[ -n "$version" && -n "$url" && -n "$expected_sha" ]] || fail "incomplete pinned skopeo metadata in $lock"

mkdir -p "$repo_root/.scratch/tools"
skopeo="$repo_root/.scratch/tools/skopeo-v${version}-${host_key}"

if [[ -n "${KKMAIL_PIN_PROXY+x}" ]]; then
    proxy="$KKMAIL_PIN_PROXY"
else
    proxy="http://127.0.0.1:7890"
fi

download_skopeo() {
    local tmp="$skopeo.tmp.$$"
    local curl_args=(-fsSL --retry 3 --max-time 300 -o "$tmp")
    [[ -z "$proxy" ]] || curl_args+=(--proxy "$proxy")
    curl "${curl_args[@]}" "$url" || { rm -f "$tmp"; fail "failed to download pinned skopeo from $url"; }
    [[ "$(checksum "$tmp")" == "$expected_sha" ]] || { rm -f "$tmp"; fail "pinned skopeo checksum mismatch"; }
    chmod +x "$tmp"
    mv "$tmp" "$skopeo"
}

run_skopeo() {
    if [[ -n "$proxy" ]]; then
        HTTPS_PROXY="$proxy" HTTP_PROXY="$proxy" "$skopeo" "$@"
    else
        "$skopeo" "$@"
    fi
}

if [[ ! -x "$skopeo" ]] || [[ "$(checksum "$skopeo")" != "$expected_sha" ]]; then
    printf 'pin_base_images: fetching pinned skopeo %s (%s)\n' "$version" "$host_key"
    download_skopeo
fi

read -r target_os target_arch <<<"$(docker info --format '{{.OSType}} {{.Architecture}}')"
[[ "$target_arch" != "aarch64" ]] || target_arch=arm64

count=0
while read -r tag digest; do
    [[ -n "$tag" ]] || continue
    repo="${tag%%:*}"
    printf 'pin_base_images: importing %s @ %s\n' "$tag" "$digest"
    run_skopeo copy \
        --policy "$policy" \
        --override-os "$target_os" --override-arch "$target_arch" \
        --retry-times 3 \
        "docker://${repo}@${digest}" "docker-daemon:${tag}" \
        || fail "failed to import ${tag} from ${repo}@${digest}"
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
