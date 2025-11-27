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
python3 - <<PY
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
# Ensure built assets are owned by the app user
if [ -d "$APP_DIR/dist" ]; then
  chown -R $REAL_USER:$REAL_USER "$APP_DIR/dist" || true
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

# 4. Install Python Libraries
echo "Installing Python libraries (soco, flask)..."
# Attempt global install compatible with newer Debian (Bookworm)
sudo pip3 install soco flask --break-system-packages 2>/dev/null || sudo pip3 install soco flask

# 5. Create Systemd Services
echo "Creating systemd services..."

# Backend Service
SERVICE_FILE_BE="/etc/systemd/system/bilal-beapp.service"
sudo bash -c "cat > $SERVICE_FILE_BE" <<EOL
[Unit]
Description=Bilal Backend App
After=network.target

[Service]
User=$REAL_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

# Frontend Service
SERVICE_FILE_FE="/etc/systemd/system/bilal-feapp.service"
sudo bash -c "cat > $SERVICE_FILE_FE" <<EOL
[Unit]
Description=Bilal Frontend App
After=network.target

[Service]
User=$REAL_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/node $APP_DIR/server-static.cjs
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bilal-feapp

[Install]
WantedBy=multi-user.target
EOL

# 6. Enable and Start Services
echo "Enabling and starting services..."
sudo systemctl daemon-reload
sudo systemctl enable bilal-beapp.service
sudo systemctl enable bilal-feapp.service
sudo systemctl start bilal-beapp.service
sudo systemctl start bilal-feapp.service

echo "--- Installation Complete ---"
echo "App Directory: $APP_DIR"
echo "Service User:  $REAL_USER"
echo "Backend running on port 5000, Frontend on port 3000 (assuming)."
echo "Use manage.sh to control services."
