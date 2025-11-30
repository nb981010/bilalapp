#!/usr/bin/env python3
"""local/soco_service.py

Small Flask microservice providing local SoCo controls for fallback use by Node backend.
Endpoints:
 - GET /local/health
 - GET /local/discover
 - POST /local/play {url}
 - POST /local/stop
 - POST /local/volume {level}
 - POST /local/group {group: [player_names_or_uids]}

"""
from flask import Flask, request, jsonify
import soco
import socket
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('soco_service')


def discover_zones():
    try:
        zones = list(soco.discover(timeout=5) or [])
        return zones
    except Exception as e:
        logger.warning(f"soco discover failed: {e}")
        return []


@app.route('/local/health')
def health():
    zones = discover_zones()
    return jsonify({'status': 'ok' if zones else 'unavailable', 'count': len(zones)})


@app.route('/local/discover')
def local_discover():
    zones = discover_zones()
    result = [{'uid': z.uid, 'name': z.player_name, 'is_coordinator': getattr(z, 'is_coordinator', False)} for z in zones]
    return jsonify(result)


@app.route('/local/play', methods=['POST'])
def local_play():
    data = request.get_json() or {}
    url = data.get('url')
    if not url:
        return jsonify({'error': 'missing url'}), 400
    zones = discover_zones()
    if not zones:
        return jsonify({'error': 'no speakers found'}), 404
    coordinator = next((z for z in zones if getattr(z, 'is_coordinator', False)), zones[0])
    try:
        coordinator.play_uri(url)
        return jsonify({'status': 'ok', 'coordinator': coordinator.player_name})
    except Exception as e:
        logger.exception('local play failed')
        return jsonify({'error': str(e)}), 500


@app.route('/local/stop', methods=['POST'])
def local_stop():
    zones = discover_zones()
    if not zones:
        return jsonify({'error': 'no speakers found'}), 404
    coordinator = next((z for z in zones if getattr(z, 'is_coordinator', False)), zones[0])
    try:
        coordinator.stop()
        return jsonify({'status': 'ok', 'coordinator': coordinator.player_name})
    except Exception as e:
        logger.exception('local stop failed')
        return jsonify({'error': str(e)}), 500


@app.route('/local/volume', methods=['POST'])
def local_volume():
    data = request.get_json() or {}
    level = data.get('level')
    if level is None:
        return jsonify({'error': 'missing level'}), 400
    try:
        level = int(level)
    except Exception:
        return jsonify({'error': 'invalid level'}), 400
    zones = discover_zones()
    if not zones:
        return jsonify({'error': 'no speakers found'}), 404
    errors = []
    for z in zones:
        try:
            z.volume = level
        except Exception as e:
            logger.warning(f"Failed to set volume on {z.player_name}: {e}")
            errors.append(str(e))
    return jsonify({'status': 'ok', 'set_to': level, 'errors': errors})


@app.route('/local/group', methods=['POST'])
def local_group():
    data = request.get_json() or {}
    group = data.get('group') or []
    zones = discover_zones()
    if not zones:
        return jsonify({'error': 'no speakers found'}), 404
    # Map names/uids to Sonos objects
    target = []
    for item in group:
        for z in zones:
            if item == z.player_name or item == z.uid:
                target.append(z)
                break
    if not target:
        return jsonify({'error': 'no matching speakers for group'}), 400
    coordinator = target[0]
    errors = []
    for s in target[1:]:
        try:
            s.join(coordinator)
        except Exception as e:
            logger.warning(f"Failed to join {s.player_name}: {e}")
            errors.append(str(e))
    return jsonify({'status': 'ok', 'coordinator': coordinator.player_name, 'errors': errors})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
