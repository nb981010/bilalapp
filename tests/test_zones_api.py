import json
import types
import pytest

import server


def setup_db(tmp_path):
    # Use a temporary SQLite file so tests are isolated
    dbfile = str(tmp_path / "test_db.sqlite")
    server.DB_PATH = dbfile
    server.init_db(db_path=dbfile)
    return dbfile


def test_default_enabled_systems_returns_onboard(tmp_path):
    setup_db(tmp_path)
    # Ensure no explicit setting is present
    client = server.app.test_client()
    rv = client.get('/api/zones')
    assert rv.status_code == 200
    data = rv.get_json()
    # default should include onboard zone
    assert any(z.get('system') == 'onboard' for z in data)


def test_onboard_only(tmp_path):
    setup_db(tmp_path)
    # Persist enabled_audio_systems = ["onboard"] in test_settings
    server._write_setting('enabled_audio_systems', json.dumps(['onboard']), test=True)
    client = server.app.test_client()
    rv = client.get('/api/zones')
    assert rv.status_code == 200
    data = rv.get_json()
    # Only onboard (and possibly static placeholders) should be present, ensure onboard exists
    assert any(z.get('system') == 'onboard' for z in data)
    # No sonos entries
    assert not any(z.get('system') == 'sonos' for z in data)


def test_sonos_discovery_mocked(tmp_path):
    setup_db(tmp_path)
    # Mock get_sonos_speakers to return two fake speaker objects
    class FakeSpeaker:
        def __init__(self, uid, player_name, volume=10):
            self.uid = uid
            self.player_name = player_name
            self.volume = volume

    def fake_discover():
        return [FakeSpeaker('uid-1', 'Living Room', 20), FakeSpeaker('uid-2', 'Kitchen', 15)]

    # Patch the function on the server module
    orig = server.get_sonos_speakers
    server.get_sonos_speakers = fake_discover
    try:
        server._write_setting('enabled_audio_systems', json.dumps(['sonos']), test=True)
        client = server.app.test_client()
        rv = client.get('/api/zones')
        assert rv.status_code == 200
        data = rv.get_json()
        # We expect at least the two mocked Sonos zones
        sonos_zones = [z for z in data if z.get('system') == 'sonos']
        assert len(sonos_zones) >= 2
        names = {z.get('name') for z in sonos_zones}
        assert 'Living Room' in names and 'Kitchen' in names
    finally:
        server.get_sonos_speakers = orig


def test_onboard_and_sonos_combination(tmp_path):
    setup_db(tmp_path)
    # Mock discovery again
    class FakeSpeaker:
        def __init__(self, uid, player_name, volume=10):
            self.uid = uid
            self.player_name = player_name
            self.volume = volume

    def fake_discover():
        return [FakeSpeaker('uid-1', 'Living Room', 20)]

    orig = server.get_sonos_speakers
    server.get_sonos_speakers = fake_discover
    try:
        server._write_setting('enabled_audio_systems', json.dumps(['onboard', 'sonos']), test=True)
        client = server.app.test_client()
        rv = client.get('/api/zones')
        assert rv.status_code == 200
        data = rv.get_json()
        assert any(z.get('system') == 'onboard' for z in data)
        assert any(z.get('system') == 'sonos' for z in data)
    finally:
        server.get_sonos_speakers = orig
