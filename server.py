import os
import time
import threading
import logging
from playback import get_local_ip, get_sonos_speakers, choose_coordinator, build_audio_url, set_group_volume, play_uri, start_monitor
import json
from datetime import datetime, timezone, timedelta
from flask import Flask, send_from_directory, jsonify, request

# Scheduler imports (lazy import in case deps not installed)
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    APSCHEDULER_AVAILABLE = True
except Exception:
    APSCHEDULER_AVAILABLE = False

# Configure Logging
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, 'sys.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_GROUPS = {}  # Store group snapshots
SCHEDULER = None
JOBSTORE_PATH = os.path.join(os.path.dirname(__file__), 'jobs.sqlite')

# played history marker (file-backed)
PLAY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'play_history.json')
# persisted played markers to prevent duplicate plays within a day
PLAYED_MARKERS_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'played_markers.json')

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------



def _load_played_markers():
    try:
        if os.path.exists(PLAYED_MARKERS_FILE):
            with open(PLAYED_MARKERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_played_markers(markers):
    try:
        with open(PLAYED_MARKERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(markers, f)
    except Exception as e:
        logger.warning(f"Could not save played markers: {e}")


def has_played_today(prayer: str) -> bool:
    """Return True if `prayer` has been recorded as played for today's date."""
    if not prayer:
        return False
    today = datetime.utcnow().date().isoformat()
    markers = _load_played_markers()
    for m in markers:
        if m.get('date') == today and m.get('prayer') == prayer:
            return True
    return False


def mark_played(prayer: str, details: dict = None):
    """Record that `prayer` was played today. `details` may include extra metadata."""
    if not prayer:
        return
    today = datetime.utcnow().date().isoformat()
    markers = _load_played_markers()
    entry = {'date': today, 'prayer': prayer, 'ts': datetime.utcnow().isoformat() + 'Z'}
    if details and isinstance(details, dict):
        entry.update(details)
    markers.append(entry)
    # Keep markers trimmed to last 30 days to avoid unbounded growth
    try:
        # filter out older than 30 days
        cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
        markers = [m for m in markers if m.get('date', '') >= cutoff]
    except Exception:
        pass
    _save_played_markers(markers)

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


@app.route('/api/scheduler/jobs', methods=['GET'])
def api_scheduler_jobs():
    """Return scheduled jobs (id + next_run_time)."""
    try:
        if not SCHEDULER:
            return jsonify({"jobs": []})

        jobs = []
        for job in SCHEDULER.get_jobs():
            nrt = job.next_run_time
            nrt_str = None
            if nrt:
                # Return in ISO-like format without timezone info to match existing UI handling
                nrt_str = nrt.strftime('%Y-%m-%d %H:%M:%S')
            jobs.append({
                'id': job.id,
                'next_run_time': nrt_str,
                'trigger': str(job.trigger)
            })

        return jsonify({"jobs": jobs})
    except Exception as e:
        logger.error(f"/api/scheduler/jobs error: {e}")
        return jsonify({"jobs": []}), 500


@app.route('/api/scheduler/force-schedule', methods=['POST'])
def api_scheduler_force_schedule():
    """Force a scheduling pass. This will not delete existing persisted jobs.
    Optional JSON body can include a `date` or `jobs` payload for testing."""
    try:
        payload = request.get_json(silent=True) or {}
        logger.info(f"Force-schedule requested: {payload}")

        # Accept explicit jobs array for testing/force scheduling. Each job entry
        # should be: {"id": "azan-YYYY-MM-DD-<prayer>", "run_date": "ISO", "prayer": "maghrib", "file": "azan.mp3"}
        jobs = payload.get('jobs') or []
        created = []
        errors = []
        for j in jobs:
            try:
                jid = j.get('id')
                rd = j.get('run_date')
                prayer = j.get('prayer')
                file = j.get('file', 'azan.mp3')

                if not jid or not rd:
                    errors.append({"job": j, "error": "id and run_date required"})
                    continue

                # parse run_date
                try:
                    run_date = datetime.fromisoformat(rd.replace('Z', '+00:00'))
                except Exception:
                    errors.append({"job": j, "error": "invalid run_date"})
                    continue

                # Idempotent add: only add if missing
                if not SCHEDULER:
                    errors.append({"job": j, "error": "scheduler not available"})
                    continue

                if SCHEDULER.get_job(jid):
                    logger.info(f"Job {jid} already exists; skipping")
                    continue

                # Use persistent callable which will call the playback endpoint
                SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file, 'prayer': prayer})
                created.append(jid)
                logger.info(f"Force-scheduled job {jid} -> {run_date}")
            except Exception as e:
                logger.error(f"Error scheduling job {j}: {e}")
                errors.append({"job": j, "error": str(e)})

        return jsonify({"status": "ok", "created": created, "errors": errors})
    except Exception as e:
        logger.error(f"force-schedule error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/scheduler/simulate-play', methods=['POST'])
def api_scheduler_simulate_play():
    """Append a simulated play_history entry for testing scheduling logic.
    Expected JSON: {"file":"azan.mp3","ts":"2025-11-27T18:31:00+04:00"}
    """
    try:
        payload = request.get_json(force=True)
        if not payload or 'file' not in payload or 'ts' not in payload:
            return jsonify({"status": "error", "message": "file and ts required"}), 400

        # Append to play_history.json
        try:
            if os.path.exists(PLAY_HISTORY_FILE):
                with open(PLAY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    hist = json.load(f)
            else:
                hist = []
        except Exception:
            hist = []

        hist.append({"file": payload['file'], "ts": payload['ts']})
        with open(PLAY_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(hist, f)

        logger.info(f"Simulated play appended: {payload}")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"simulate-play error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/scheduler/create_test_job', methods=['POST'])
def api_scheduler_create_test_job():
    """Create a persistent test job in the scheduler.

    JSON body (optional): {
        "id": "test-job-2025-11-29",
        "run_date": "2025-11-29T12:34:00Z",
        "note": "optional note"
    }
    The scheduled callable is `server.test_job_func` so the jobstore can persist
    it by module path.
    """
    try:
        if not SCHEDULER:
            return jsonify({"status": "error", "message": "Scheduler not available"}), 500

        payload = request.get_json(silent=True) or {}
        job_id = payload.get('id')
        note = payload.get('note')

        if not job_id:
            # create a deterministic id for today
            today = datetime.utcnow().strftime('%Y%m%d')
            job_id = f"test-job-{today}"

        # parse run_date if provided, otherwise schedule 5 minutes from now
        rd = payload.get('run_date')
        if rd:
            try:
                # support basic ISO formats
                run_date = datetime.fromisoformat(rd.replace('Z', '+00:00'))
            except Exception:
                return jsonify({"status": "error", "message": "invalid run_date format"}), 400
        else:
            run_date = datetime.utcnow() + timedelta(minutes=5)

        # If job exists, return existing job info
        existing = SCHEDULER.get_job(job_id)
        if existing:
            return jsonify({"status": "exists", "id": job_id, "next_run_time": existing.next_run_time.isoformat() if existing.next_run_time else None})

        # Add job using module:function string so SQLAlchemyJobStore can persist
        # Use `persistent_jobs:test_job_func` which is an importable module in the repo
        SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=job_id, kwargs={'job_id': job_id, 'note': note})

        logger.info(f"Created test job {job_id} run_date={run_date}")
        return jsonify({"status": "created", "id": job_id, "next_run_time": run_date.isoformat()})

    except Exception as e:
        logger.error(f"create_test_job error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/scheduler/played', methods=['GET'])
def api_scheduler_played():
    """Return played markers for today (and optional query `days` to include prior days).
    Example: `/api/scheduler/played?days=3` returns last 3 days of markers.
    """
    try:
        days_q = request.args.get('days', '1')
        try:
            days = int(days_q)
        except Exception:
            days = 1

        markers = _load_played_markers()
        if days <= 1:
            today = datetime.utcnow().date().isoformat()
            todays = [m for m in markers if m.get('date') == today]
            return jsonify({"markers": todays})

        # include last `days` days
        cutoff = (datetime.utcnow() - timedelta(days=days-1)).date().isoformat()
        results = [m for m in markers if m.get('date', '') >= cutoff]
        return jsonify({"markers": results})
    except Exception as e:
        logger.error(f"played endpoint error: {e}")
        return jsonify({"markers": []}), 500

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

        coordinator_name = None
        try:
            # prefer playback helper
            from playback import group_zones
            coordinator_name = group_zones(speakers)
        except Exception:
            # fallback: call local grouping logic
            coordinator = speakers[0]
            for s in speakers[1:]:
                try:
                    s.join(coordinator)
                except Exception:
                    pass
            coordinator_name = getattr(speakers[0], 'player_name', None)

        return jsonify({"status": "success", "message": "Zones Grouped", "coordinator": coordinator_name})

    except Exception as e:
        logger.error(f"Prepare Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/play', methods=['POST'])
def play_audio():
    """
    Plays the Azan audio file on the group.
    """
    data = request.json
    filename = data.get('file', 'azan.mp3')
    prayer = data.get('prayer')
    force = bool(data.get('force'))

    logger.info(f"Received Play Request (route): {filename} prayer={prayer} force={force}")

    # Delegate to internal playback function so scheduled jobs can call same logic
    result = play_from_job(filename, prayer=prayer, force=force)
    if result.get('status') == 'success':
        return jsonify({"status": "success", "message": "Playback Started"})
    elif result.get('status') == 'skipped':
        return jsonify({"status": "skipped", "message": result.get('message', 'skipped')}), 409
    else:
        return jsonify({"status": "error", "message": result.get('message', 'error')}), 500


def play_from_job(filename: str, prayer: str = None, force: bool = False) -> dict:
    """Internal in-process playback function used by scheduled jobs and `/api/play`.

    Returns a dict with `status` and optional `message`. This mirrors the behavior
    of the `/api/play` route but runs in-process (no HTTP).
    """
    global PLAYBACK_ACTIVE
    try:
        logger.info(f"play_from_job invoked: file={filename} prayer={prayer} force={force}")

        if prayer and not force and has_played_today(prayer):
            logger.info(f"Skipping play_from_job for {prayer}: already played today")
            return {"status": "skipped", "message": "prayer already played today"}

        speakers = get_sonos_speakers()
        if not speakers:
            return {"status": "error", "message": "No speakers"}

        coordinator = choose_coordinator(speakers)
        if not coordinator:
            return {"status": "error", "message": "No coordinator"}

        # Construct URL using playback helper
        audio_url = build_audio_url(filename)
        logger.info(f"Playing URL (in-process): {audio_url} on {coordinator.player_name}")

        # Set Volume (Optional)
        set_group_volume(coordinator, 45)

        # Play via helper
        play_uri(coordinator, audio_url)

        # mark played for dedupe tracking if `prayer` provided
        try:
            if prayer:
                mark_played(prayer, {"file": filename})
        except Exception as e:
            logger.warning(f"Failed to mark played: {e}")

        start_monitor(coordinator)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"play_from_job error: {e}")
        return {"status": "error", "message": str(e)}


    # ------------------------------------------------------------------
    # Test job function (module-level so SQLAlchemyJobStore can persist by reference)
    # ------------------------------------------------------------------
    def test_job_func(job_id=None, note=None):
        """A simple importable function that can be scheduled and persisted.
        It logs invocation and appends a record to the play history for visibility.
        """
        logger.info(f"Test job executed: {job_id} note={note}")
        # Append a small marker to play_history for audit (non-critical)
        try:
            entry = {"file": "test-job", "ts": datetime.utcnow().isoformat() + 'Z', "job_id": job_id, "note": note}
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
        except Exception as e:
            logger.warning(f"Could not write play history from test job: {e}")


if __name__ == '__main__':
    # Initialize scheduler with persistent SQLAlchemy jobstore (if available)
    if APSCHEDULER_AVAILABLE:
        try:
            jobstores = {
                'default': SQLAlchemyJobStore(url=f'sqlite:///{JOBSTORE_PATH}')
            }
            SCHEDULER = BackgroundScheduler(jobstores=jobstores, timezone='UTC')
            SCHEDULER.start()
            logger.info(f"APScheduler started with jobstore: sqlite:///{JOBSTORE_PATH}")
        except Exception as e:
            logger.error(f"Failed to start APScheduler with SQLAlchemyJobStore: {e}")
            SCHEDULER = None
    else:
        logger.warning("APScheduler or SQLAlchemy not available; running without persistent scheduler.")

    logger.info("Server Starting on Port 5000...")
    app.run(host='0.0.0.0', port=5000)
