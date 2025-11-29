import playback


class MockMember:
    def __init__(self, name):
        self.name = name
        self.unjoined = False

    def unjoin(self):
        self.unjoined = True


class MockCoordinator:
    def __init__(self, members_states):
        # members_states: list of states to return sequentially from get_current_transport_info
        self.player_name = 'Coordinator'
        self.group = type('g', (), {})()
        # first element is coordinator itself; others are members
        self.member_objs = [MockMember('m1'), MockMember('m2')]
        self.group.members = [self] + self.member_objs
        self._states = list(members_states)
        self._calls = 0

    def get_current_transport_info(self):
        # Return a dict with current_transport_state based on call count
        self._calls += 1
        if self._calls <= len(self._states):
            return {'current_transport_state': self._states[self._calls - 1]}
        return {'current_transport_state': 'STOPPED'}


def test_monitor_playback_unjoins(monkeypatch):
    # Avoid sleeping to keep the test fast
    monkeypatch.setattr(playback.time, 'sleep', lambda s: None)

    # Simulate: first call PLAYING, then STOPPED
    coord = MockCoordinator(['PLAYING', 'STOPPED'])

    # Run monitor directly (does not spawn a thread here)
    playback.monitor_playback(coord)

    # After monitor finishes, members should have been unjoined
    assert coord.member_objs[0].unjoined is True
    assert coord.member_objs[1].unjoined is True
