#!/usr/bin/env bash
set -euo pipefail

# idempotent installer for bilalapp
# - deploys code to /opt/bilalapp (or custom $DEPLOY)
# - creates service user
# - creates python venv and installs requirements
# - installs systemd unit files for backend/frontend and an env file
# - enables & starts services

APP="bilalapp"
DEPLOY="/opt/$APP"
SERVICE_USER="bilal"
ENV_DIR="/etc/$APP"
ENV_FILE="$ENV_DIR/env"
SRC_DIR="${SRC_DIR:-$(pwd)}"
PYTHON_BIN="python3"

echo "Bilal App installer"
echo "Source directory: $SRC_DIR"
echo "Deploy directory: $DEPLOY"

require_sudo() {
  if [ "$EUID" -ne 0 ]; then
    echo "This installer requires sudo for system operations. Re-run as root or allow sudo when prompted."
  fi
}

ensure_user() {
  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Creating service user: $SERVICE_USER"
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER" || true
  else
    echo "Service user $SERVICE_USER already exists"
  fi
}

backup_if_exists() {
  local path="$1"
  if [ -e "$path" ]; then
    local b="$path.bak.$(date +%s)"
    echo "Backing up $path → $b"
    sudo cp -a "$path" "$b"
  fi
}

deploy_code() {
  echo "Deploying code from $SRC_DIR to $DEPLOY"
  sudo mkdir -p "$DEPLOY"
  # sync; exclude virtualenv, node_modules and logs by default
  sudo rsync -a --delete --exclude='.venv' --exclude='node_modules' --exclude='logs' "$SRC_DIR/" "$DEPLOY/"
  sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY"
}

create_venv_and_install() {
  echo "Creating virtualenv and installing Python dependencies"
  # create venv if missing
  if [ ! -d "$DEPLOY/.venv" ]; then
    sudo -u "$SERVICE_USER" $PYTHON_BIN -m venv "$DEPLOY/.venv"
    sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY/.venv"
  else
    echo ".venv already exists at $DEPLOY/.venv"
  fi

  # Upgrade pip and install requirements if present
  if [ -f "$DEPLOY/requirements.txt" ]; then
    echo "Installing Python requirements (may take a while)"
    sudo -u "$SERVICE_USER" "$DEPLOY/.venv/bin/pip" install --upgrade pip setuptools wheel
    sudo -u "$SERVICE_USER" "$DEPLOY/.venv/bin/pip" install -r "$DEPLOY/requirements.txt"
  else
    echo "No requirements.txt found; skipping pip install"
  fi
}

write_env_file() {
  echo "Writing environment file to $ENV_FILE"
  sudo mkdir -p "$ENV_DIR"
  # default values; users may override later
  sudo tee "$ENV_FILE" >/dev/null <<EOF
BILAL_DB_PATH=$DEPLOY/bilal_jobs.sqlite
PRAYER_TZ=Asia/Dubai
LOG_DIR=$DEPLOY/logs
EOF
  sudo chown root:root "$ENV_FILE"
  sudo chmod 0640 "$ENV_FILE"
}

install_systemd_units() {
  echo "Installing systemd unit files"

  # backend unit
  local be_unit=/etc/systemd/system/${APP}.be.service
  backup_if_exists "$be_unit"
  sudo tee "$be_unit" >/dev/null <<'EOF'
[Unit]
Description=Bilal Backend Service
After=network.target

[Service]
Type=simple
User=bilal
WorkingDirectory=/opt/bilalapp
EnvironmentFile=/etc/bilalapp/env
ExecStart=/opt/bilalapp/.venv/bin/python3 /opt/bilalapp/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  # frontend unit (optional; only if frontend static server or dev server used)
  local fe_unit=/etc/systemd/system/${APP}.fe.service
  backup_if_exists "$fe_unit"
  sudo tee "$fe_unit" >/dev/null <<'EOF'
[Unit]
Description=Bilal Frontend Service
After=network.target

[Service]
Type=simple
User=bilal
WorkingDirectory=/opt/bilalapp
EnvironmentFile=/etc/bilalapp/env
# Adjust this ExecStart if you host frontend differently (e.g. serve built files via nginx)
ExecStart=/bin/true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  # enable backend; frontend unit is a placeholder (enable if you replace ExecStart)
  sudo systemctl enable --now ${APP}.be.service || true
  sudo systemctl enable ${APP}.fe.service || true
}

setup_logrotate() {
  echo "Installing logrotate config"
  local lr=/etc/logrotate.d/${APP}
  backup_if_exists "$lr"
  sudo tee "$lr" >/dev/null <<EOF
$DEPLOY/logs/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
EOF
}

finalize() {
  echo "Finalizing installation"
  sudo mkdir -p $DEPLOY/logs
  sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$DEPLOY"
  echo "Installation complete. Check service status with: sudo systemctl status ${APP}.be.service"
}

main() {
  require_sudo
  ensure_user
  deploy_code
  create_venv_and_install
  write_env_file
  install_systemd_units
  setup_logrotate
  finalize
}

main "$@"

# End of installer
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
SERVICE_NAME="bilalapp.main.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

usage(){
  cat <<EOF
Usage: $0 [--service] [--start]
  --service    : create and enable systemd service (requires sudo)
  --start      : start the service after enabling
  --no-node    : skip installing Node deps
  --user USER  : systemd unit will run as USER (default: current user)
  --force-env  : overwrite existing /etc/default/bilal if present
  --create-user: create the specified system user if it does not exist (requires sudo)
EOF
  exit 1
}

INSTALL_SERVICE=0
START_SERVICE=0
INSTALL_NODE=1
FORCE_ENV=0
CREATE_USER=0
RUN_USER="$(id -un)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) INSTALL_SERVICE=1; shift ;;
    --start) START_SERVICE=1; shift ;;
    --no-node) INSTALL_NODE=0; shift ;;
    --user) RUN_USER="$2"; shift 2 ;;
    --force-env) FORCE_ENV=1; shift ;;
    --create-user) CREATE_USER=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1"; usage ;;
  esac
done

echo "Bilal installer running from: $APP_DIR"

echo "Updating apt and installing system packages..."
sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-distutils nodejs npm sqlite3 curl iproute2 psmisc

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
  echo "Installing Node dependencies for frontend app..."
  if [ -f "$APP_DIR/package.json" ]; then
    (cd "$APP_DIR" && npm ci --no-audit --no-fund || npm install --no-audit --no-fund)
  else
    echo "Warning: No package.json found in app root. Skipping frontend dependencies."
  fi

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

echo "Ensuring settings table exists and default production passcode is set (default: 2234)..."
# Ensure the settings table exists before attempting to insert the passcode
sqlite3 "$DB_PATH" "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);" || true
# Insert passcode only if missing; do not overwrite an existing passcode.
sqlite3 "$DB_PATH" "INSERT OR IGNORE INTO settings (key, value) VALUES ('passcode','2234');" || true

# Ensure DB file ownership is appropriate for the runtime user (if using system service)
if [ -n "$RUN_USER" ]; then
  sudo chown "$RUN_USER":"$RUN_USER" "$DB_PATH" || true
fi

if [ $INSTALL_SERVICE -eq 1 ]; then
  echo "Creating systemd unit at $SERVICE_PATH (requires sudo)"
  # Write an env file that the unit will consume (preserve if exists unless forced)
  ENV_PATH="/etc/default/bilal"
  # Optionally create the system user before writing the env / enabling the unit
  if [ "$CREATE_USER" -eq 1 ] || [ "$RUN_USER" = "bilal" ]; then
    echo "Ensuring system user '$RUN_USER' exists (requires sudo)..."
    if id -u "$RUN_USER" >/dev/null 2>&1; then
      echo "User '$RUN_USER' already exists. Skipping creation."
    else
      if [ -f "$APP_DIR/systemd/create_bilal_user.sh" ]; then
        echo "Calling helper to create user: $APP_DIR/systemd/create_bilal_user.sh $APP_DIR $RUN_USER"
        sudo bash "$APP_DIR/systemd/create_bilal_user.sh" "$APP_DIR" "$RUN_USER"
      else
        echo "Helper script not found; creating user via useradd"
        sudo useradd --system --create-home --shell /usr/sbin/nologin "$RUN_USER"
        sudo mkdir -p /home/$RUN_USER
        sudo chown -R $RUN_USER:$RUN_USER /home/$RUN_USER
        sudo chown -R $RUN_USER:$RUN_USER "$APP_DIR"
      fi
    fi
  fi

  if [ -f "$ENV_PATH" ] && [ $FORCE_ENV -ne 1 ]; then
    echo "$ENV_PATH already exists — preserving it (use --force-env to overwrite)"
  else
    echo "Writing environment file to $ENV_PATH (requires sudo)"
    sudo tee "$ENV_PATH" > /dev/null <<ENV
# Environment file for bilal service
PRAYER_TZ=Asia/Dubai
BILAL_DB_PATH=$DB_PATH
APP_DIR=$APP_DIR
VENV_DIR=$VENV_DIR
ENV
  fi

[ -n "$SERVICE_PATH" ] || true
  echo "Creating systemd unit at $SERVICE_PATH (requires sudo)"
  sudo tee "$SERVICE_PATH" > /dev/null <<UNIT
[Unit]
Description=Bilal Azan Scheduler Service
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_PATH
ExecStart=${VENV_DIR}/bin/python3 ${APP_DIR}/server.py
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
