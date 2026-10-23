#!/bin/sh
# The container's entrypoint (openspec:container-image). Every command is passed straight to
# `strata`; only `serve` is adjusted, because a server inside a container is reached through a
# published port:
#
#   * it listens on all interfaces (a published port never reaches the container's loopback);
#   * it always has a session token: STRATA_TOKEN or --token if given, otherwise a new one, so
#     the URL it prints is the only way in (the native CLI still refuses a non-loopback bind
#     without --token);
#   * it validates Host and Origin against the URL a browser uses: STRATA_PUBLIC_URL or
#     --public-url if given, otherwise http://localhost:<port>, which is where the documented
#     `-p 127.0.0.1:<port>:<port>` publishes it;
#   * it never tries to open a browser.
set -eu

if [ "${1:-}" != "serve" ]; then
    exec strata "$@"
fi
shift

has_host=0
has_port=0
has_token=0
has_public_url=0
port="${STRATA_PORT:-8765}"
previous=""
for arg in "$@"; do
    case "$arg" in
        --host|--host=*) has_host=1 ;;
        --port=*) has_port=1; port="${arg#--port=}" ;;
        --token|--token=*) has_token=1 ;;
        --public-url|--public-url=*) has_public_url=1 ;;
    esac
    if [ "$previous" = "--port" ]; then
        has_port=1
        port="$arg"
    fi
    previous="$arg"
done

if [ "$has_host" -eq 0 ]; then
    set -- --host 0.0.0.0 "$@"
fi
if [ "$has_port" -eq 0 ]; then
    set -- --port "$port" "$@"
fi
if [ "$has_token" -eq 0 ] && [ -z "${STRATA_TOKEN:-}" ]; then
    STRATA_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
    export STRATA_TOKEN
fi
if [ "$has_public_url" -eq 0 ] && [ -z "${STRATA_PUBLIC_URL:-}" ]; then
    STRATA_PUBLIC_URL="http://localhost:${port}"
    export STRATA_PUBLIC_URL
fi
exec strata serve --no-browser "$@"
