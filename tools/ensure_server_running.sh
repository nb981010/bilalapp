#!/usr/bin/env bash
# ensure_server_running.sh
# Simple watchdog to ensure the bilal server is running; can be run from cron.

set -euo pipefail
REPO_DIR="/home/nbc/bilalapp"
LOG_FILE="$REPO_DIR/logs/server_stdout.log"
PYTHON="/usr/bin/python3"
SERVER_SCRIPT="$REPO_DIR/server.py"
HEALTH_URL="http://127.0.0.1:5000/api/scheduler/jobs"

# Check HTTP health
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    exit 0
  fi
fi

# No HTTP response: try to detect process
if pgrep -f "python.*server.py" >/dev/null 2>&1; then
  # process exists but not responding; restart
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) - server not responsive, restarting" >> "$LOG_FILE"
  pkill -f "python.*server.py" || true
  sleep 1
fi

# Start server in background, redirecting output to log
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) - starting server" >> "$LOG_FILE"
nohup "$PYTHON" "$SERVER_SCRIPT" > "$LOG_FILE" 2>&1 &
sleep 1
exit 0
