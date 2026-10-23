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
    status=$?
    if [ "$status" -ne 0 ]; then
        echo "--- container log (exit status $status) ---" >&2
        docker logs "$name" >&2 2>&1 || true
    fi
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
logs="$(docker logs "$name" 2>&1)"
[ "$(cat "$work/health.json")" = '{"status":"ok"}' ] || { echo "unexpected /healthz body" >&2; echo "$logs" >&2; exit 1; }
# the tokenised URL a browser outside the container uses (the console may wrap the line)
token_url="$(printf '%s' "$logs" | tr -d '\n ' | grep -o 'http://localhost:8765/?token=[A-Za-z0-9_-]*' | head -n 1)"
[ -n "$token_url" ] || { echo "the announced URL is missing from the log:" >&2; echo "$logs" >&2; exit 1; }
# Host and Origin are checked against the public URL (http://localhost:8765), so say that is what
# the browser sent: without a session the server refuses, with the token it serves the dashboard.
code="$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost:8765' http://127.0.0.1:8765/)"
[ "$code" = "403" ] || { echo "expected 403 without a session, got $code" >&2; exit 1; }
curl -fsS -H 'Host: localhost:8765' "http://127.0.0.1:8765/?token=${token_url##*token=}" | grep -q "Smoke test" \
    || { echo "the dashboard did not load with the token" >&2; exit 1; }
# a request that names any other host is a DNS-rebinding attempt and is refused
[ "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: attacker.example:8765' http://127.0.0.1:8765/)" = "400" ]
# the image's own HEALTHCHECK (30 s interval after a 10 s start period) reports healthy
for _ in $(seq 1 40); do
    state="$(docker inspect --format '{{.State.Health.Status}}' "$name")"
    [ "$state" = "healthy" ] && break
    sleep 3
done
[ "$state" = "healthy" ] || { echo "the container never became healthy (last state: $state)" >&2; exit 1; }
echo "container smoke test passed"
