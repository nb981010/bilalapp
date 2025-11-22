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
# 2. Scans local network for Sonos devices using soco-cli or node-sonos-http-api
# 3. Generates config.json with detected zones

LOG_DIR="/logs"
mkdir -p $LOG_DIR

echo "Installing dependencies..."
sudo apt-get update && sudo apt-get install -y python3-pip vlc

echo "Detecting Sonos Zones..."
# Hypothetical detection logic
DETECTED_ZONES=$(python3 -c "import soco; print([z.player_name for z in soco.discover()])")

echo "Zones Detected: $DETECTED_ZONES"

if [ -z "$DETECTED_ZONES" ]; then
  echo "No zones found! Ensure you are on the same network."
  exit 1
fi

echo "Setup complete. Service starting..."
# Setup cron or systemd service here
`;