#!/bin/bash
# Research dashboard (bilingual) -- supervisor wrapper for the Vast.ai base image: FastAPI on 127.0.0.1:$PORT,
# exposed through the Caddy auth edge by the /etc/portal.yaml entry named $PORTAL_NAME (使用指南.md §7.1).
# Copy to /opt/supervisor-scripts/<name>.sh and edit the block below. The values shown are the AN (VS) project's.
PROJECT=/workspace/an_project                 # project root (AN_ROOT): state/ runs/ results/ paper/
DASH_DIR="$PROJECT/dashboard"                 # the directory that holds server.py and static/
PORTAL_NAME="AN Dashboard"                    # must equal the application name in /etc/portal.yaml
VENV=/venv/main                               # Python env with requirements.txt installed (a separate venv is safer)
PORT=17100                                    # internal port (portal.yaml internal_port)
# optional features: leave a value empty to switch the feature off
TRANSCRIPTS=/root/.claude/projects/-workspace # Claude Code transcripts (Agents / Session views): ls ~/.claude/projects/
RAW=/workspace/an_data/raw                    # System view: dataset extraction progress (du -sb of this directory) ...
RAW_TOTAL=104236481492                        # ... against this many bytes
ALERT_SERVICES=an_jobrunner0,an_jobrunner1,an_diskguard   # supervisor programs that must be RUNNING

utils=/opt/supervisor-scripts/utils
. "${utils}/logging.sh"
. "${utils}/environment.sh"                 # exports /etc/environment + ${WORKSPACE}/.env
. "${utils}/exit_portal.sh" "$PORTAL_NAME"  # self-skips if $PORTAL_NAME isn't in /etc/portal.yaml

source "$VENV/bin/activate"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONUNBUFFERED=1
export AN_ROOT="$PROJECT" AN_DASH_HOST=127.0.0.1 AN_DASH_PORT="$PORT"
export AN_TRANSCRIPTS="$TRANSCRIPTS" AN_RAW="$RAW" AN_RAW_TOTAL="$RAW_TOTAL" AN_ALERT_SERVICES="$ALERT_SERVICES"
cd "$DASH_DIR" || exit 1
pty python -I "$DASH_DIR/server.py" 2>&1
