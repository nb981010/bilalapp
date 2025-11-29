import os, json
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
PLAY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'play_history.json')


def test_job_func(job_id=None, note=None, **kwargs):
    """A small test job function that is importable as `persistent_jobs:test_job_func`.
    It appends a marker to `logs/play_history.json` so we can audit execution.
    """
    # Try to call the local playback API so the server's dedupe guard is exercised.
    file = kwargs.get('file') or note or 'azan.mp3'
    prayer = kwargs.get('prayer') or note or job_id
        # Call server.play_from_job in-process so the dedupe guard and playback
        # logic are exercised without HTTP loopback.
        try:
            import server
            # Call the in-process playback wrapper; ignore return value but log it
            res = server.play_from_job(file, prayer=prayer, force=False)
            return True
        except Exception:
            # Fallback: record to play history if in-process call fails
            try:
                entry = {"file": "persistent-test-job", "ts": datetime.utcnow().isoformat() + 'Z', "job_id": job_id, "note": note}
                if os.path.exists(PLAY_HISTORY_FILE):
                    with open(PLAY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                        hist = json.load(f)
                else:
                    hist = []
            except Exception:
                hist = []

            hist.append(entry)
            try:
                with open(PLAY_HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(hist, f)
            except Exception:
                pass

    return True
