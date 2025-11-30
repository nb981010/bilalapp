#!/usr/bin/env bash
set -euo pipefail

# Simple static check: look for fetch('/api/settings' calls and warn if the following
# few lines don't include adding the X-BILAL-PASSCODE header. This is a heuristic
# intended to run in CI to catch accidental front-end calls that won't include the
# required passcode header when server-side enforcement is enabled.

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
echo "Running settings API usage check..."
BAD=0

grep -R "fetch('/api/settings'" --include="*.tsx" --exclude-dir=node_modules || true

while IFS= read -r -d '' file; do
  # For each occurrence, inspect next 12 lines for passcode header
  while IFS= read -r line; do
    lineno=$(echo "$line" | cut -d: -f1)
    # extract 12 lines after the match
    tail=$(sed -n "$((lineno+1)),$((lineno+12))p" "$file" || true)
    if echo "$tail" | grep -q "X-BILAL-PASSCODE"; then
      # ok
      :
    else
      echo "Warning: $file:$lineno calls /api/settings but does not appear to set X-BILAL-PASSCODE header"
      BAD=1
    fi
  done < <(grep -n "fetch('/api/settings'" "$file" | sed -e 's/^/"/' -e 's/$/"\0/' -n | sed 's/^\"//;s/\"\x00$//' | sed -n 'p' || true)
done < <(grep -Rl "fetch('/api/settings'" --include="*.tsx" -n0 || true)

if [[ $BAD -ne 0 ]]; then
  echo "Settings API usage check FAILED. If this is intentional, ensure server env var BILAL_ENFORCE_SETTINGS_API is not enabled, or adjust the UI to include the header." >&2
  exit 2
fi

echo "Settings API usage check passed."
exit 0
