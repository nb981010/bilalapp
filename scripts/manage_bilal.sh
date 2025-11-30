#!/usr/bin/env bash
set -euo pipefail

# manage_bilal.sh - Manage Bilal app (service, backend, frontend)
# Usage: manage_bilal.sh {start|stop|restart|status} [--frontend]
#
# Behavior:
#  - Ensures ports are free (kills processes listening on configured ports)
#  - Stops/starts the systemd service `bilal.service` (uses sudo)
#  - Optionally starts/stops the frontend dev server (`npm run dev`) in background
#

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
FRONTEND_PID_FILE="$ROOT_DIR/.frontend.pid"
FRONTEND_LOG="$LOG_DIR/frontend.log"

PORTS=(5000 5173)
SERVICE_NAME="bilal.service"

ensure_logs_dir() {
  mkdir -p "$LOG_DIR"
  chmod 755 "$LOG_DIR"
}

ps_on_port() {
  local port=$1
  lsof -t -i :${port} 2>/dev/null || true
}

kill_port_procs() {
  local port=$1
  local pids
  pids=$(ps_on_port "$port")
  if [ -z "$pids" ]; then
    return 0
  fi
  echo "Found processes on port $port: $pids"
  for pid in $pids; do
    echo "Stopping PID $pid (port $port)";
    kill "$pid" 2>/dev/null || true
  done
  sleep 1
  # force kill if still present
  pids=$(ps_on_port "$port")
  if [ -n "$pids" ]; then
    for pid in $pids; do
      echo "Force killing PID $pid (port $port)";
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
}

stop_frontend() {
  if [ -f "$FRONTEND_PID_FILE" ]; then
    pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)
    if [ -n "$pid" ]; then
      echo "Stopping frontend (PID $pid)"
      kill "$pid" 2>/dev/null || true
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        echo "Frontend PID $pid still alive, killing -9"
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$FRONTEND_PID_FILE"
  else
    # fallback: kill any process on vite default port
    for p in "$(ps_on_port 5173)"; do
      if [ -n "$p" ]; then
        echo "Killing stray frontend PID $p"
        kill -9 "$p" 2>/dev/null || true
      fi
    done
  fi
}

start_frontend() {
  ensure_logs_dir
  echo "Starting frontend (vite) in background, logging to $FRONTEND_LOG"
  cd "$ROOT_DIR"
  # prefer npm if available
  if command -v npm >/dev/null 2>&1; then
    nohup npm run dev >"$FRONTEND_LOG" 2>&1 &
    echo $! >"$FRONTEND_PID_FILE"
    echo "Frontend started (PID $(cat $FRONTEND_PID_FILE))"
  else
    echo "npm not found; frontend dev server not started"
  fi
}

stop_service() {
  echo "Stopping systemd service $SERVICE_NAME (if active)"
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    sudo systemctl stop "$SERVICE_NAME"
    sleep 1
  fi
}

start_service() {
  echo "Starting systemd service $SERVICE_NAME"
  sudo systemctl daemon-reload
  sudo systemctl enable --now "$SERVICE_NAME"
}

status() {
  echo "=== Service status ==="
  sudo systemctl status "$SERVICE_NAME" --no-pager || true
  echo
  echo "=== Listening processes on configured ports ==="
  for p in "${PORTS[@]}"; do
    echo "Port $p:"; ss -ltnp "sport = :$p" || true
  done
  echo
  if [ -f "$FRONTEND_PID_FILE" ]; then
    echo "Frontend PID file: $(cat $FRONTEND_PID_FILE)" || true
  fi
}

do_start() {
  echo "Preparing to start Bilal app..."
  ensure_logs_dir
  # Ensure ports are clear
  for p in "${PORTS[@]}"; do
    kill_port_procs "$p"
  done

  # Stop frontend and service first
  stop_frontend
  stop_service

  # Ensure ports cleared after stopping
  for p in "${PORTS[@]}"; do
    kill_port_procs "$p"
  done

  # Start systemd service
  start_service

  # Start frontend if requested
  if [ "$START_FRONTEND" = "1" ]; then
    start_frontend
  fi

  echo "Start sequence complete. Check logs with: sudo journalctl -u $SERVICE_NAME -f";
}

do_stop() {
  echo "Stopping Bilal app (service + frontend + freeing ports)"
  stop_frontend
  stop_service
  for p in "${PORTS[@]}"; do
    kill_port_procs "$p"
  done
  echo "Stopped."
}

do_restart() {
  do_stop
  sleep 1
  do_start
}

# --- main
if [ "$#" -lt 1 ]; then
  echo "Usage: $0 {start|stop|restart|status} [--frontend]"
  exit 2
fi

ACTION="$1"; shift || true
START_FRONTEND=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --frontend) START_FRONTEND=1; shift;;
    *) shift;;
  esac
done

case "$ACTION" in
  start) do_start ;; 
  stop) do_stop ;; 
  restart) do_restart ;; 
  status) status ;; 
  *) echo "Unknown action: $ACTION"; exit 2 ;;
esac

exit 0
