#!/usr/bin/env bash
set -euo pipefail

# Wrapper that logs invocations and delegates to safe_service_restart.sh
# Usage: safe_service_wrapper.sh <action> <service-unit> <port> [--yes]

LOGDIR="logs"
LOGFILE="$LOGDIR/safe_service_restart.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAFE_SCRIPT="$SCRIPT_DIR/safe_service_restart.sh"

mkdir -p "$LOGDIR"

echo "$(date --iso-8601=seconds) - wrapper called: $*" >> "$LOGFILE"

if [[ ! -x "$SAFE_SCRIPT" ]]; then
  echo "ERROR: safe script not found or not executable: $SAFE_SCRIPT" | tee -a "$LOGFILE"
  exit 2
fi

# Log environment variables of interest (non-sensitive)
echo "ENV: BILAL_ENFORCE_SETTINGS_API=${BILAL_ENFORCE_SETTINGS_API-}" >> "$LOGFILE" || true

# Call the actual safe restart script and capture exit status
"$SAFE_SCRIPT" "$@" 2>&1 | tee -a "$LOGFILE"
RC=${PIPESTATUS[0]:-0}
echo "$(date --iso-8601=seconds) - wrapper finished (rc=$RC)" >> "$LOGFILE"
exit $RC
