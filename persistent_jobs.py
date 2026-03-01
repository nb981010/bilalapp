import os, json
from datetime import datetime
import sys
sys.path.insert(0, os.path.dirname(__file__))
import db as _db

LEGACY_PLAY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'play_history.json')


def test_job_func(job_id=None, note=None, **kwargs):
    """A small test job function that is importable as `persistent_jobs:test_job_func`.
    Calls server.play_from_job in-process; records execution to SQLite via db.py.
    """
    file = kwargs.get('file') or note or 'azan.mp3'
    prayer = kwargs.get('prayer') or note or job_id
    try:
        import server
        res = server.play_from_job(file, prayer=prayer, force=False)
        # play_from_job already calls _db.record_play internally; nothing more to do.
        return True
    except Exception:
        # Fallback: record a bare entry so the job run is not completely invisible.
        try:
            _db.init_db()
            _db.record_play(
                prayer=str(prayer),
                file=str(file),
                status='error',
                job_id=str(job_id),
                message='persistent_jobs fallback: server.play_from_job unavailable',
            )
        except Exception:
            pass
    return True
