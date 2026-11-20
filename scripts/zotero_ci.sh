#!/usr/bin/env bash
# Start a real Zotero for tests/live/test_zotero_local.py (.github/workflows/zotero-live.yml).
#
#   scripts/zotero_ci.sh install   download the current release into $ZOTERO_HOME
#   scripts/zotero_ci.sh start     start it under Xvfb with the local API on, wait for it
#   scripts/zotero_ci.sh seed      save the test items through the connector endpoint
#
# Linux only. The local API is switched on by the preference behind Settings > Advanced >
# "Allow other applications on this computer to communicate with Zotero"
# (extensions.zotero.httpServer.localAPI.enabled; docs/zotero-real-run.md).
set -euo pipefail

ZOTERO_HOME="${ZOTERO_HOME:-$HOME/zotero-ci}"
PROFILE="$ZOTERO_HOME/profile"
DATA="$ZOTERO_HOME/data"
PORT=23119

install() {
  mkdir -p "$ZOTERO_HOME"
  curl -fsSL -o "$ZOTERO_HOME/zotero.tar" \
    "https://www.zotero.org/download/client/dl?channel=release&platform=linux-x86_64"
  tar -xf "$ZOTERO_HOME/zotero.tar" -C "$ZOTERO_HOME"
  rm "$ZOTERO_HOME/zotero.tar"
  local app
  app=$(find "$ZOTERO_HOME" -maxdepth 2 -name zotero -type f -perm -u+x | head -1)
  [ -n "$app" ] || { echo "no zotero executable in the download" >&2; exit 1; }
  ln -sf "$app" "$ZOTERO_HOME/zotero-bin"
  mkdir -p "$PROFILE" "$DATA"
  cat > "$PROFILE/user.js" <<PREFS
user_pref("extensions.zotero.httpServer.enabled", true);
user_pref("extensions.zotero.httpServer.localAPI.enabled", true);
user_pref("extensions.zotero.useDataDir", true);
user_pref("extensions.zotero.dataDir", "$DATA");
user_pref("extensions.zotero.firstRun2", false);
user_pref("extensions.zotero.firstRunGuidance", false);
user_pref("extensions.zotero.sync.autoSync", false);
user_pref("app.update.enabled", false);
user_pref("app.update.auto", false);
PREFS
  "$ZOTERO_HOME/zotero-bin" --version || true
}

start() {
  nohup xvfb-run -a "$ZOTERO_HOME/zotero-bin" -profile "$PROFILE" > "$ZOTERO_HOME/zotero.log" 2>&1 &
  for _ in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:$PORT/connector/ping" > /dev/null 2>&1; then
      curl -sS -D - -o /dev/null "http://127.0.0.1:$PORT/api/" || true
      # The first library query of a freshly started Zotero can take several seconds; make it here,
      # so the tests measure strata and not Zotero's start-up.
      curl -fsS -m 60 -o /dev/null "http://127.0.0.1:$PORT/api/users/0/items/top?limit=1" || true
      return 0
    fi
    sleep 2
  done
  echo "Zotero did not start; its log:" >&2
  cat "$ZOTERO_HOME/zotero.log" >&2 || true
  exit 1
}

seed() {
  # The item shapes are Zotero's own (translator output), which the connector saves as they are.
  curl -fsS -X POST "http://127.0.0.1:$PORT/connector/saveItems" \
    -H "Content-Type: application/json" \
    -H "X-Zotero-Connector-API-Version: 3" \
    --data @- <<'JSON'
{
  "uri": "https://example.org/strata-ci",
  "items": [
    {"itemType": "journalArticle", "id": "1",
     "title": "Spacing effects in learning: A temporal ridgeline of optimal retention",
     "creators": [{"firstName": "Nicholas J.", "lastName": "Cepeda", "creatorType": "author"},
                  {"firstName": "Edward", "lastName": "Vul", "creatorType": "author"}],
     "publicationTitle": "Psychological Science", "volume": "19", "issue": "11",
     "pages": "1095-1102", "date": "2008-11", "DOI": "10.1111/j.1467-9280.2008.02209.x"},
    {"itemType": "journalArticle", "id": "2", "title": "An item whose date is not an ISO date",
     "creators": [{"firstName": "Larry V.", "lastName": "Hedges", "creatorType": "author"}],
     "date": "11/1984"},
    {"itemType": "book", "id": "3", "title": "An item with its PMID in extra",
     "creators": [{"firstName": "Ada", "lastName": "Okonkwo", "creatorType": "author"}],
     "date": "2015", "extra": "PMID: 12345678"}
  ]
}
JSON
  # Saving is asynchronous; wait until the local API lists all three.
  for _ in $(seq 1 30); do
    total=$(curl -fsS -D - -o /dev/null "http://127.0.0.1:$PORT/api/users/0/items/top" \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="total-results"{print $2}')
    [ "${total:-0}" -ge 3 ] && { echo "seeded: $total items"; return 0; }
    sleep 1
  done
  echo "the seeded items did not appear on the local API" >&2
  exit 1
}

"$@"
