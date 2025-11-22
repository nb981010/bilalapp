import { ZoneId, SonosZone } from './types.ts';

export const DUBAI_COORDS = {
  latitude: 25.2048,
  longitude: 55.2708
};

export const INITIAL_ZONES: SonosZone[] = [
  { id: ZoneId.Pool, name: 'Pool Area', isAvailable: true, status: 'playing_music', volume: 40 },
  { id: ZoneId.Boy1, name: "Boy 1 Room", isAvailable: true, status: 'idle', volume: 25 },
  { id: ZoneId.Zone1, name: 'Living Room', isAvailable: true, status: 'playing_music', volume: 30 },
  { id: ZoneId.Zone2, name: 'Kitchen', isAvailable: true, status: 'idle', volume: 30 },
  { id: ZoneId.Zone3, name: 'Master Bed', isAvailable: true, status: 'idle', volume: 20 },
  { id: ZoneId.Zone4, name: 'Guest Room', isAvailable: false, status: 'idle', volume: 0 }, // Simulated offline
  { id: ZoneId.Zone5, name: 'Majlis', isAvailable: true, status: 'idle', volume: 45 },
];

export const INSTALL_SCRIPT = `#!/bin/bash

# Bilal Installer Script (install.sh)
# -----------------------------------
# Run this on Raspberry Pi to setup the environment.

APP_DIR=$(pwd)
LOG_DIR="/logs"

# Detect the actual user if run via sudo
REAL_USER=\${SUDO_USER:-\$USER}

echo "--- Starting Installation for user: \$REAL_USER ---"

# 1. Check for server.py
if [ ! -f "$APP_DIR/server.py" ]; then
  echo "ERROR: server.py not found in $APP_DIR."
  echo "Please ensure you have created server.py before running this script."
  exit 1
fi

# 2. Create Logs Directory
echo "Configuring directories..."
if [ ! -d "$LOG_DIR" ]; then
  sudo mkdir -p $LOG_DIR
  sudo chmod 777 $LOG_DIR
  echo "Created $LOG_DIR"
else
  # Ensure permissions are open so the service can write
  sudo chmod 777 $LOG_DIR
fi

# 3. Install System Dependencies
echo "Installing system dependencies..."
sudo apt-get update
# Install python3-venv just in case, though we use break-system-packages for simplicity on Lite
sudo apt-get install -y python3-pip python3-flask vlc ffmpeg

# 4. Install Python Libraries
echo "Installing Python libraries (soco, flask)..."
# Attempt global install compatible with newer Debian (Bookworm)
sudo pip3 install soco flask --break-system-packages 2>/dev/null || sudo pip3 install soco flask

# 5. Create Systemd Service
echo "Creating background service (bilal.service)..."
SERVICE_FILE="/etc/systemd/system/bilal.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Bilal Azan Controller
After=network.target

[Service]
User=$REAL_USER
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/server.py
Restart=always
# Wait a bit before restarting to prevent tight loops if failing
RestartSec=10
StandardOutput=append:$LOG_DIR/sys.log
StandardError=append:$LOG_DIR/sys.log

[Install]
WantedBy=multi-user.target
EOL

# 6. Enable and Start Service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable bilal.service
sudo systemctl restart bilal.service

echo "--- Installation Complete ---"
echo "App Directory: $APP_DIR"
echo "Service User:  $REAL_USER"
echo ""
echo "Checking Service Status..."
sudo systemctl status bilal.service --no-pager
`;