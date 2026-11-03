#!/usr/bin/env bash
# Qichuang dashboard demo: builds SYNTHETIC data with the kit's fixture generators, then serves the dashboard.
#
#   bash demo/run_demo.sh                  build data in ${TMPDIR:-/tmp}/qichuang-dashboard-demo, serve http://127.0.0.1:17199/
#   bash demo/run_demo.sh --port 17200     use another port
#   bash demo/run_demo.sh --root DIR       use another data dir (must be new, empty, or an earlier demo dir: it is wiped)
#   bash demo/run_demo.sh --freshness      the freshness edge-case tree instead (stale / missing / half-written files)
#   bash demo/run_demo.sh --build-only     only build the data and print the start command
#
# Python >= 3.12: $PYTHON, else <kit>/.venv/bin/python, else python3; it needs requirements.txt + requirements-dev.txt.
# The server binds 127.0.0.1 only and never reads a real project or real transcripts (AN_DEMO=1 also hides this
# machine's processes and supervisor programs on the System tab). Stop it with Ctrl+C.
# All numbers are random or hand-designed test data, not research results.
set -euo pipefail

KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASH="$KIT/dashboard"
TESTS="$DASH/tests"
PORT=17199
ROOT="${TMPDIR:-/tmp}/qichuang-dashboard-demo"
MODE=full
BUILD_ONLY=0
MARK=".qichuang-demo-root"   # written by the fixture generators after a build: only marked directories may be wiped

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:-}"; shift 2 || { usage >&2; exit 2; } ;;
    --root) ROOT="${2:-}"; shift 2 || { usage >&2; exit 2; } ;;
    --freshness) MODE=freshness; shift ;;
    --build-only) BUILD_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
case "$PORT" in ''|*[!0-9]*) echo "--port needs a number" >&2; exit 2 ;; esac
[ -n "$ROOT" ] || { echo "--root needs a directory" >&2; exit 2; }

if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif [ -x "$KIT/.venv/bin/python" ]; then PY="$KIT/.venv/bin/python"
else PY="$(command -v python3 || true)"; fi
[ -n "$PY" ] || { echo "python3 not found; set PYTHON=/path/to/python" >&2; exit 1; }

# keep thread pools small (some containers have a tight pids limit) and draw PNGs without a display
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg

if ! "$PY" -I - <<'PYCHECK'
import sys
if sys.version_info < (3, 12):
    sys.exit(f"Python >= 3.12 is needed (pinned numpy 2.5.4 / starlette 1.10.0), found {sys.version.split()[0]}")
missing = []
for mod in ("fastapi", "uvicorn", "starlette", "anyio", "psutil", "yaml", "matplotlib", "numpy"):
    try:
        __import__(mod)
    except Exception:
        missing.append(mod)
if missing:
    sys.exit("missing Python packages: " + ", ".join(missing))
PYCHECK
then
  echo "-> install them with:" >&2
  echo "   $PY -m pip install -r $KIT/requirements.txt -r $KIT/requirements-dev.txt" >&2
  exit 1
fi

# --- the data dir: absolute, never a real project, never the kit itself, only wiped when the generators built it
# (the generators repeat these checks in dashboard/tests/_fixture_guard.py, plus "never a directory containing one")
absp() { "$PY" -I -c 'import os, sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$1"; }
ROOT="$(absp "$ROOT")"
case "$ROOT" in
  /|/root|/home|/tmp|/workspace|"${HOME:-/root}"|"$KIT"|"$KIT"/*)
    echo "refusing to use $ROOT as demo root (pick a new directory, e.g. /tmp/my-dashboard-demo)" >&2; exit 1 ;;
esac
for v in AN_ROOT AN_REAL_ROOT; do   # a real project named in the environment
  [ -n "${!v:-}" ] || continue
  P="$(absp "${!v}")"
  case "$ROOT" in "$P"|"$P"/*) echo "refusing to use $ROOT as demo root: it is (inside) \$$v=$P" >&2; exit 1 ;; esac
done
if [ -e "$ROOT" ] && [ ! -d "$ROOT" ]; then echo "$ROOT exists and is not a directory" >&2; exit 1; fi
if [ -d "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ] && [ ! -f "$ROOT/$MARK" ]; then
  echo "refusing to wipe $ROOT: it is not empty and was not built by this kit (no $MARK file);" >&2
  echo "pick a new directory with --root (or delete it yourself if it is a half-built demo)" >&2; exit 1
fi

if [ "$BUILD_ONLY" = 0 ] && "$PY" -I -c '
import socket, sys
s = socket.socket(); s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$PORT"; then
  echo "port $PORT on 127.0.0.1 is already in use; pick another one with --port" >&2; exit 1
fi

echo "building synthetic demo data ($MODE) in $ROOT ..."
if [ "$MODE" = full ]; then
  "$PY" -I "$TESTS/make_fixture.py" "$ROOT"                       # every view (wipes ROOT first, writes $MARK)
  "$PY" -I "$TESTS/make_leaderboard_fixture.py" "$ROOT" --merge   # baselines vs our runs, ablation, final scope
  "$PY" -I "$TESTS/make_session_fixture.py" "$ROOT" --no-base     # transcripts + Session state files
  "$PY" -I "$KIT/demo/demo_extras.py" "$ROOT"                     # briefing; leaderboard runs moved to "now"
else
  "$PY" -I "$TESTS/make_freshness_fixture.py" "$ROOT" >/dev/null  # stale / missing / half-written sources (wipes ROOT)
  export AN_LEADERBOARD_READONLY=1                                # keep the tree exactly as built
fi

export AN_ROOT="$ROOT" AN_TRANSCRIPTS="$ROOT/transcripts" AN_DEMO=1 AN_DASH_HOST=127.0.0.1 AN_DASH_PORT="$PORT"
unset AN_SESSION_FILE AN_RAW AN_RAW_TOTAL AN_DISK_PATH AN_ALERT_SERVICES   # real-machine settings stay out of the demo

if [ "$BUILD_ONLY" = 1 ]; then
  echo "demo data ready in $ROOT; start the server with:"
  echo "  cd $DASH && AN_ROOT=$ROOT AN_TRANSCRIPTS=$ROOT/transcripts AN_DEMO=1 \\"
  echo "    AN_DASH_HOST=127.0.0.1 AN_DASH_PORT=$PORT${AN_LEADERBOARD_READONLY:+ AN_LEADERBOARD_READONLY=1} $PY -I server.py"
  exit 0
fi

URL="http://127.0.0.1:$PORT/"
cat <<MSG

Qichuang dashboard demo (synthetic data, $MODE)
  data       $ROOT
  dashboard  $URL                     English: $URL#/overview?lang=en   kiosk: $URL#/overview?kiosk=45
  remote     ssh -L $PORT:127.0.0.1:$PORT <user>@<this machine>   then open the same URL on your computer
Stop with Ctrl+C.

MSG
cd "$DASH"
exec "$PY" -I server.py
