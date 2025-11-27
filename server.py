import os
import time
import threading
import logging
import socket
import json
from flask import Flask, send_from_directory, jsonify, request

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'sys.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_GROUPS = {}  # Store group snapshots
PLAYBACK_ACTIVE = False

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
    try:
        import soco
        zones = list(soco.discover(timeout=5) or [])
        return zones
    except ImportError:
        logger.error("SoCo library not found.")
        return []
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
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
    try:
        speakers = get_sonos_speakers()
        data = []
        for s in speakers:
            status = 'idle'
            try:
                info = s.get_current_transport_info()
                if info['current_transport_state'] == 'PLAYING':
                    status = 'playing_music'
            except:
                pass
            
            data.append({
                "id": s.uid,
                "name": s.player_name,
                "isAvailable": True,
                "status": status,
                "volume": s.volume
            })
        return jsonify(data)
    except Exception as e:
        logger.error(f"API Zones Error: {e}")
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
    global PLAYBACK_ACTIVE
    data = request.json
    filename = data.get('file', 'azan.mp3')
    
    logger.info(f"Received Play Request: {filename}")

    try:
        speakers = get_sonos_speakers()
        if not speakers:
            return jsonify({"status": "error", "message": "No speakers"}), 404
        
        # Ideally, we find the coordinator from the Prepare step, 
        # but for robustness we just pick the first one (assuming they are grouped).
        coordinator = speakers[0]
        
        # Construct URL
        local_ip = get_local_ip()
        audio_url = f"http://{local_ip}:5000/audio/{filename}"
        
        logger.info(f"Playing URL: {audio_url} on {coordinator.player_name}")
        
        # Set Volume (Optional: Set standard volume for Azan)
        try:
            coordinator.group.volume = 45
        except:
            pass

        # Play
        coordinator.play_uri(audio_url)
        
        # Start Monitoring Thread
        PLAYBACK_ACTIVE = True
        threading.Thread(target=monitor_playback, args=(coordinator,)).start()

        return jsonify({"status": "success", "message": "Playback Started"})

    except Exception as e:
        logger.error(f"Play Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def monitor_playback(coordinator):
    """
    Monitors playback and restores state after finish.
    """
    global PLAYBACK_ACTIVE
    logger.info("Playback Monitor Started...")
    
    # Wait for it to actually start
    time.sleep(5)
    
    while PLAYBACK_ACTIVE:
        try:
            info = coordinator.get_current_transport_info()
            state = info['current_transport_state']
            if state != 'PLAYING' and state != 'TRANSITIONING':
                logger.info(f"Playback finished (State: {state}). Restoring...")
                PLAYBACK_ACTIVE = False
                
                # Ungroup Logic (Simple Restore)
                for s in coordinator.group.members:
                    if s != coordinator:
                        try:
                            s.unjoin()
                        except:
                            pass
                break
        except Exception as e:
            logger.error(f"Monitor Error: {e}")
            PLAYBACK_ACTIVE = False
            break
        
        time.sleep(3) # Check every 3 seconds

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    app.run(host='0.0.0.0', port=5000)
