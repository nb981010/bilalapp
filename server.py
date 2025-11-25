import os
import time
import threading
import logging
import socket
import json
import subprocess
from flask import Flask, send_from_directory, jsonify, request

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/sys.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

# Kill any existing process on port 5000
try:
    result = subprocess.run(['fuser', '-k', '5000/tcp'], check=False, capture_output=True)
    if result.returncode == 0:
        logger.info("Killed any existing process on port 5000")
except Exception as e:
    logger.warning(f"Failed to kill process on port 5000: {e}")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_SNAPSHOT = {}  # Store zone snapshots: {uid: {volume, uri, position}}
PLAYBACK_ACTIVE = False
AZAN_LOCK = False  # Prevent music/radio playback during Azan
STATIC_ZONE_NAMES = [
    "Pool",
    "Boy 1",
    "Boy 2",
    "Girls Room",
    "Living Room Sonos",
    "Master Bedroom"
]

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def get_local_ip():
    """Get the Raspberry Pi's local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_sonos_speakers():
    """Discover and return Sonos speakers."""
    logger.info("Starting Sonos speaker discovery")
    try:
        import soco
    except ImportError:
        logger.error("SoCo library not found.")
        return []
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Discovery attempt {attempt+1}/{max_retries}")
            zones = list(soco.discover(timeout=5) or [])
            if zones:
                logger.info(f"Discovered {len(zones)} Sonos speakers: {[z.player_name for z in zones]}")
                return zones
            else:
                logger.warning(f"No Sonos speakers found (attempt {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"Error during Sonos discovery (attempt {attempt+1}): {e}")
    logger.error("Failed to discover any Sonos speakers after all retries")
    return []

# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/api/zones', methods=['GET'])
def list_zones():
    """Return list of available zones and their status."""
    logger.info("API /api/zones requested")
    try:
        speakers = get_sonos_speakers()
        found_names = [s.player_name for s in speakers]
        data = []
        # Add discovered zones that match static names
        for s in speakers:
            if s.player_name in STATIC_ZONE_NAMES:
                status = 'idle'
                try:
                    info = s.get_current_transport_info()
                    if info['current_transport_state'] == 'PLAYING':
                        status = 'playing_music'
                except Exception as e:
                    logger.warning(f"Failed to get transport info for {s.player_name}: {e}")
                data.append({
                    "id": s.uid,
                    "name": s.player_name,
                    "isAvailable": True,
                    "status": status,
                    "volume": s.volume
                })
        # Add static zones not found in discovery as offline
        for name in STATIC_ZONE_NAMES:
            if name not in found_names:
                data.append({
                    "id": name,
                    "name": name,
                    "isAvailable": False,
                    "status": "offline",
                    "volume": 0
                })
        logger.info(f"API /api/zones returning {len(data)} zones")
        return jsonify(data)
    except Exception as e:
        logger.error(f"API /api/zones error: {e}")
        return jsonify([]), 500

@app.route('/api/prepare', methods=['GET'])
def prepare_group():
    """
    Called 1 minute before Azan.
    Groups all available speakers to the Coordinator (first found).
    """
    global SONOS_GROUPS
    logger.info("Preparing Zones for Azan...")
    
    try:
        speakers = get_sonos_speakers()
        if not speakers:
            return jsonify({"status": "error", "message": "No speakers found"}), 404

        # 1. Snapshot current state (volume, URI, position) logic omitted for brevity in V1, 
        #    but we just group them now.
        
        coordinator = speakers[0]
        logger.info(f"Elected Coordinator: {coordinator.player_name}")

        # 2. Join all others to coordinator
        for s in speakers[1:]:
            logger.info(f"Joining {s.player_name} to {coordinator.player_name}")
            try:
                s.join(coordinator)
            except Exception as e:
                logger.warning(f"Failed to join {s.player_name}: {e}")

        return jsonify({"status": "success", "message": "Zones Grouped", "coordinator": coordinator.player_name})

    except Exception as e:
        logger.error(f"Prepare Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/play', methods=['POST'])
def play_audio():
    """
    Plays the Azan audio file on the group.
    """
    global PLAYBACK_ACTIVE, AZAN_LOCK
    if AZAN_LOCK:
        logger.warning("Azan already in progress, blocking duplicate playback.")
        return jsonify({"status": "error", "message": "Azan in progress, playback blocked."}), 429
    data = request.json
    filename = data.get('file', 'fajr.mp3')
    
    logger.info(f"Received Play Request: {filename}")

    try:
        speakers = get_sonos_speakers()
        if not speakers:
            logger.error("No speakers found for Azan playback")
            return jsonify({"status": "error", "message": "No speakers"}), 404

        # Snapshot all zones: volume, uri, position
        global SONOS_SNAPSHOT
        SONOS_SNAPSHOT = {}
        AZAN_LOCK = True
        error_count = 0
        logger.info("Starting snapshot of current Sonos state")
        
        # Find the coordinator
        coordinator = next((s for s in speakers if s.is_coordinator), speakers[0])
        logger.info(f"Coordinator: {coordinator.player_name}")
        
        # Get coordinator's track and transport info
        track_info = coordinator.get_current_track_info()
        transport_info = coordinator.get_current_transport_info()
        logger.info(f"Coordinator track: uri={track_info.get('uri')}, position={track_info.get('position')}, state={transport_info.get('current_transport_state')}")
        
        for s in speakers:
            try:
                SONOS_SNAPSHOT[s.uid] = {
                    "volume": s.volume,
                    "uri": track_info.get("uri"),
                    "position": track_info.get("position"),
                    "state": transport_info.get("current_transport_state")
                }
                logger.info(f"Snapped {s.player_name}: vol={s.volume}, uri={track_info.get('uri')}, position={track_info.get('position')}")
                # Set volume to 50%
                s.volume = 50
                logger.info(f"Set volume to 50% for {s.player_name}")
            except Exception as e:
                logger.warning(f"Snapshot failed for {s.player_name}: {e}")
                error_count += 1
        if error_count == len(speakers):
            logger.error("Failed to snapshot any speakers")
            AZAN_LOCK = False
            return jsonify({"status": "error", "message": "Failed to snapshot all speakers."}), 500

        # Pick coordinator (first speaker)
        coordinator = speakers[0]
        local_ip = get_local_ip()
        audio_url = f"http://{local_ip}:5000/audio/{filename}"
        logger.info(f"Playing URL: {audio_url} on {coordinator.player_name}")

        # Set metadata for display
        title = "Azan by Bilal App"
        meta = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
<item id="0" parentID="0" restricted="0">
<dc:title>{title}</dc:title>
<upnp:class>object.item.audioItem</upnp:class>
<res protocolInfo="http-get:*:audio/mpeg:*">{audio_url}</res>
</item>
</DIDL-Lite>"""

        try:
            coordinator.play_uri(audio_url, meta=meta)
        except Exception as e:
            logger.error(f"Azan playback failed: {e}")
            AZAN_LOCK = False
            return jsonify({"status": "error", "message": "Azan playback failed."}), 500

        # Start Monitoring Thread
        PLAYBACK_ACTIVE = True
        threading.Thread(target=monitor_playback, args=(coordinator, speakers, audio_url)).start()

        return jsonify({"status": "success", "message": "Playback Started"})

    except Exception as e:
        logger.error(f"Play Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def monitor_playback(coordinator, speakers, audio_url):
    """
    Monitors playback for 3 minutes, enforcing Azan priority by overriding interruptions and resuming from interrupted position.
    Restores state after the full duration.
    """
    global PLAYBACK_ACTIVE, SONOS_SNAPSHOT, AZAN_LOCK
    logger.info("Playback Monitor Started...")
    logger.info(f"Monitoring Azan URI: {audio_url}")
    start_time = time.time()
    duration = 180  # 3 minutes
    last_azan_position = None
    while time.time() - start_time < duration:
        try:
            info = coordinator.get_current_transport_info()
            state = info['current_transport_state']
            track_info = coordinator.get_current_track_info()
            current_uri = track_info.get('uri')
            logger.debug(f"Playback state: {state}, URI: {current_uri}")
            if state == 'STOPPED' and current_uri == audio_url:
                logger.info("Azan finished and stopped, starting restore immediately")
                break
            if current_uri == audio_url:
                # Get Azan duration
                duration_str = track_info.get('duration', '0:02:10')
                duration_parts = duration_str.split(':')
                if len(duration_parts) == 3:
                    azan_duration_seconds = int(duration_parts[0])*3600 + int(duration_parts[1])*60 + int(duration_parts[2])
                else:
                    azan_duration_seconds = 130  # default
                # Update last known Azan position
                last_azan_position = track_info.get('position', '0:00:00')
                # Check if Azan is near end
                pos_str = last_azan_position
                pos_parts = pos_str.split(':')
                if len(pos_parts) == 3:
                    pos_seconds = int(pos_parts[0])*3600 + int(pos_parts[1])*60 + int(pos_parts[2])
                    if pos_seconds >= azan_duration_seconds:
                        logger.info(f"Azan position {pos_str} >= {azan_duration_seconds}s, Azan finished")
                        break
            elif current_uri != audio_url:
                logger.info(f"Azan interrupted by another track (URI: {current_uri}). Enforcing Azan priority - resuming Azan from position {last_azan_position}.")
                # Force resume Azan
                coordinator.stop()
                time.sleep(1)
                title = "Azan by Bilal App"
                meta = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
<item id="0" parentID="0" restricted="0">
<dc:title>{title}</dc:title>
<upnp:class>object.item.audioItem</upnp:class>
<res protocolInfo="http-get:*:audio/mpeg:*">{audio_url}</res>
</item>
</DIDL-Lite>"""
                coordinator.play_uri(audio_url, meta=meta)
                coordinator.play()
                # Seek to the last Azan position
                if last_azan_position:
                    time.sleep(1)  # Wait for play to start
                    try:
                        coordinator.seek(last_azan_position)
                        logger.info(f"Seeked to {last_azan_position}")
                    except Exception as e:
                        logger.warning(f"Seek failed: {e}")
                # Re-group if needed
                for s in speakers:
                    if s != coordinator and not s.is_coordinator:
                        try:
                            s.join(coordinator)
                        except Exception as e:
                            logger.warning(f"Re-group failed for {s.player_name}: {e}")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Monitor Error: {e}")
            break
    # After 3 minutes, restore
    logger.info("Azan duration completed. Starting restore process...")
    PLAYBACK_ACTIVE = False
    AZAN_LOCK = False
    # Restore all zones
    for s in speakers:
        snap = SONOS_SNAPSHOT.get(s.uid)
        if snap:
            logger.info(f"Restoring {s.player_name} with snapshot: {snap}")
            try:
                s.volume = snap["volume"]
                logger.info(f"Restored volume to {snap['volume']} for {s.player_name}")
            except Exception as e:
                logger.warning(f"Restore volume failed for {s.player_name}: {e}")
            # Ungroup first
            if s != coordinator:
                try:
                    s.unjoin()
                    logger.info(f"Ungrouped {s.player_name}")
                except Exception as e:
                    logger.warning(f"Ungroup failed for {s.player_name}: {e}")
            # Resume previous music/radio if was playing
            if snap["state"] == "PLAYING" and snap["uri"]:
                if 'sid=' in snap["uri"]:
                    logger.info(f"Skipping resume for streaming URI: {snap['uri']} for {s.player_name}")
                else:
                    logger.info(f"Attempting to resume {snap['uri']} at {snap['position']} for {s.player_name}")
                    try:
                        s.play_uri(snap["uri"])
                        if snap["position"] and snap["position"] != 'NOT_IMPLEMENTED':
                            time.sleep(1)
                            s.seek(snap["position"])
                            logger.info(f"Seeked to {snap['position']} for {s.player_name}")
                        logger.info(f"Resumed playback for {s.player_name}: {snap['uri']} at {snap['position']}")
                    except Exception as e:
                        logger.warning(f"Restore playback failed for {s.player_name}: {e}")
            else:
                logger.info(f"No playback to resume for {s.player_name} (state: {snap['state']}, uri: {snap['uri']})")
        else:
            logger.warning(f"No snapshot found for {s.player_name}")
    logger.info("Azan playback and restore completed")

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    app.run(host='0.0.0.0', port=5000)
