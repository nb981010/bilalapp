import os
import time
import threading
import logging
from playback import get_local_ip, get_sonos_speakers, choose_coordinator, build_audio_url, set_group_volume, play_uri, start_monitor
import json
from datetime import datetime, timezone, timedelta
from flask import Flask, send_from_directory, jsonify, request
from flask import abort
import os

# Local prayer calculation dependency (optional at runtime)
try:
    from praytimes import PrayTimes
    PRAYTIMES_AVAILABLE = True
except Exception:
    PRAYTIMES_AVAILABLE = False

# Optional tz detection for local timezone-aware scheduling
try:
    from tzlocal import get_localzone
    TZLOCAL_AVAILABLE = True
except Exception:
    TZLOCAL_AVAILABLE = False
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

# Default coordinates (Dubai) used when computing prayer times server-side
DUBAI_COORDS = (25.2048, 55.2708)

# played history marker (file-backed)
PLAY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'play_history.json')
# persisted played markers to prevent duplicate plays within a day
PLAYED_MARKERS_FILE = os.path.join(os.path.dirname(__file__), 'logs', 'played_markers.json')

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def compute_prayer_times_for_date_module(d: datetime):
    """Module-level prayer time computation returning prayer->UTC datetime mapping.

    This mirrors the logic used inside init_scheduler but is importable so
    APScheduler can persist jobs that reference a textual module:function.
    """
    # Mandatory Node/adahn calculation for module usage: do NOT fallback.
    try:
        import shutil, subprocess, json
        node = shutil.which('node')
        if not node:
            logger.error('Node not found: cannot compute adhan times (module)')
            return {}

        tzname = None
        if TZLOCAL_AVAILABLE:
            try:
                tzname = get_localzone().zone
            except Exception:
                tzname = None
        if not tzname:
            tzname = 'Asia/Dubai'

        script = os.path.join(os.path.dirname(__file__), 'tools', 'compute_prayer_times.mjs')
        lat, lon = DUBAI_COORDS
        args = [node, script, d.strftime('%Y-%m-%d'), str(lat), str(lon), tzname]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0 or not proc.stdout:
            logger.error(f'Node adhan script failed (module): rc={proc.returncode} stderr={proc.stderr}')
            return {}

        js = json.loads(proc.stdout)
        mapping = {}
        for k in ('fajr', 'dhuhr', 'asr', 'maghrib', 'isha'):
            v = js.get(k)
            if v:
                try:
                    dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
                    mapping[k] = dt
                except Exception:
                    logger.exception('Failed parsing datetime from adhan output (module)')

        return mapping
    except Exception as e:
        logger.exception(f'Adhan/node computation failed (module): {e}')
        return {}


def schedule_today_jobs_for_date(target_date: datetime):
    """Module-level scheduler that creates persistent Azan jobs for `target_date`.

    This function is importable (module:function string) and thus can be used
    as the callable for persisted cron jobs in APScheduler.
    """
    global SCHEDULER
    if not SCHEDULER:
        logger.warning('Scheduler not available; cannot schedule jobs')
        return

    times = compute_prayer_times_for_date_module(target_date)
    if not times:
        logger.info('No prayer times computed for scheduling')
        return

    date_str = target_date.strftime('%Y-%m-%d')
    for prayer, dt in times.items():
        jid = f'azan-{date_str}-{prayer}'
        try:
            run_date = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=timezone.utc)
        except Exception:
            run_date = None

        if not run_date:
            continue

        if run_date <= datetime.utcnow().replace(tzinfo=timezone.utc):
            logger.debug(f"Skipping scheduling past prayer {prayer} at {run_date}")
            continue

        if SCHEDULER.get_job(jid):
            logger.debug(f"Job {jid} already exists; skipping")
            continue

        # Use a prayer-specific file for Fajr; otherwise use generic azan
        file_name = 'fajr.mp3' if prayer and prayer.lower() == 'fajr' else 'azan.mp3'

        try:
            SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file_name, 'prayer': prayer})
            logger.info(f"Scheduled Azan job {jid} -> {run_date}")
        except Exception as e:
            logger.error(f"Failed to schedule job {jid}: {e}")


def schedule_today_jobs_wrapper():
    """Wrapper for cron job: schedules today's azan jobs at invocation time."""
    # The rescheduler runs at local 00:15 (with a timezone set on the cron job).
    # Use the local date (tzlocal if available, otherwise Asia/Dubai) so we
    # schedule jobs for the intended local day rather than the UTC day.
    try:
        local_tz = None
        if TZLOCAL_AVAILABLE:
            try:
                from tzlocal import get_localzone
                local_tz = get_localzone()
            except Exception:
                local_tz = None

        if local_tz is None:
            try:
                # zoneinfo is available on modern Python; use Asia/Dubai as fallback
                from zoneinfo import ZoneInfo
                local_tz = ZoneInfo('Asia/Dubai')
            except Exception:
                local_tz = timezone.utc

        local_now = datetime.now(local_tz)
        # Pass the local datetime so the scheduler computes today's local date
        schedule_today_jobs_for_date(local_now)
    except Exception:
        # Fallback to UTC date if anything goes wrong
        schedule_today_jobs_for_date(datetime.utcnow())



def init_scheduler():
    """Initialize APScheduler with a persistent jobstore and rescheduler jobs.

    This function is safe to call multiple times; it will only start the
    scheduler once per process.
    """
    global SCHEDULER
    if not APSCHEDULER_AVAILABLE:
        logger.warning("APScheduler or SQLAlchemy not available; running without persistent scheduler.")
        return

    if SCHEDULER is not None:
        logger.debug("Scheduler already initialized in this process; skipping init")
        return

    try:
        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{JOBSTORE_PATH}')
        }
        # Prefer local timezone when available so cron triggers and displayed
        # next-run times align with local expectations (Asia/Dubai fallback).
        try:
            if TZLOCAL_AVAILABLE:
                try:
                    scheduler_tz = get_localzone()
                except Exception:
                    from zoneinfo import ZoneInfo
                    scheduler_tz = ZoneInfo('Asia/Dubai')
            else:
                from zoneinfo import ZoneInfo
                scheduler_tz = ZoneInfo('Asia/Dubai')
        except Exception:
            scheduler_tz = timezone.utc

        SCHEDULER = BackgroundScheduler(jobstores=jobstores, timezone=scheduler_tz)
        SCHEDULER.start()
        logger.info(f"APScheduler started with jobstore: sqlite:///{JOBSTORE_PATH}")

    except Exception as e:
        logger.error(f"Failed to start APScheduler with SQLAlchemyJobStore: {e}")
        SCHEDULER = None
        return

    # Helper: compute prayer times (local fallback) and schedule date jobs
    def compute_prayer_times_for_date(d: datetime):
        """Return a dict of prayer name -> UTC datetime for the given date.

        Uses `praytimes` python library when available. Times are returned
        as timezone-naive UTC datetimes.
        """
        # Mandatory Node/adahn calculation: do NOT fall back to python praytimes.
        try:
            import shutil, subprocess, json
            node = shutil.which('node')
            if not node:
                logger.error('Node not found: cannot compute adhan times')
                return {}

            tzname = None
            if TZLOCAL_AVAILABLE:
                try:
                    tzname = get_localzone().zone
                except Exception:
                    tzname = None
            if not tzname:
                tzname = 'Asia/Dubai'

            script = os.path.join(os.path.dirname(__file__), 'tools', 'compute_prayer_times.mjs')
            lat, lon = DUBAI_COORDS
            args = [node, script, d.strftime('%Y-%m-%d'), str(lat), str(lon), tzname]
            proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0 or not proc.stdout:
                logger.error(f'Node adhan script failed: rc={proc.returncode} stderr={proc.stderr}')
                return {}

            js = json.loads(proc.stdout)
            mapping = {}
            for k in ('fajr', 'dhuhr', 'asr', 'maghrib', 'isha'):
                v = js.get(k)
                if v:
                    try:
                        dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
                        mapping[k] = dt
                    except Exception:
                        logger.exception('Failed parsing datetime from adhan output')

            return mapping
        except Exception as e:
            logger.exception(f'Adhan/node computation failed: {e}')
            return {}

    def schedule_today_jobs(target_date: datetime):
        """Schedule date-based Azan jobs for the given date (UTC datetimes).
        Idempotent: will not create a job if job id already exists in the store.
        """
        if not SCHEDULER:
            logger.warning('Scheduler not available; cannot schedule jobs')
            return

        # Compute times
        times = compute_prayer_times_for_date(target_date)
        if not times:
            logger.info('No prayer times computed for scheduling')
            return

        date_str = target_date.strftime('%Y-%m-%d')
        for prayer, dt in times.items():
            # build job id with lowercase prayer name
            jid = f'azan-{date_str}-{prayer}'
            # Only add future jobs (dt is UTC naive representing UTC time)
            try:
                run_date = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=timezone.utc)
            except Exception:
                run_date = None

            if not run_date:
                continue

            # skip if run_date already in the past
            if run_date <= datetime.utcnow().replace(tzinfo=timezone.utc):
                logger.debug(f"Skipping scheduling past prayer {prayer} at {run_date}")
                continue

            if SCHEDULER.get_job(jid):
                logger.debug(f"Job {jid} already exists; skipping")
                continue

            # add persistent one-shot job that will call persistent_jobs:test_job_func
            # Use prayer-specific file for Fajr
            try:
                file_name = 'fajr.mp3' if prayer and prayer.lower() == 'fajr' else 'azan.mp3'
                SCHEDULER.add_job('persistent_jobs:test_job_func', trigger='date', run_date=run_date, id=jid, kwargs={'job_id': jid, 'note': prayer, 'file': file_name, 'prayer': prayer})
                logger.info(f"Scheduled Azan job {jid} -> {run_date}")
            except Exception as e:
                logger.error(f"Failed to schedule job {jid}: {e}")

    # Add a daily rescheduler job at 00:15 UTC that will create jobs for the day
    try:
        if not SCHEDULER.get_job('rescheduler-daily'):
            # Prefer to schedule daily at local 00:15 if tzlocal is available
            try:
                if TZLOCAL_AVAILABLE:
                    tz = get_localzone()
                else:
                    tz = timezone.utc
            except Exception:
                tz = timezone.utc

            # Use a textual module:function reference so the job can be persisted
            # by SQLAlchemyJobStore. `schedule_today_jobs_wrapper` is defined at
            # module level above.
            try:
                # Do NOT pass a per-job timezone here — rely on scheduler timezone
                # so cron triggers are interpreted in the scheduler's zone.
                SCHEDULER.add_job('server:schedule_today_jobs_wrapper', trigger='cron', hour=0, minute=15, id='rescheduler-daily')
                logger.info(f"Scheduled daily rescheduler job at 00:15 (scheduler tz={getattr(SCHEDULER, 'timezone', 'unknown')}) (id=rescheduler-daily)")
            except Exception as e:
                logger.warning(f'Could not add rescheduler-daily job (persistable reference failed): {e}')
        else:
            logger.info('Daily rescheduler job already present')
    except Exception as e:
        logger.warning(f'Could not add rescheduler-daily job: {e}')

    # If jobstore is empty (no azan jobs scheduled for today), run an immediate populate
    try:
        jobs = SCHEDULER.get_jobs()
        has_azan = any(j.id.startswith('azan-') for j in jobs)
        if not has_azan:
            logger.info('Jobstore appears empty of azan jobs; scheduling today immediately')
            # Use module-level scheduler helper to ensure consistent behavior
            schedule_today_jobs_for_date(datetime.utcnow())
    except Exception as e:
        logger.warning(f'Error checking existing jobs: {e}')


@app.route('/api/health/scheduler', methods=['GET'])
def api_health_scheduler():
    """Return scheduler health: whether scheduler is initialized, presence of rescheduler, and azan jobs."""
    try:
        info = {'scheduler_available': bool(SCHEDULER)}
        if not SCHEDULER:
            return jsonify(info)

        res = SCHEDULER.get_job('rescheduler-daily')
        info['rescheduler'] = {'exists': bool(res)}
        # Present next_run_time in local timezone for easier human reading
        try:
            if TZLOCAL_AVAILABLE:
                tz = get_localzone()
            else:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo('Asia/Dubai')
        except Exception:
            tz = timezone.utc

        if res and getattr(res, 'next_run_time', None):
            try:
                info['rescheduler']['next_run_time'] = res.next_run_time.astimezone(tz).isoformat()
            except Exception:
                info['rescheduler']['next_run_time'] = str(res.next_run_time)

        azan_jobs = []
        for j in SCHEDULER.get_jobs():
            if j.id.startswith('azan-'):
                nrt = None
                if getattr(j, 'next_run_time', None):
                    try:
                        nrt = j.next_run_time.astimezone(tz).isoformat()
                    except Exception:
                        nrt = str(j.next_run_time)
                azan_jobs.append({'id': j.id, 'next_run_time': nrt})

        info['azan_jobs'] = azan_jobs
        return jsonify(info)
    except Exception as e:
        logger.error(f"health endpoint error: {e}")
        return jsonify({'error': str(e)}), 500



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

        # Determine local timezone for display
        try:
            if TZLOCAL_AVAILABLE:
                tz = get_localzone()
            else:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo('Asia/Dubai')
        except Exception:
            tz = timezone.utc

        jobs = []
        for job in SCHEDULER.get_jobs():
            nrt = job.next_run_time
            nrt_str = None
            if nrt:
                try:
                    local_nrt = nrt.astimezone(tz)
                    # ISO with offset for clarity
                    nrt_str = local_nrt.isoformat()
                except Exception:
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
        # Enforce that test/force operations require a testing token to avoid
        # accidental modifications from an unauthorised UI. The environment
        # variable `TESTING_TOKEN` should be set on test/dev deployments.
        testing_token = os.environ.get('TESTING_TOKEN')
        if testing_token:
            header = request.headers.get('X-Testing-Token')
            if header != testing_token:
                logger.warning('Rejected force-schedule: missing/invalid testing token')
                return jsonify({'status': 'error', 'message': 'testing token required'}), 403

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
        # Only allow simulate-play when a valid testing token is provided.
        testing_token = os.environ.get('TESTING_TOKEN')
        if testing_token:
            header = request.headers.get('X-Testing-Token')
            if header != testing_token:
                logger.warning('Rejected simulate-play: missing/invalid testing token')
                return jsonify({'status': 'error', 'message': 'testing token required'}), 403

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
        # Only allow creating test jobs when a testing token is provided
        testing_token = os.environ.get('TESTING_TOKEN')
        if testing_token:
            header = request.headers.get('X-Testing-Token')
            if header != testing_token:
                logger.warning('Rejected create_test_job: missing/invalid testing token')
                return jsonify({'status': 'error', 'message': 'testing token required'}), 403
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


@app.route('/api/scheduler/repopulate_today', methods=['POST'])
def api_scheduler_repopulate_today():
    """Admin endpoint: remove today's azan jobs and re-schedule using server calculation.

    This will delete any persisted `azan-YYYY-MM-DD-*` jobs for today's local date
    and create new ones using the adhan-based calculation (or fallback).
    """
    try:
        if not SCHEDULER:
            return jsonify({"status": "error", "message": "Scheduler not available"}), 500

        # Determine local date for 'today'
        if TZLOCAL_AVAILABLE:
            try:
                tz = get_localzone()
                today = datetime.now(tz).date()
            except Exception:
                today = datetime.utcnow().date()
        else:
            today = datetime.utcnow().date()

        date_str = today.isoformat()

        # Remove existing azan jobs for today
        removed = []
        for job in SCHEDULER.get_jobs():
            if job.id.startswith(f'azan-{date_str}-'):
                try:
                    SCHEDULER.remove_job(job.id)
                    removed.append(job.id)
                except Exception as e:
                    logger.warning(f"Failed to remove job {job.id}: {e}")

        # Recreate jobs for today using module-level helper
        schedule_today_jobs_for_date(datetime.combine(today, datetime.min.time()))

        return jsonify({"status": "ok", "removed": removed})
    except Exception as e:
        logger.error(f"repopulate_today error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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

        # Allow the Sonos grouping to settle for a short moment before returning
        try:
            time.sleep(1.5)
        except Exception:
            pass

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

        # Attempt to play; if the coordinator isn't properly the group coordinator
        # Sonos may reject `play_uri`. Retry once after re-resolving the coordinator.
        audio_url = build_audio_url(filename)
        logger.info(f"Playing URL (in-process): {audio_url} on {getattr(coordinator, 'player_name', None)}")

        played_success = False
        last_exc = None

        # Initial attempts: try twice, re-resolving coordinator between attempts
        for attempt in (1, 2):
            try:
                set_group_volume(coordinator, 45)
                play_uri(coordinator, audio_url)
                played_success = True
                break
            except Exception as e:
                last_exc = e
                logger.warning(f"play_uri attempt {attempt} failed: {e}")
                if attempt == 1:
                    try:
                        time.sleep(1.0)
                    except Exception:
                        pass
                    speakers = get_sonos_speakers()
                    coordinator = choose_coordinator(speakers) or coordinator
                    logger.info(f"Re-resolved coordinator to: {getattr(coordinator, 'player_name', None)}")
                    continue

        # If initial retries failed, attempt robust recovery: unjoin & rejoin members then play
        if not played_success:
            try:
                logger.info("Attempting unjoin/rejoin recovery for Sonos group")
                speakers = get_sonos_speakers()
                if speakers:
                    coordinator = choose_coordinator(speakers) or coordinator

                    # Try to unjoin members from the coordinator first
                    try:
                        members = list(getattr(coordinator, 'group').members)
                    except Exception:
                        members = []

                    for m in members:
                        if m == coordinator:
                            continue
                        try:
                            m.unjoin()
                        except Exception:
                            pass

                    # Small pause to let unjoin take effect
                    try:
                        time.sleep(1.0)
                    except Exception:
                        pass

                    # Re-join members to the coordinator
                    for s in speakers:
                        try:
                            if s == coordinator:
                                continue
                            s.join(coordinator)
                        except Exception:
                            pass

                    # Allow group to stabilize
                    try:
                        time.sleep(1.5)
                    except Exception:
                        pass

                    # Final attempt to play
                    try:
                        set_group_volume(coordinator, 45)
                        play_uri(coordinator, audio_url)
                        played_success = True
                        logger.info("Playback started after recovery")
                    except Exception as e:
                        last_exc = e
                        logger.error(f"Playback failed after recovery: {e}")
                else:
                    logger.error("No speakers found during recovery attempt")
            except Exception as e:
                last_exc = e
                logger.error(f"Recovery attempt error: {e}")

        if not played_success:
            # All attempts failed
            msg = str(last_exc) if last_exc else 'unknown error'
            return {"status": "error", "message": msg}

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
    # When running as script, ensure scheduler initialized and run Flask dev server
    init_scheduler()
    logger.info("Server Starting on Port 5000...")
    app.run(host='0.0.0.0', port=5000)

# Ensure scheduler initialized when module is imported (useful for gunicorn --preload)
try:
    init_scheduler()
except Exception as e:
    logger.exception(f"init_scheduler() on import failed: {e}")
