#!/usr/bin/env bash
set -euo pipefail

# Minimal installer for Bilal app (repo-level `install.sh`).
# Installs system packages, Python libs (including SQLAlchemy) and Node helper for prayer times.

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Bilal installer running from: $APP_DIR"

echo "Updating apt and installing system packages..."
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv nodejs npm ffmpeg vlc curl

echo "Installing Python libraries (soco, flask, apscheduler, praytimes, tzlocal, requests, sqlalchemy)..."
# Try to use --break-system-packages where supported; ignore warnings if not.
sudo pip3 install --break-system-packages soco flask apscheduler praytimes tzlocal requests sqlalchemy || sudo pip3 install soco flask apscheduler praytimes tzlocal requests sqlalchemy

echo "Installing Node dependencies for scripts helper (adhan)..."
if [ -d "$APP_DIR/scripts" ] && [ -f "$APP_DIR/scripts/package.json" ]; then
  (cd "$APP_DIR/scripts" && npm ci --no-audit --no-fund || npm install --no-audit --no-fund)
else
  mkdir -p "$APP_DIR/scripts"
  cat > "$APP_DIR/scripts/package.json" <<'JSON'
{
  "name": "bilal-scripts",
  "version": "1.0.0",
  "private": true,
  "dependencies": {
    "adhan": "^4.0.0"
  }
}
JSON
  (cd "$APP_DIR/scripts" && npm install --no-audit --no-fund)
fi

echo "Initializing SQLite DB file (if not present)..."
DB_PATH="$APP_DIR/bilal_jobs.sqlite"
if [ ! -f "$DB_PATH" ]; then
  sqlite3 "$DB_PATH" "VACUUM;" || touch "$DB_PATH"
fi
chmod 664 "$DB_PATH" || true

echo "Installer finished. Next steps:"
echo " - Start the server: (env PRAYER_TZ='Asia/Dubai' BILAL_DB_PATH='$DB_PATH') python3 server.py"
echo " - Or set up systemd to run server as a service."

exit 0
