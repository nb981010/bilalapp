#!/usr/bin/env python3
"""
Lightweight Flask microservice wrapping SoCo for local Sonos control.
Exposes endpoints:
 - GET /local/health
 - GET /local/discover
 - POST /local/play  { device_name, url }
 - POST /local/stop  { device_name }
 - POST /local/setVolume { device_name, level }
 - POST /local/group { coordinator_name, members: [names] }

Run this alongside the main app; the Node cloud microservice will call it when cloud unavailable.
"""

from flask import Flask, request, jsonify
import soco
import socket
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('soco_server')


def discover_speakers(timeout=5):
    try:
        zones = list(soco.discover(timeout=timeout) or [])
        return zones
    except Exception as e:
        logger.error(f"soco discover failed: {e}")
        return []


@app.route('/local/health', methods=['GET'])
def health():
    # Very simple: try discover for 1s
    speakers = discover_speakers(timeout=1)
    return jsonify({'available': bool(speakers), 'count': len(speakers)})


@app.route('/local/discover', methods=['GET'])
def discover():
    speakers = discover_speakers()
    data = []
    for s in speakers:
        data.append({'uid': s.uid, 'name': s.player_name, 'is_coordinator': getattr(s, 'is_coordinator', False), 'volume': s.volume})
    return jsonify(data)


def find_by_name(name):
    speakers = discover_speakers()
    for s in speakers:
        if s.player_name == name:
            return s
    return None


@app.route('/local/play', methods=['POST'])
def play():
    data = request.get_json() or {}
    name = data.get('device_name')
    url = data.get('url')
    if not name or not url:
        return jsonify({'error': 'missing device_name or url'}), 400
    s = find_by_name(name)
    if not s:
        return jsonify({'error': 'device not found'}), 404
    try:
        s.play_uri(url)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/local/stop', methods=['POST'])
def stop():
    data = request.get_json() or {}
    name = data.get('device_name')
    if not name:
        return jsonify({'error': 'missing device_name'}), 400
    s = find_by_name(name)
    if not s:
        return jsonify({'error': 'device not found'}), 404
    try:
        s.stop()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/local/setVolume', methods=['POST'])
def set_volume():
    data = request.get_json() or {}
    name = data.get('device_name')
    level = data.get('level')
    if not name or level is None:
        return jsonify({'error': 'missing device_name or level'}), 400
    s = find_by_name(name)
    if not s:
        return jsonify({'error': 'device not found'}), 404
    try:
        s.volume = int(level)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/local/group', methods=['POST'])
def group():
    data = request.get_json() or {}
    coordinator_name = data.get('coordinator_name')
    members = data.get('members') or []
    if not coordinator_name or not members:
        return jsonify({'error': 'missing coordinator_name or members'}), 400
    coordinator = find_by_name(coordinator_name)
    if not coordinator:
        return jsonify({'error': 'coordinator not found'}), 404
    try:
        # Join each member to coordinator
        speakers = discover_speakers()
        member_objs = [s for s in speakers if s.player_name in members]
        for m in member_objs:
            try:
                m.join(coordinator)
            except Exception as e:
                logger.warning(f"Failed to join {m.player_name}: {e}")
        return jsonify({'ok': True, 'joined': [m.player_name for m in member_objs]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001)
