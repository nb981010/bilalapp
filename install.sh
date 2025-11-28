#!/usr/bin/env bash
set -euo pipefail

# Installer for Bilal app (repo-level `install.sh`).
# - Creates a Python virtualenv in `.venv`
# - Installs Python deps from `requirements.txt` (creates it if missing)
# - Installs Node deps for `scripts/` (adhan)
# - Optionally installs and enables a systemd service

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
DB_PATH="$APP_DIR/bilal_jobs.sqlite"
SERVICE_NAME="bilal.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

usage(){
  cat <<EOF
Usage: $0 [--service] [--start]
  --service    : create and enable systemd service (requires sudo)
  --start      : start the service after enabling
  --no-node    : skip installing Node deps
  --user USER  : systemd unit will run as USER (default: current user)
EOF
  exit 1
}

INSTALL_SERVICE=0
START_SERVICE=0
INSTALL_NODE=1
RUN_USER="$(id -un)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) INSTALL_SERVICE=1; shift ;;
    --start) START_SERVICE=1; shift ;;
    --no-node) INSTALL_NODE=0; shift ;;
    --user) RUN_USER="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1"; usage ;;
  esac
done

echo "Bilal installer running from: $APP_DIR"

echo "Updating apt and installing system packages..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-distutils nodejs npm sqlite3 curl

echo "Preparing Python virtualenv at $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
# Activate and upgrade pip
. "$VENV_DIR/bin/activate"
python3 -m pip install --upgrade pip

echo "Ensuring requirements.txt exists..."
if [ ! -f "$APP_DIR/requirements.txt" ]; then
  cat > "$APP_DIR/requirements.txt" <<'REQ'
soco
flask
apscheduler
praytimes
tzlocal
requests
sqlalchemy
REQ
fi

echo "Installing Python dependencies from requirements.txt into virtualenv..."
pip install -r "$APP_DIR/requirements.txt"

if [ $INSTALL_NODE -eq 1 ]; then
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
fi

echo "Initializing SQLite DB file (if not present)..."
if [ ! -f "$DB_PATH" ]; then
  sqlite3 "$DB_PATH" "VACUUM;" || touch "$DB_PATH"
fi
chmod 664 "$DB_PATH" || true

if [ $INSTALL_SERVICE -eq 1 ]; then
  echo "Creating systemd unit at $SERVICE_PATH (requires sudo)"
  sudo tee "$SERVICE_PATH" > /dev/null <<UNIT
[Unit]
Description=Bilal Azan Scheduler Service
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
Environment=PRAYER_TZ=Asia/Dubai
Environment=BILAL_DB_PATH=$DB_PATH
ExecStart=$VENV_DIR/bin/python3 $APP_DIR/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

  echo "Reloading systemd and enabling $SERVICE_NAME"
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"

  if [ $START_SERVICE -eq 1 ]; then
    echo "Starting $SERVICE_NAME"
    sudo systemctl start "$SERVICE_NAME"
    echo "Service status:"
    sudo systemctl status --no-pager "$SERVICE_NAME" || true
  fi
fi

echo "Installer finished. Next steps:"
echo " - Activate venv: source $VENV_DIR/bin/activate"
echo " - Run server manually: (env PRAYER_TZ='Asia/Dubai' BILAL_DB_PATH='$DB_PATH') $VENV_DIR/bin/python3 server.py"
if [ $INSTALL_SERVICE -eq 1 ]; then
  echo " - The systemd service '$SERVICE_NAME' was created and enabled for user '$RUN_USER'."
fi

deactivate || true

exit 0
