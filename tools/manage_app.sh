#!/usr/bin/env bash
# manage_app.sh
# Manage the Bilal app (frontend + backend service). Ensures ports are free
# and no duplicate service processes are running before starting.

set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$APP_DIR/logs"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/server_stdout.log"
FRONTEND_PIDFILE="$APP_DIR/tools/frontend.pid"

# Configurable ports
FRONTEND_PORT=${FRONTEND_PORT:-5173}
BACKEND_PORT=${BACKEND_PORT:-5000}
SERVICE_NAME=${SERVICE_NAME:-bilal-server.service}

echolog(){ echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) - $*"; }

find_pids_on_port(){
  local port="$1"
  # Prefer fuser, fall back to lsof, then ss parsing
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:"$port" 2>/dev/null || true
  else
    ss -ltnp 2>/dev/null | grep -E ":${port}\\b" | sed -n 's/.*pid=\([0-9]*\),.*/\1/p' || true
  fi
}

kill_pids(){
  local pids="$1"
  if [ -z "$pids" ]; then
    return
  fi
  echolog "Killing PIDs: $pids"
  for p in $pids; do
    if [ "$p" -eq 1 ] 2>/dev/null; then
      echolog "Refusing to kill PID 1"
      continue
    fi
    # Safety: ensure the process appears to belong to this app before killing.
    ok=0
    if [ -r "/proc/$p/cmdline" ]; then
      cmdline=$(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null || true)
      if echo "$cmdline" | grep -q "$APP_DIR"; then
        ok=1
      fi
      # Also allow killing python server.py and npm processes started from app dir
      if echo "$cmdline" | grep -E -q "server.py|npm|node"; then
        ok=1
      fi
    fi
    if [ "$ok" -ne 1 ]; then
      echolog "Skipping PID $p (does not appear to belong to app): $cmdline"
      continue
    fi
    kill "$p" 2>/dev/null || true
    sleep 0.5
    if kill -0 "$p" 2>/dev/null; then
      echolog "PID $p still alive, forcing"
      kill -9 "$p" 2>/dev/null || true
    fi
  done
}

stop_service(){
  echolog "Stopping systemd service if present: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl --quiet is-active "$SERVICE_NAME"; then
      sudo systemctl stop "$SERVICE_NAME" || true
      sleep 1
    fi
  fi
}

start_service(){
  echolog "Starting systemd service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl daemon-reload || true
    sudo systemctl enable --now "$SERVICE_NAME"
    sleep 1
  else
    echolog "systemctl not available; starting backend via venv fallback"
    if [ -x "$APP_DIR/.venv/bin/python" ]; then
      nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/server.py" >> "$BACKEND_LOG" 2>&1 &
    else
      nohup python3 "$APP_DIR/server.py" >> "$BACKEND_LOG" 2>&1 &
    fi
    sleep 1
  fi
}

stop_frontend(){
  echolog "Stopping frontend (PIDFILE: $FRONTEND_PIDFILE) and any process on port $FRONTEND_PORT"
  if [ -f "$FRONTEND_PIDFILE" ]; then
    pid=$(cat "$FRONTEND_PIDFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$FRONTEND_PIDFILE" || true
  fi
  local pids
  pids=$(find_pids_on_port "$FRONTEND_PORT" || true)
  kill_pids "$pids" || true
}

start_frontend(){
  echolog "Starting frontend (npm dev)"
  # Only start if package.json exists and port not in use
  if [ -f "$APP_DIR/package.json" ]; then
    local pids
    pids=$(find_pids_on_port "$FRONTEND_PORT" || true)
    if [ -n "$pids" ]; then
      echolog "Frontend port $FRONTEND_PORT already in use by: $pids"
    fi
    # Start with npm (prefer npm if available)
    if command -v npm >/dev/null 2>&1; then
      # Start frontend from the app directory so $! points to the npm background PID.
      oldpwd=$(pwd)
      cd "$APP_DIR"
      nohup npm run dev >> "$FRONTEND_LOG" 2>&1 &
      bgpid=$!
      cd "$oldpwd"
      sleep 1
      if [ -n "${bgpid}" ]; then
        echo "$bgpid" > "$FRONTEND_PIDFILE" || true
      else
        # Fallback: try to detect a process listening on the frontend port
        fgpids=$(find_pids_on_port "$FRONTEND_PORT" || true)
        if [ -n "$fgpids" ]; then
          echo "$fgpids" | awk '{print $1}' > "$FRONTEND_PIDFILE" || true
        fi
      fi
      echolog "Frontend started, log: $FRONTEND_LOG"
    else
      echolog "npm not installed; skipping frontend start"
    fi
  else
    echolog "No package.json; skipping frontend"
  fi
}

ensure_ports_free(){
  echolog "Ensuring ports $BACKEND_PORT and $FRONTEND_PORT are free"
  local bpids fids all
  bpids=$(find_pids_on_port "$BACKEND_PORT" || true)
  fids=$(find_pids_on_port "$FRONTEND_PORT" || true)
  all="$bpids $fids"
  if [ -n "$all" ]; then
    kill_pids "$all"
  fi
}

status(){
  echolog "Status report"
  echo "Service: $SERVICE_NAME"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl status --no-pager "$SERVICE_NAME" || true
  fi
  echo
  echolog "Processes listening on ports:"
  ss -ltnp | egrep ":(${BACKEND_PORT}|${FRONTEND_PORT})\\b" || true
}

cmd_start(){
  echolog "Start sequence: stop any existing, ensure ports free, start service and frontend"
  stop_service
  stop_frontend
  ensure_ports_free
  start_service
  start_frontend
  echolog "Start sequence finished"
}

cmd_stop(){
  echolog "Stop sequence: stop frontend, stop service, kill any remaining pids"
  stop_frontend
  stop_service
  ensure_ports_free
}

cmd_restart(){
  echolog "Restart requested"
  cmd_stop
  sleep 1
  cmd_start
}

case ${1:-help} in
  start)
    cmd_start
    ;;
  stop)
    cmd_stop
    ;;
  restart)
    cmd_restart
    ;;
  status)
    status
    ;;
  help|--help|-h)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 0
    ;;
  *)
    echo "Unknown command. Usage: $0 {start|stop|restart|status}"
    exit 2
    ;;
esac

exit 0
