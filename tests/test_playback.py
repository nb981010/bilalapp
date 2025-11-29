import playback

class MockSpeaker:
    def __init__(self, name):
        self.player_name = name
        self.uid = f"uid-{name}"
        self.joined_to = None
        self.group = type('g', (), {'members': []})()
    def join(self, coordinator):
        self.joined_to = coordinator.player_name
        # simulate being in the coordinator group
        try:
            coordinator.group.members.append(self)
        except Exception:
            pass
    def unjoin(self):
        self.joined_to = None


def test_build_audio_url(monkeypatch):
    monkeypatch.setattr(playback, 'get_local_ip', lambda: '192.0.2.1')
    url = playback.build_audio_url('azan.mp3', port=5000)
    assert url == 'http://192.0.2.1:5000/audio/azan.mp3'


def test_group_zones_joins_members():
    c = MockSpeaker('Coordinator')
    s1 = MockSpeaker('LivingRoom')
    s2 = MockSpeaker('Kitchen')
    speakers = [c, s1, s2]
    name = playback.group_zones(speakers)
    assert name == 'Coordinator'
    assert s1.joined_to == 'Coordinator'
    assert s2.joined_to == 'Coordinator'


def test_play_uri_calls_play():
    class Coord:
        def __init__(self):
            self.player_name = 'Test'
            self.played = None
        def play_uri(self, uri):
            self.played = uri
    coord = Coord()
    uri = 'http://example.local/audio/test.mp3'
    playback.play_uri(coord, uri)
    assert coord.played == uri
