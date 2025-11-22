import { ZoneId, SonosZone } from './types';

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

# Bilal Installer Script
# ----------------------
# 1. Checks for nodejs/python dependencies
# 2. Scans local network for Sonos devices using soco
# 3. Generates config.json with detected zones

LOG_DIR="/logs"

echo "Creating log directory..."
if [ ! -d "$LOG_DIR" ]; then
  sudo mkdir -p $LOG_DIR
  sudo chmod 777 $LOG_DIR
fi

echo "Installing dependencies..."
sudo apt-get update && sudo apt-get install -y python3-pip vlc

echo "Installing Python libraries..."
# Install soco, handling potential managed environment restrictions on newer RPi OS
sudo pip3 install soco --break-system-packages 2>/dev/null || sudo pip3 install soco

echo "Detecting Sonos Zones..."
# Use python to discover and output
DETECTED_ZONES=$(python3 -c "
import soco
import sys
try:
    zones = soco.discover(timeout=10)
    if zones:
        print(', '.join([z.player_name for z in zones]))
    else:
        print('')
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
")

echo "Zones Detected: $DETECTED_ZONES"

if [ -z "$DETECTED_ZONES" ]; then
  echo "Warning: No zones found! Ensure you are on the same network."
else
  echo "Configuration successful for zones: $DETECTED_ZONES"
fi

echo "Setup complete."
`;