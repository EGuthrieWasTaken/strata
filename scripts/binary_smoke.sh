#!/usr/bin/env bash
# Smoke-test a standalone `strata` binary (packaging/pyinstaller/strata.spec): the five-minute
# first run, in an empty directory with nothing from the source tree on the path.
#
#   scripts/binary_smoke.sh path/to/strata
#
# Used by release.yml on every platform it builds a binary for.
set -euo pipefail

binary="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
fixture="$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures/migration/rayyan-articles.csv"
work="$(mktemp -d)"
cd "$work"

"$binary" --version
"$binary" init review --title "Binary smoke test" --actor ethan --actor-name Ethan
cd review
"$binary" --why "the release smoke test" import "$fixture" --format rayyan --via website --by ethan
"$binary" verify
"$binary" report methods --out methods.md
head -n 3 methods.md

"$binary" serve --actor ethan --port 8799 --token smoke > ../serve.log 2>&1 &
server=$!
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8799/healthz > /dev/null 2>&1; then
    kill "$server" 2> /dev/null || true
    echo "binary smoke test passed"
    exit 0
  fi
  sleep 1
done
kill "$server" 2> /dev/null || true
cat ../serve.log >&2
echo "the web UI did not answer /healthz" >&2
exit 1
