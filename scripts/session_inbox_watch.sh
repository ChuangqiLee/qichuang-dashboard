#!/bin/bash
# Session inbox watcher (orchestrator-only). Blocks until state/session_inbox.jsonl contains a message whose id is
# greater than $1 (the last acknowledged id), prints the new lines as JSON and exits 0; exits 3 after the cap (hours, $2,
# default 8). Writes a heartbeat to state/session_watch.json every loop so the dashboard can show whether the
# orchestrator is listening. Started by the orchestrator with the Bash tool in the background; its exit wakes the
# orchestrator, which reads the message(s), acts, acknowledges them in state/session_inbox_ack.json and re-arms.
#
#   AN_ROOT=/path/to/project bash scripts/session_inbox_watch.sh <last id> [cap hours]
#
# Project root: $AN_ROOT, else the parent of the scripts/ directory that holds this file (copy it to
# <project>/scripts/). It exits 2 at once when <root>/state does not exist (wrong or unset root).
set -u
ROOT=${AN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
[ -d "$ROOT/state" ] || { echo "session_inbox_watch: no $ROOT/state directory; set AN_ROOT to the project root" >&2; exit 2; }
SINCE=${1:-0}
CAP_H=${2:-8}
INBOX=$ROOT/state/session_inbox.jsonl
HB=$ROOT/state/session_watch.json
start=$(date +%s)
while true; do
  now=$(date +%s)
  printf '{"pid": %d, "ts": "%s", "since_id": %s, "started": %d}\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SINCE" "$start" > "$HB.tmp" && mv -f "$HB.tmp" "$HB"
  if [ -s "$INBOX" ]; then
    new=$(python3 -c "
import sys, json
since = int(sys.argv[1]); out = []
for l in open(sys.argv[2], encoding='utf-8'):
    l = l.strip()
    if not l: continue
    try: m = json.loads(l)
    except Exception: continue
    if int(m.get('id', 0)) > since: out.append(json.dumps(m, ensure_ascii=False))
print('\n'.join(out))" "$SINCE" "$INBOX")
    if [ -n "$new" ]; then echo "SESSION_INBOX_NEW"; echo "$new"; exit 0; fi
  fi
  if [ $((now - start)) -ge $((CAP_H * 3600)) ]; then echo "SESSION_INBOX_WATCH_CAP"; exit 3; fi
  sleep 3
done
