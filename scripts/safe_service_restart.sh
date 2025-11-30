#!/usr/bin/env bash
set -euo pipefail

# Safe service control script for Bilal services
# Usage:
#   ./scripts/safe_service_restart.sh restart <service-unit> <port> [--yes]
#   ./scripts/safe_service_restart.sh stop <service-unit> <port> [--yes]
#   ./scripts/safe_service_restart.sh start <service-unit> <port> [--yes]
#
# Behavior:
# - Checks whether <port> is listening before/after operations.
# - If a process is listening on <port>, it reports PID(s) and command line.
# - It will only kill PIDs whose command line contains the string "bilal" (case-insensitive)
#   or the given service unit name. This prevents accidental kills of unrelated processes.
# - By default it asks for confirmation before killing; pass --yes to skip confirmation.

CONFIRM=1
if [[ ${@: -1} == "--yes" ]]; then
  CONFIRM=0
  set -- "${@:1:$(($#-1))}" # remove last arg
fi

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 {start|stop|restart} <service-unit> <port> [--yes]"
  exit 2
fi

ACTION=$1
SERVICE=$2
PORT=$3

log() { echo "[safe-service] $*"; }

get_listening_pids() {
  local port=$1
  local pids=()

  if command -v lsof >/dev/null 2>&1; then
    mapfile -t pids < <(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t || true)
  else
    # fallback to ss parsing
    while read -r line; do
      pid=$(echo "$line" | sed -n 's/.*pid=\([0-9]*\),.*/\1/p') || true
      if [[ -n "$pid" ]]; then
        pids+=("$pid")
      fi
    done < <(ss -ltnp 2>/dev/null | grep -E ":${port}\b" || true)
  fi

  # output unique pids
  if [[ ${#pids[@]} -gt 0 ]]; then
    printf "%s\n" "${pids[@]}" | sort -u
  fi
}

is_safe_to_kill() {
  local pid=$1
  if [[ ! -e /proc/${pid}/cmdline ]]; then
    return 1
  fi
  cmd=$(tr '\0' ' ' < /proc/${pid}/cmdline 2>/dev/null || true)
  # case-insensitive match for 'bilal' or service name
  if echo "$cmd" | grep -qi "bilal"; then
    return 0
  fi
  if echo "$cmd" | grep -qi "${SERVICE}"; then
    return 0
  fi
  return 1
}

confirm_or_die() {
  if [[ $CONFIRM -eq 0 ]]; then
    return 0
  fi
  read -r -p "$1 [y/N]: " ans
  case "$ans" in
    [Yy]|[Yy][Ee][Ss]) return 0 ;;
    *) echo "Aborted."; exit 3 ;;
  esac
}

check_and_report() {
  local port=$1
  pids=($(get_listening_pids "$port"))
  if [[ ${#pids[@]} -eq 0 ]]; then
    log "Port ${port} is free (no LISTEN)."
    return 0
  fi
  log "Port ${port} is LISTENED by PID(s): ${pids[*]}"
  for pid in "${pids[@]}"; do
    if [[ -e /proc/${pid}/cmdline ]]; then
      cmd=$(tr '\0' ' ' < /proc/${pid}/cmdline || true)
    else
      cmd="(no cmdline available)"
    fi
    owner=$(ps -o user= -p ${pid} 2>/dev/null || true)
    echo "  PID ${pid} (user: ${owner}): ${cmd}"
  done
  return 1
}

do_stop() {
  log "Stopping systemd service ${SERVICE}..."
  sudo systemctl stop "${SERVICE}"
  sleep 2
  # wait briefly for process to exit
  for i in {1..6}; do
    if ! get_listening_pids "$PORT" >/dev/null; then
      break
    fi
    sleep 1
  done

  pids=($(get_listening_pids "$PORT"))
  if [[ ${#pids[@]} -eq 0 ]]; then
    log "Port ${PORT} is free after stopping ${SERVICE}."
    return 0
  fi

  log "Port ${PORT} still in use by PID(s): ${pids[*]}. Evaluating safety to kill..."
  to_kill=()
  for pid in "${pids[@]}"; do
    if is_safe_to_kill "$pid"; then
      to_kill+=("$pid")
    else
      log "Refusing to kill PID ${pid} because it doesn't look like a bilal process." 
    fi
  done

  if [[ ${#to_kill[@]} -eq 0 ]]; then
    echo "No safe PIDs to kill. Manual intervention required." >&2
    return 4
  fi

  echo "About to kill these PIDs: ${to_kill[*]}"
  confirm_or_die "Kill the above PIDs?"

  for pid in "${to_kill[@]}"; do
    log "Killing PID ${pid}..."
    sudo kill -TERM "$pid" || sudo kill -KILL "$pid" || true
  done

  sleep 1
  if [[ -n "$(get_listening_pids "$PORT")" ]]; then
    echo "Port ${PORT} still in use after kill attempts." >&2
    return 5
  fi

  log "Port ${PORT} freed."
  return 0
}

do_start() {
  log "Starting systemd service ${SERVICE}..."
  sudo systemctl start "${SERVICE}"
  sleep 2
  # wait up to 10s for port to be LISTEN
  for i in {1..10}; do
    if get_listening_pids "$PORT" >/dev/null; then
      log "Service listening on port ${PORT}."
      return 0
    fi
    sleep 1
  done
  echo "Service did not start listening on port ${PORT} within timeout." >&2
  return 6
}

case "$ACTION" in
  stop)
    check_and_report "$PORT" || true
    do_stop
    ;;
  start)
    check_and_report "$PORT" || true
    do_start
    ;;
  restart)
    check_and_report "$PORT" || true
    do_stop
    do_start
    ;;
  *)
    echo "Unknown action: $ACTION" >&2
    echo "Usage: $0 {start|stop|restart} <service-unit> <port> [--yes]"
    exit 2
    ;;
esac

exit $?
