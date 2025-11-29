#!/bin/bash

# Bilal Installer Script
# -----------------------------------
# Run this on Raspberry Pi to setup the environment.

APP_DIR="$HOME/bilalapp"
LOG_DIR="$APP_DIR/logs"

# Detect the actual user if run via sudo
REAL_USER=${SUDO_USER:-$USER}

echo "--- Starting Installation for user: $REAL_USER ---"

# Create installation directory
echo "Creating installation directory: $APP_DIR"
mkdir -p "$APP_DIR"

# Copy application files to installation directory
echo "Copying application files..."
cp -r . "$APP_DIR"

# Apply App.tsx runtime fixes during install (idempotent)
echo "Patching App.tsx to add duplicate-trigger guard..."
python3 - <<'PY'
from pathlib import Path

app_dir = Path("$APP_DIR")
app_file = app_dir / "App.tsx"
if app_file.exists():
  s = app_file.read_text()
  # 1) Insert triggeredPrayersRef after intervalRef (if not present)
  if 'triggeredPrayersRef' not in s:
    s = s.replace(
      'const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);',
      'const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);\n  const triggeredPrayersRef = useRef(new Set<string>());'
    )

  # 2) Replace simple automatic-trigger if with guarded version (idempotent)
  old_if = 'if (now.getHours() === prayer.time.getHours() && now.getMinutes() === prayer.time.getMinutes() && now.getSeconds() === 0) {'
  if old_if in s and 'prayerKey' not in s:
    s = s.replace(
      old_if,
      "const prayerKey = `${prayer.name}-${format(prayer.time, 'yyyy-MM-dd-HH-mm')}`;\n        if (now.getHours() === prayer.time.getHours() && now.getMinutes() === prayer.time.getMinutes() && now.getSeconds() === 0 && !triggeredPrayersRef.current.has(prayerKey)) {\n          triggeredPrayersRef.current.add(prayerKey);"
    )

  # 3) Ensure test fast-forward triggers Fajr (idempotent)
  if 'playAzan(PrayerName.Dhuhr);' in s:
    s = s.replace('playAzan(PrayerName.Dhuhr);', 'playAzan(PrayerName.Fajr);')

  app_file.write_text(s)
  print('App.tsx patched')
else:
  print('App.tsx not found, skipping patch')
PY

# Install Node.js (NodeSource) and build tools, then build the frontend
echo "Installing Node.js (NodeSource) and build tools..."
# Install NodeSource Node.js 18.x LTS
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs build-essential
cd "$APP_DIR"
# Prefer reproducible install via npm ci when lockfile present
if [ -f package-lock.json ]; then
  npm ci --silent || npm install --silent
else
  npm install --silent
fi
# Build the frontend (Vite) so static assets exist in dist/
if npm run build --silent; then
  echo "Frontend build completed"
else
  echo "Frontend build failed (vite may be missing); attempting fallback install of dev deps and rebuild"
  npm install --silent
  npm run build --silent || echo "Frontend build ultimately failed"
fi

# 0. Fix Empty Files (Manual Recovery)
# If server.txt exists but server.py is missing or empty, copy it.
if [ -f "$APP_DIR/server.txt" ] && [ -s "$APP_DIR/server.txt" ]; then
    echo "Restoring server.py from server.txt..."
    cp "$APP_DIR/server.txt" "$APP_DIR/server.py"
fi

# 1. Check for server.py
if [ ! -f "$APP_DIR/server.py" ]; then
  echo "ERROR: server.py not found in $APP_DIR."
  exit 1
fi

# 2. Create Logs Directory
echo "Configuring directories..."
if [ ! -d "$LOG_DIR" ]; then
  mkdir -p "$LOG_DIR"
  chmod 777 "$LOG_DIR"
  echo "Created $LOG_DIR"
else
  # Ensure permissions are open so the service can write
  chmod 777 "$LOG_DIR"
fi

# 3. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-flask vlc ffmpeg nodejs

echo "Creating systemd services..."
# Ensure .env exists with defaults including GUNICORN_WORKERS
if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<EOF
# Environment for bilal backend
PRAYER_PLAY_TOL_MIN=5
GUNICORN_WORKERS=2
EOF
  chown $REAL_USER:$REAL_USER "$APP_DIR/.env" || true
  chmod 640 "$APP_DIR/.env" || true
fi
# 4. Install Python Libraries (prefer isolated venv)
echo "Setting up Python virtualenv and installing dependencies..."
# Create a venv under the app directory so we don't need system pip installs
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
  # Upgrade packaging tools inside venv
  "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel || true
  # Install from requirements if available, otherwise install core runtime deps
  if [ -f "$APP_DIR/requirements.TXT" ]; then
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.TXT" || true
  else
    "$APP_DIR/venv/bin/pip" install soco praytimes schedule python-dotenv gunicorn apscheduler tzlocal flask || true
  fi
  # Ensure the app user owns the venv
  chown -R $REAL_USER:$REAL_USER "$APP_DIR/venv" || true
else
  echo "Virtualenv already exists at $APP_DIR/venv — upgrading packages from requirements if present"
  "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel || true
  if [ -f "$APP_DIR/requirements.TXT" ]; then
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.TXT" || true
  fi
fi

# As a fallback, if system pip is allowed, try to ensure a minimal set is available system-wide.
sudo pip3 install soco flask --break-system-packages 2>/dev/null || sudo pip3 install soco flask 2>/dev/null || true

#!/bin/bash

# Bilal Installer Script (idempotent)
# Prefers creating a Python virtualenv and writing systemd units that use the venv

set -euo pipefail

APP_DIR="$HOME/bilalapp"
LOG_DIR="$APP_DIR/logs"
REAL_USER=${SUDO_USER:-$USER}

echo "--- Starting Installation for user: $REAL_USER ---"

# Ensure app directory exists
mkdir -p "$APP_DIR"

# Copy files to app dir (idempotent)
echo "Copying application files to $APP_DIR (idempotent)"
rsync -a --exclude=.git --exclude=venv . "$APP_DIR/"

cd "$APP_DIR"

# Build frontend
echo "Installing Node.js build tools and building frontend (if applicable)..."
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get update
sudo apt-get install -y nodejs build-essential || true
if [ -f package-lock.json ]; then
  npm ci --silent || npm install --silent || true
else
  npm install --silent || true
fi
if npm run build --silent; then
  echo "Frontend build completed"
else
  echo "Frontend build failed; attempting fallback dev install and rebuild"
  npm install --silent || true
  npm run build --silent || true
fi
# Ensure built assets are owned by the app user
if [ -d "$APP_DIR/dist" ]; then
  chown -R $REAL_USER:$REAL_USER "$APP_DIR/dist" || true
fi

# Ensure logs directory exists and has permissive perms for the service
mkdir -p "$LOG_DIR"
chmod 777 "$LOG_DIR" || true

# Python virtualenv and deps
echo "Setting up Python virtualenv and dependencies..."
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel || true
  if [ -f "$APP_DIR/requirements.TXT" ]; then
    "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.TXT" || true
  else
    "$APP_DIR/venv/bin/pip" install soco praytimes schedule python-dotenv gunicorn apscheduler tzlocal flask || true
  fi
  chown -R $REAL_USER:$REAL_USER "$APP_DIR/venv" || true
else
  echo "venv already present; upgrading packaging tools"
  "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel || true
fi

# Create .env with defaults (idempotent)
if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<EOF
 # Environment for bilal backend
 PRAYER_PLAY_TOL_MIN=5
 # Number of gunicorn worker processes (adjust for your CPU count)
 GUNICORN_WORKERS=2
EOF
  chown $REAL_USER:$REAL_USER "$APP_DIR/.env" || true
  chmod 640 "$APP_DIR/.env" || true
fi

# Create systemd services pointing to venv gunicorn and node static server
echo "Creating systemd unit files (bilal-beapp, bilal-feapp)"
SERVICE_BE=/etc/systemd/system/bilal-beapp.service
SERVICE_FE=/etc/systemd/system/bilal-feapp.service
GUNICORN_BIN="$APP_DIR/venv/bin/gunicorn"

sudo bash -c "cat > $SERVICE_BE" <<EOL
[Unit]
Description=Bilal Backend (gunicorn)
After=network.target

[Service]
 User=$REAL_USER
 WorkingDirectory=$APP_DIR
 EnvironmentFile=$APP_DIR/.env
 ExecStart=$GUNICORN_BIN --workers \${GUNICORN_WORKERS} --bind 0.0.0.0:5000 --access-logfile - --error-logfile - server:app
 Restart=on-failure
 RestartSec=10
 StandardOutput=journal
 StandardError=journal
 SyslogIdentifier=bilal-beapp

[Install]
WantedBy=multi-user.target
EOL

# Ensure server-static.cjs exists and is owned by app user
cat > "$APP_DIR/server-static.cjs" <<'NODE'
const http = require('http');
const fs = require('fs');
const path = require('path');
const port = process.env.PORT || 3000;
const root = path.resolve(__dirname, 'dist');
const mime = {
  '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.json':'application/json',
  '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml', '.ico':'image/x-icon', '.map':'application/json'
};
const server = http.createServer((req, res) => {
  try {
    let reqpath = decodeURIComponent(req.url.split('?')[0]);
    if (reqpath === '/') reqpath = '/index.html';
    let file = path.join(root, reqpath);
    fs.stat(file, (err, stat) => {
      if (err) { res.writeHead(404); res.end('Not Found'); return; }
      if (stat.isDirectory()) file = path.join(file, 'index.html');
      const ext = path.extname(file);
      const ct = mime[ext] || 'application/octet-stream';
      res.writeHead(200, { 'Content-Type': ct, 'Cache-Control': 'public, max-age=31536000' });
      fs.createReadStream(file).pipe(res);
    });
  } catch (e) { res.writeHead(500); res.end('Server Error'); }
});
server.listen(port, () => console.log('Static server serving', root, 'on port', port));
NODE
chmod 755 "$APP_DIR/server-static.cjs" || true
chown $REAL_USER:$REAL_USER "$APP_DIR/server-static.cjs" || true

sudo bash -c "cat > $SERVICE_FE" <<EOL
[Unit]
Description=Bilal Frontend App
After=network.target

[Service]
User=$REAL_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/node $APP_DIR/server-static.cjs
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bilal-feapp

[Install]
WantedBy=multi-user.target
EOL

# Ensure ownership for dist and other created files
chown -R $REAL_USER:$REAL_USER "$APP_DIR/dist" || true
chown $REAL_USER:$REAL_USER "$APP_DIR/.env" || true

echo "Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable --now bilal-beapp.service || true
sudo systemctl enable --now bilal-feapp.service || true

echo "--- Verification ---"
sudo systemctl is-active --quiet bilal-beapp.service && echo "bilal-beapp: active" || echo "bilal-beapp: inactive"
sudo systemctl is-active --quiet bilal-feapp.service && echo "bilal-feapp: active" || echo "bilal-feapp: inactive"
echo "Listening ports:"; sudo ss -ltnp | egrep ':5000|:3000' || true

echo "--- Installation Complete ---"
echo "App Directory: $APP_DIR"
echo "Service User:  $REAL_USER"
echo "Backend running on port 5000, Frontend on port 3000 (if active)."
echo "Manage services with: sudo systemctl status|restart bilal-beapp.service bilal-feapp.service"
