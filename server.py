import os
import time
import threading
import logging
import socket
from datetime import datetime, timedelta

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    import tzlocal
except Exception:
    # APScheduler or tzlocal may not be installed in some environments — scheduler will be disabled.
    BackgroundScheduler = None
    SQLAlchemyJobStore = None
    tzlocal = None
import json
import subprocess
from flask import Flask, send_from_directory, jsonify, request

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/sys.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_GROUPS = {}  # Store group snapshots
PLAYBACK_ACTIVE = False

# played history marker (file-backed)
PLAY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'play_history.json')
# persisted played markers to prevent duplicate plays within a day
PLAYED_MARKERS_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'played_markers.json')

# Scheduler (initialized later if available)
SCHEDULER = None
JOBSTORE_DB = os.path.join(os.path.dirname(__file__), 'apscheduler_jobs.sqlite')

def init_scheduler():
    global SCHEDULER
    if BackgroundScheduler is None or SQLAlchemyJobStore is None:
        logger.warning('APScheduler or jobstore not available; scheduler disabled')
        return

    if SCHEDULER is not None:
        return

    try:
        tz = None
        try:
            tz = tzlocal.get_localzone()
        except Exception:
            tz = 'UTC'

        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{JOBSTORE_DB}')
        }
        SCHEDULER = BackgroundScheduler(jobstores=jobstores, timezone=tz)
        SCHEDULER.start(paused=False)
        logger.info(f'APScheduler started with jobstore: {JOBSTORE_DB}')
        # Ensure daily reschedule job exists
        try:
            # Always ensure the cron exists and is set to 00:15. If an older job
            # exists (e.g., persisted with minute=5), remove and recreate it.
            existing = SCHEDULER.get_job('azan_job_daily_reschedule')
            if existing:
                try:
                    SCHEDULER.remove_job('azan_job_daily_reschedule')
                    logger.info('Removed existing daily reschedule job to update schedule')
                except Exception:
                    logger.exception('Failed to remove existing azan_job_daily_reschedule')
            # run daily at 00:15 local time to recompute next day's jobs
            SCHEDULER.add_job(schedule_daily_reschedule, 'cron', hour=0, minute=15, id='azan_job_daily_reschedule', name='schedule_daily_reschedule')
            logger.info('Added daily reschedule job azan_job_daily_reschedule')
        except Exception:
            logger.exception('Failed to ensure daily reschedule job')
    except Exception as e:
        logger.exception('Failed to start APScheduler: %s', e)


def _parse_time_to_dt(date_obj, time_str, tz):
    """Convert a date and 'HH:MM' string into a timezone-aware datetime."""
    from datetime import datetime as _dt, time as _time
    try:
        hh, mm = [int(x) for x in time_str.split(':')]
        return tz.localize(_dt(date_obj.year, date_obj.month, date_obj.day, hh, mm, 0))
    except Exception:
        # fallback
        return None


def schedule_daily_reschedule():
    """Compute prayer times for today and schedule prepare/play jobs for remaining prayers.

    This function is idempotent: it removes any existing one-off jobs for the same day before adding.
    """
    logger.info('Running daily reschedule...')
    try:
        if BackgroundScheduler is None or SCHEDULER is None:
            logger.warning('Scheduler not initialized; skipping reschedule')
            return

        # Prefer Node "adhan" calculation if available (more configurable), fallback to praytimes
        lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
        lon = float(os.environ.get('PRAYER_LON', '55.2708'))

        today = datetime.now().date()
        times = None
        # Use Node "adhan" calculation (preferred). If this fails, abort reschedule
        try:
            cmd = ['node', os.path.join(os.path.dirname(__file__), 'scripts', 'compute_prayer_times.mjs'), today.isoformat(), str(lat), str(lon), os.environ.get('PRAYER_METHOD', 'Dubai')]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=10)
            parsed = json.loads(out)
            times = parsed
            # parsed contains hh:mm strings for fajr,dhuhr,asr,maghrib,isha
            local_tz = __import__('tzlocal').get_localzone()
            now = datetime.now(local_tz)
        except Exception as e:
            logger.exception('Node adhan compute failed; aborting reschedule: %s', e)
            return

        # prayer keys in praytimes: fajr, sunrise, dhuhr, asr, maghrib, isha
        prayer_order = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

        # Remove any existing today jobs to avoid duplicates
        for j in list(SCHEDULER.get_jobs()):
            if j.id and j.id.startswith(f'azan_job_{today.isoformat()}'):
                try:
                    SCHEDULER.remove_job(j.id)
                    logger.info(f'Removed existing job {j.id}')
                except Exception:
                    pass

        from datetime import timedelta
        for p in prayer_order:
            t_str = times.get(p)
            if not t_str:
                continue
            # compute prepare time 1 minute before
            hhmm = t_str
            hh, mm = [int(x) for x in hhmm.split(':')[:2]]
            # support both pytz (has localize) and zoneinfo (no localize)
            if hasattr(local_tz, 'localize'):
                run_dt = local_tz.localize(datetime(today.year, today.month, today.day, hh, mm, 0))
            else:
                run_dt = datetime(today.year, today.month, today.day, hh, mm, 0, tzinfo=local_tz)
            now_dt = now
            if run_dt <= now_dt:
                # skip past prayers
                continue

            prepare_dt = run_dt - timedelta(minutes=1)
            prepare_id = f'azan_job_{today.isoformat()}_{p}_prepare'
            play_id = f'azan_job_{today.isoformat()}_{p}_play'

            try:
                SCHEDULER.add_job(_run_prepare_job, 'date', run_date=prepare_dt, id=prepare_id, name='_run_prepare_job', args=[p])
                SCHEDULER.add_job(_run_play_job, 'date', run_date=run_dt, id=play_id, name='_run_play_job', args=[p, 'azan.mp3'])
                logger.info(f'Scheduled {p}: prepare at {prepare_dt.isoformat()}, play at {run_dt.isoformat()}')
            except Exception as e:
                logger.exception('Failed to schedule %s: %s', p, e)

        # ensure daily reschedule cron is present (in case jobstore was replaced)
        try:
            # Ensure cron exists and update if necessary
            existing = SCHEDULER.get_job('azan_job_daily_reschedule')
            if not existing:
                SCHEDULER.add_job(schedule_daily_reschedule, 'cron', hour=0, minute=15, id='azan_job_daily_reschedule', name='schedule_daily_reschedule')
            else:
                # If the job exists but we want to enforce minute=15, replace it.
                try:
                    SCHEDULER.remove_job('azan_job_daily_reschedule')
                    SCHEDULER.add_job(schedule_daily_reschedule, 'cron', hour=0, minute=15, id='azan_job_daily_reschedule', name='schedule_daily_reschedule')
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        logger.exception('schedule_daily_reschedule failed: %s', e)


# -------------------- played-markers helpers --------------------
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
        cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
        markers = [m for m in markers if m.get('date', '') >= cutoff]
    except Exception:
        pass
    _save_played_markers(markers)


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

        # Play via helper so scheduler can call the same code
        start_playback(audio_url, coordinator)

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


@app.route('/api/scheduler/jobs', methods=['GET'])
def api_scheduler_jobs():
    """Return scheduled jobs (id + next_run_time).

    Returns an object with `jobs` array to match front-end expectations.
    """
    if SCHEDULER is None:
        # Try to initialize if possible
        init_scheduler()
    try:
        if SCHEDULER is None:
            return jsonify({"jobs": []})

        jobs = []
        for job in SCHEDULER.get_jobs():
            nrt = job.next_run_time
            nrt_str = None
            if nrt:
                try:
                    # Return in ISO-like format without timezone info to match existing UI handling
                    nrt_str = nrt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    nrt_str = str(nrt)

            jobs.append({
                'id': job.id,
                'next_run_time': nrt_str,
                'trigger': str(job.trigger)
            })

        return jsonify({"jobs": jobs})
    except Exception as e:
        logger.exception('api_scheduler_jobs error: %s', e)
        return jsonify({"jobs": []}), 500


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
        logger.exception(f"simulate-play error: {e}")
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
    if SCHEDULER is None:
        init_scheduler()
    try:
        if not SCHEDULER:
            return jsonify({"status": "error", "message": "Scheduler not available"}), 500

        payload = request.get_json(silent=True) or {}
        job_id = payload.get('id')
        note = payload.get('note')

        if not job_id:
            today = datetime.utcnow().strftime('%Y%m%d')
            job_id = f"test-job-{today}"

        rd = payload.get('run_date')
        if rd:
            try:
                run_date = datetime.fromisoformat(rd.replace('Z', '+00:00'))
            except Exception:
                return jsonify({"status": "error", "message": "invalid run_date format"}), 400
        else:
            run_date = datetime.utcnow() + timedelta(minutes=5)

        existing = SCHEDULER.get_job(job_id)
        if existing:
            return jsonify({"status": "exists", "id": job_id, "next_run_time": existing.next_run_time.isoformat() if existing.next_run_time else None})

        # Add job using module:function string so SQLAlchemyJobStore can persist
        try:
            SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=job_id, kwargs={'job_id': job_id, 'note': note})
        except Exception:
            # fallback to server path
            SCHEDULER.add_job('server:test_job_func', trigger='date', run_date=run_date, id=job_id, kwargs={'job_id': job_id, 'note': note})

        logger.info(f"Created test job {job_id} run_date={run_date}")
        return jsonify({"status": "created", "id": job_id, "next_run_time": run_date.isoformat()})

    except Exception as e:
        logger.exception(f"create_test_job error: {e}")
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

        cutoff = (datetime.utcnow() - timedelta(days=days-1)).date().isoformat()
        results = [m for m in markers if m.get('date', '') >= cutoff]
        return jsonify({"markers": results})
    except Exception as e:
        logger.exception(f"played endpoint error: {e}")
        return jsonify({"markers": []}), 500


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

        coordinator = speakers[0]
        # Construct URL using local helper
        audio_url = f"http://{get_local_ip()}:5000/audio/{filename}"
        logger.info(f"Playing URL (in-process): {audio_url} on {coordinator.player_name}")

        try:
            coordinator.group.volume = 45
        except Exception:
            pass

        start_playback(audio_url, coordinator)

        try:
            if prayer:
                mark_played(prayer, {"file": filename})
        except Exception as e:
            logger.warning(f"Failed to mark played: {e}")

        return {"status": "success"}

    except Exception as e:
        logger.exception(f"play_from_job error: {e}")
        return {"status": "error", "message": str(e)}



@app.route('/api/scheduler', methods=['GET'])
def api_scheduler_info():
    if SCHEDULER is None:
        init_scheduler()
    return jsonify({'status': 'running' if SCHEDULER is not None and SCHEDULER.running else 'stopped'})


@app.route('/api/scheduler/reschedule', methods=['POST', 'GET'])
def api_scheduler_reschedule():
    """Trigger immediate reschedule (compute today's prayer times and schedule jobs)."""
    if SCHEDULER is None:
        init_scheduler()
    try:
        schedule_daily_reschedule()
        return jsonify({'status': 'ok', 'message': 'reschedule triggered'})
    except Exception as e:
        logger.exception('api_scheduler_reschedule error: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/scheduler/force_schedule', methods=['POST'])
def api_scheduler_force_schedule():
    """Force schedule prepare/play jobs for a specific date (default: today).

    This will add date-trigger jobs even if the scheduled times are in the past.
    Request JSON: { "date": "YYYY-MM-DD" }
    """
    if SCHEDULER is None:
        init_scheduler()
    try:
        payload = request.get_json() or {}
        date_str = payload.get('date') or datetime.now().date().isoformat()

        lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
        lon = float(os.environ.get('PRAYER_LON', '55.2708'))

        # Call Node adhan script
        cmd = ['node', os.path.join(os.path.dirname(__file__), 'scripts', 'compute_prayer_times.mjs'), date_str, str(lat), str(lon), os.environ.get('PRAYER_METHOD', 'Dubai')]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=10)
        parsed = json.loads(out)
        times = parsed

        prayer_order = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
        scheduled = []
        from datetime import timedelta
        # compute tz-aware datetimes for the date
        local_tz = __import__('tzlocal').get_localzone()
        y, m, d = [int(x) for x in date_str.split('-')]
        for p in prayer_order:
            t_str = times.get(p)
            if not t_str:
                continue
            hh, mm = [int(x) for x in t_str.split(':')[:2]]
            try:
                if hasattr(local_tz, 'localize'):
                    run_dt = local_tz.localize(datetime(y, m, d, hh, mm, 0))
                else:
                    run_dt = datetime(y, m, d, hh, mm, 0, tzinfo=local_tz)
            except Exception:
                continue

            prepare_dt = run_dt - timedelta(minutes=1)
            prepare_id = f'azan_job_{date_str}_{p}_prepare'
            play_id = f'azan_job_{date_str}_{p}_play'

            # Remove existing if present
            try:
                if SCHEDULER.get_job(prepare_id):
                    SCHEDULER.remove_job(prepare_id)
            except Exception:
                pass
            try:
                if SCHEDULER.get_job(play_id):
                    SCHEDULER.remove_job(play_id)
            except Exception:
                pass

            # Force-add jobs regardless of current time
            SCHEDULER.add_job(_run_prepare_job, 'date', run_date=prepare_dt, id=prepare_id, name='_run_prepare_job', args=[p])
            SCHEDULER.add_job(_run_play_job, 'date', run_date=run_dt, id=play_id, name='_run_play_job', args=[p, 'azan.mp3'])
            scheduled.append({'prayer': p, 'prepare_at': prepare_dt.isoformat(), 'play_at': run_dt.isoformat()})

        return jsonify({'status': 'ok', 'scheduled': scheduled})
    except subprocess.CalledProcessError as e:
        logger.exception('Force schedule failed: %s', e)
        return jsonify({'status': 'error', 'message': 'Node compute failed', 'detail': str(e.output)}), 500
    except Exception as e:
        logger.exception('api_scheduler_force_schedule error: %s', e)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/scheduler/force-schedule', methods=['POST'])
def api_scheduler_force_schedule_payload():
    """Force-schedule by accepting explicit job payloads (compatible with azan-01).

    Expected JSON: { "jobs": [ {"id":"...","run_date":"ISO","prayer":"fajr","file":"azan.mp3"}, ... ] }
    """
    if SCHEDULER is None:
        init_scheduler()
    try:
        payload = request.get_json(silent=True) or {}
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

                try:
                    run_date = datetime.fromisoformat(rd.replace('Z', '+00:00'))
                except Exception:
                    errors.append({"job": j, "error": "invalid run_date"})
                    continue

                if not SCHEDULER:
                    errors.append({"job": j, "error": "scheduler not available"})
                    continue

                if SCHEDULER.get_job(jid):
                    logger.info(f"Job {jid} already exists; skipping")
                    continue

                # Try to add a persistable job by module:function name so SQLAlchemyJobStore can persist
                # Prefer `persistent_jobs:test_job_func` so the jobstore can import the callable
                added = False
                try:
                    SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file, 'prayer': prayer})
                    added = True
                except Exception:
                    try:
                        # Fallback to server module path
                        SCHEDULER.add_job('server:test_job_func', trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file, 'prayer': prayer})
                        added = True
                    except Exception:
                        pass

                if not added:
                    # Final fallback to direct function reference (non-persistable)
                    SCHEDULER.add_job(test_job_func, trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file, 'prayer': prayer})

                created.append(jid)
                logger.info(f"Force-scheduled job {jid} -> {run_date}")
            except Exception as e:
                logger.exception(f"Error scheduling job {j}: {e}")
                errors.append({"job": j, "error": str(e)})

        return jsonify({"status": "ok", "created": created, "errors": errors})
    except Exception as e:
        logger.exception(f"force-schedule error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def start_playback(audio_url, coordinator):
    """Start playback on a coordinator speaker and start monitor."""
    global PLAYBACK_ACTIVE
    try:
        logger.info(f"Starting playback on {coordinator.player_name}: {audio_url}")
        try:
            coordinator.group.volume = 45
        except Exception:
            pass

        coordinator.play_uri(audio_url)
        PLAYBACK_ACTIVE = True
        threading.Thread(target=monitor_playback, args=(coordinator,), daemon=True).start()
    except Exception as e:
        logger.error(f"start_playback error: {e}")


def _run_prepare_job(prayer=None):
    """APScheduler callable used by persisted jobs (module-level name required)."""
    logger.info(f"Scheduler running prepare job for {prayer}")
    try:
        # prepare_group() uses Flask helpers (jsonify / current_app), so ensure
        # we have an application context when running from the scheduler.
        try:
            with app.app_context():
                return prepare_group()
        except Exception:
            # If app context fails for any reason, still attempt to call prepare_group
            # so we can log and return an error response.
            return prepare_group()
    except Exception as e:
        logger.exception('Prepare job failed: %s', e)


def _run_play_job(prayer=None, file='azan.mp3'):
    """APScheduler callable used by persisted jobs to start playback."""
    logger.info(f"Scheduler running play job for {prayer}, file={file}")
    try:
        # Use the in-process playback helper so we respect played markers and
        # centralized behavior.
        result = play_from_job(file, prayer=prayer, force=False)
        if result.get('status') != 'success':
            logger.warning(f"Scheduled play did not start: {result}")
    except Exception as e:
        logger.exception('Play job failed: %s', e)


def test_job_func(job_id=None, note=None, **kwargs):
    """A simple importable function that can be scheduled and persisted.
    It logs invocation and appends a record to the play history for visibility.
    """
    logger.info(f"Test job executed: {job_id} note={note}")
    try:
        entry = {"file": "test-job", "ts": datetime.utcnow().isoformat() + 'Z', "job_id": job_id, "note": note}
        if os.path.exists(PLAY_HISTORY_FILE):
            try:
                with open(PLAY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    hist = json.load(f)
            except Exception:
                hist = []
        else:
            hist = []

        hist.append(entry)
        try:
            with open(PLAY_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(hist, f)
        except Exception as e:
            logger.warning(f"Could not write play history from test job: {e}")
    except Exception:
        pass

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    # Initialize scheduler (will load jobs from jobstore if present)
    try:
        init_scheduler()
    except Exception:
        logger.exception('Scheduler init failed')

    app.run(host='0.0.0.0', port=5000)
