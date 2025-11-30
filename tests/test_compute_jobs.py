import importlib.util
from datetime import date
from pathlib import Path


def _load_server_module():
    # Load server.py directly by path to avoid import issues in test runner
    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('server', str(repo_root / 'server.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_prayer_jobs_basic():
    server = _load_server_module()
    # Provide a minimal settings dict and a known date
    settings = {'prayer_lat': '25.2048', 'prayer_lon': '55.2708'}
    tgt = date.today()
    jobs = server.compute_prayer_jobs_for_date(settings, tgt)
    assert isinstance(jobs, list)
    # Expect at least one job entry with required keys
    assert all(isinstance(j, dict) for j in jobs)
    if len(jobs) > 0:
        j = jobs[0]
        for key in ('id', 'prayer', 'scheduled_local', 'scheduled_utc', 'playback_file'):
            assert key in j
