#!/usr/bin/env bash
# Smoke test of the container image (openspec:container-image#image-ci):
# --version, git, init, verify and status against a mounted repository (file ownership, a different
# owner), then `serve` with its token, public URL and /healthz.
#
# usage: scripts/container_smoke.sh IMAGE
set -euo pipefail

image="${1:?usage: container_smoke.sh IMAGE}"
work="$(mktemp -d)"
name="strata-smoke-$$"
cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

review="$work/review"
mkdir "$review"
as_me=(--user "$(id -u):$(id -g)" -v "$review":/review
    -e GIT_AUTHOR_NAME=Smoke -e GIT_AUTHOR_EMAIL=smoke@example.invalid
    -e GIT_COMMITTER_NAME=Smoke -e GIT_COMMITTER_EMAIL=smoke@example.invalid)

expected="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)"
[ "$(docker run --rm "$image" --version)" = "strata $expected" ]
docker run --rm --entrypoint git "$image" --version

docker run --rm "${as_me[@]}" "$image" init . --title "Smoke test" --actor ci --actor-name CI
[ "$(stat -c %u "$review/strata.toml")" = "$(id -u)" ] || { echo "files are not owned by the host user" >&2; exit 1; }
docker run --rm "${as_me[@]}" "$image" verify
docker run --rm "${as_me[@]}" "$image" status
# a repository owned by someone else: git must not refuse it for dubious ownership
docker run --rm --user 12345:12345 -v "$review":/review "$image" status

docker run -d --name "$name" "${as_me[@]}" -p 127.0.0.1:8765:8765 "$image" serve --actor ci >/dev/null
for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8765/healthz >"$work/health.json" 2>/dev/null; then break; fi
    sleep 0.5
done
[ "$(cat "$work/health.json")" = '{"status":"ok"}' ]
docker logs "$name" 2>&1 | grep -q 'http://localhost:8765/?token='
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/)" = "403" ]  # no session
echo "container smoke test passed"
