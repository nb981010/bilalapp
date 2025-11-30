import os
import time
import uuid
import threading
import logging
import socket
import json
import subprocess
from datetime import datetime, date, timedelta
from flask import Flask, send_from_directory, jsonify, request
import requests
from subprocess import PIPE, Popen
from zoneinfo import ZoneInfo
import sqlite3
import sys

# Optional scheduler/prayer time imports (installed by install.sh)
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    import praytimes
    from tzlocal import get_localzone
    import fcntl
    SCHEDULER_AVAILABLE = True
    # Optional SQLAlchemy jobstore support
    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        SQLALCHEMY_AVAILABLE = True
    except Exception:
        SQLALCHEMY_AVAILABLE = False
except Exception:
    SCHEDULER_AVAILABLE = False
    SCHEDULER_IMPORT_ERROR = None
    try:
        import traceback
        SCHEDULER_IMPORT_ERROR = traceback.format_exc()
    except Exception:
        SCHEDULER_IMPORT_ERROR = 'Unknown import error for scheduler-related packages'

# Path to SQLite DB (used for APScheduler jobstore and play history)
DB_PATH = os.environ.get('BILAL_DB_PATH', 'bilal_jobs.sqlite')


def get_prayer_tz():
    """Return timezone to use for prayer calculations.

    Priority:
      1. `PRAYER_TZ` environment variable (ZoneInfo name)
      2. system local zone via tzlocal
      3. fallback to UTC
    """
    tz_env = os.environ.get('PRAYER_TZ')
    if tz_env:
        try:
            return ZoneInfo(tz_env)
        except Exception:
            # invalid env value; fall through to system tz
            pass
    try:
        return get_localzone()
    except Exception:
        try:
            return ZoneInfo('UTC')
        except Exception:
            return None

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/sys.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

# Ensure this script is importable as module name 'server' when executed as __main__.
# APScheduler textual job references require the module path to be importable; when
# running the script directly (`python server.py`) its module name is '__main__',
# so register it under 'server' in sys.modules so textual references like
# 'server._http_post_play' resolve correctly.
if __name__ == '__main__':
    try:
        sys.modules['server'] = sys.modules['__main__']
    except Exception:
        pass

# Safely handle any stale process on port 5000, but only once per host boot/service install.
# Create a lightweight marker file in /tmp to avoid repeated kills during rapid restarts.
PORT_CHECK_MARKER = '/tmp/bilalv3_port_check_done'
if not os.path.exists(PORT_CHECK_MARKER):
    try:
        # Use `ss` to inspect listening processes on port 5000 (may require sudo to show all details).
        ss = subprocess.run(['ss', '-ltnp', 'sport = :5000'], check=False, capture_output=True, text=True)
        ss_out = (ss.stdout or '') + (ss.stderr or '')
        if not ss_out.strip():
            logger.info("Port 5000 appears free")
        else:
            curpid = str(os.getpid())
            # If current process is already using the port, do nothing.
            if curpid in ss_out:
                logger.info(f"Port 5000 is in use by current process (pid {curpid}); not killing")
            # If output references obvious bilal identifiers, avoid killing.
            elif 'server.py' in ss_out or 'bilal-beapp' in ss_out:
                logger.info("Port 5000 is in use by a bilal process; not killing")
            else:
                logger.info("Port 5000 is in use by another process; killing stale process(es)")
                try:
                    subprocess.run(['fuser', '-k', '5000/tcp'], check=False)
                    logger.info("Killed stale process(es) on port 5000")
                except Exception as e:
                    logger.warning(f"Failed to kill stale process on port 5000: {e}")
        # Write marker so this check won't run again until marker is removed
        try:
            with open(PORT_CHECK_MARKER, 'w') as f:
                f.write(f"checked_by_pid:{os.getpid()}\n")
        except Exception as e:
            logger.warning(f"Failed to write port check marker: {e}")
    except Exception as e:
        logger.warning(f"Failed to inspect/handle port 5000: {e}")
else:
    logger.info("Port check already completed previously; skipping port-kill logic")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_SNAPSHOT = {}  # Store zone snapshots: {uid: {volume, uri, position}}
PLAYBACK_ACTIVE = False
AZAN_LOCK = False  # Prevent music/radio playback during Azan
AZAN_STARTED = False  # True when initial Azan start succeeded (prevents retries)
STATIC_ZONE_NAMES = [
    "Pool",
    "Boy 1",
    "Boy 2",
    "Girls Room",
    "Living Room",
    "Master Bedroom"
]

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
    """Discover and return Sonos speakers with fast timeout."""
    logger.info("Starting Sonos speaker discovery")
    try:
        import soco
    except ImportError:
        logger.error("SoCo library not found.")
        return []
    # Use single attempt with 2-second timeout to avoid slow API responses
    try:
        logger.debug("Discovery attempt (2s timeout)")
        zones = list(soco.discover(timeout=2) or [])
        if zones:
            logger.info(f"Discovered {len(zones)} Sonos speakers: {[z.player_name for z in zones]}")
            return zones
        else:
            logger.warning("No Sonos speakers found")
    except Exception as e:
        logger.error(f"Error during Sonos discovery: {e}")
    logger.info("No Sonos speakers discovered, returning empty list")
    return []


def _write_play_session_event(event: dict):
    """Append a structured JSON event to `logs/play_sessions.log` (one JSON object per line)."""
    try:
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', 'play_sessions.log')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.warning(f"Failed to write play session event: {e}")

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
    logger.info("API /api/zones requested")
    try:
        speakers = get_sonos_speakers()
        found_names = [s.player_name for s in speakers]
        data = []
        # Add discovered zones that match static names
        for s in speakers:
            if s.player_name in STATIC_ZONE_NAMES:
                status = 'idle'
                try:
                    info = s.get_current_transport_info()
                    if info['current_transport_state'] == 'PLAYING':
                        status = 'playing_music'
                except Exception as e:
                    logger.warning(f"Failed to get transport info for {s.player_name}: {e}")
                data.append({
                    "id": s.uid,
                    "name": s.player_name,
                    "isAvailable": True,
                    "status": status,
                    "volume": s.volume
                })
        # Add static zones not found in discovery as offline
        for name in STATIC_ZONE_NAMES:
            if name not in found_names:
                data.append({
                    "id": name,
                    "name": name,
                    "isAvailable": False,
                    "status": "offline",
                    "volume": 0
                })
        logger.info(f"API /api/zones returning {len(data)} zones")
        return jsonify(data)
    except Exception as e:
        logger.error(f"API /api/zones error: {e}")
        return jsonify([]), 500


@app.route('/api/prayertimes', methods=['GET'])
def api_prayer_times():
    """Return prayer times for a given date (query param `date=YYYY-MM-DD`).
    Prefer computing with the frontend `adhan` library via the Node helper for exact parity.
    Falls back to Python `praytimes` if Node/adhan is not available.
    """
    date_q = request.args.get('date')
    # Try Node helper first
    try:
        script = os.path.join(os.path.dirname(__file__), 'scripts', 'compute_prayer_times.mjs')
        if os.path.exists(script):
            cmd = ['node', script]
            if date_q:
                cmd.append(date_q)
            # Set TZ environment variable to Asia/Dubai for the subprocess
            env = os.environ.copy()
            env['TZ'] = 'Asia/Dubai'
            p = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, env=env)
            out, err = p.communicate(timeout=5)
            if p.returncode == 0 and out:
                try:
                    return jsonify(json.loads(out))
                except Exception:
                    logger.warning(f"Node helper returned invalid JSON: {out}")
            else:
                logger.warning(f"Node helper failed: rc={p.returncode} err={err}")
    except Exception as e:
        logger.warning(f"Failed to run node helper for prayertimes: {e}")

    # Fallback to existing praytimes calculation
    try:
        tz = get_prayer_tz()
        try:
            tgt = datetime.now(tz).date() if tz is not None else date.today()
        except Exception:
            tgt = date.today()
        if date_q:
            try:
                tgt = datetime.fromisoformat(date_q).date()
            except Exception:
                pass
        # Prefer DB-configured settings if present
        try:
            s = _read_settings_table(test=False)
            lat = float(s.get('prayer_lat') or os.environ.get('PRAYER_LAT', '25.2048'))
            lon = float(s.get('prayer_lon') or os.environ.get('PRAYER_LON', '55.2708'))
        except Exception:
            lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
            lon = float(os.environ.get('PRAYER_LON', '55.2708'))
        tz = get_prayer_tz()
        pt = praytimes.PrayTimes()
        try:
            local_dt = datetime(tgt.year, tgt.month, tgt.day, tzinfo=tz)
            offset_td = local_dt.utcoffset() or timedelta(0)
            tz_offset_hours = offset_td.total_seconds() / 3600.0
        except Exception:
            tz_offset_hours = 0
        times = pt.getTimes((tgt.year, tgt.month, tgt.day), (lat, lon), tz_offset_hours)
        return jsonify({'date': tgt.isoformat(), 'fajr': times.get('fajr'), 'sunrise': times.get('sunrise'), 'dhuhr': times.get('dhuhr'), 'asr': times.get('asr'), 'maghrib': times.get('maghrib'), 'isha': times.get('isha')})
    except Exception as e:
        logger.error(f"Failed to compute prayertimes fallback: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------
# Scheduler helpers (optional)
# ---------------------------------------------------------
scheduler = None
# Track missed-scheduler attempts per date so we can adapt retry cadence.
MISSED_SCHED_ATTEMPTS = {}


def _reschedule_daily_job():
    """Module-level wrapper used by APScheduler jobstore (textual reference).

    This function calls schedule_prayers_for_date for the current day. Using a
    textual reference ("server._reschedule_daily_job") avoids serialization
    warnings when using persistent jobstores.
    """
    try:
        tz = get_prayer_tz()
        try:
            cur = datetime.now(tz).date() if tz is not None else date.today()
        except Exception:
            cur = date.today()
        schedule_prayers_for_date(cur)
    except Exception as e:
        logger.warning(f"_reschedule_daily_job failed: {e}")


def _missed_scheduler_wrapper():
    """Module-level wrapper for missed-scheduler retry logic.

    This moves the inner `_try_schedule_missed` logic to a top-level callable
    so APScheduler can persist it by textual reference.
    """
    try:
        tz = get_prayer_tz()
        try:
            cur = datetime.now(tz).date() if tz is not None else date.today()
        except Exception:
            cur = date.today()
        key = cur.isoformat()
        MISSED_SCHED_ATTEMPTS[key] = MISSED_SCHED_ATTEMPTS.get(key, 0) + 1
        attempts = MISSED_SCHED_ATTEMPTS[key]
        logger.info(f"Missed-scheduler attempt #{attempts} for {key}")
        cnt = schedule_prayers_for_date(cur)
        if cnt > 0:
            logger.info(f"Missed-scheduler: scheduled {cnt} prayer jobs for today; removing retry job")
            try:
                scheduler.remove_job('missed-scheduler')
            except Exception:
                pass
            # Ensure the daily rescheduler exists for tomorrow
            try:
                if 'rescheduler-daily' not in [j.id for j in scheduler.get_jobs()]:
                    # schedule textual reference to module-level rescheduler
                    tomorrow = datetime.combine(cur + timedelta(days=1), datetime.min.time()) + timedelta(minutes=5)
                    try:
                        tomorrow = tomorrow.replace(tzinfo=tz)
                    except Exception:
                        pass
                    scheduler.add_job('server._reschedule_daily_job', trigger=DateTrigger(run_date=tomorrow), id='rescheduler-daily')
            except Exception:
                pass
            return
        if attempts >= 6:
            logger.info("Missed-scheduler reached 6 attempts; switching to hourly retries")
            try:
                scheduler.remove_job('missed-scheduler')
            except Exception:
                pass
            scheduler.add_job('server._missed_scheduler_wrapper', trigger=IntervalTrigger(hours=1), id='missed-scheduler')
            return
    except Exception as e:
        logger.warning(f"Missed-scheduler attempt failed: {e}")

def _http_post_play(filename):
    """POST to the local /api/play endpoint to trigger playback."""
    try:
        import urllib.request
        body = json.dumps({"file": filename}).encode('utf-8')
        req = urllib.request.Request('http://127.0.0.1:5000/api/play', data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode('utf-8')
            logger.info(f"Scheduled play triggered for {filename}: {resp.status} {resp_body}")
    except Exception as e:
        logger.error(f"Scheduled play POST failed for {filename}: {e}")


def control_with_fallback(cloud_fn, local_fn):
    """Decision engine: try cloud first, fallback to local on failure."""
    try:
        # call cloud microservice
        cloud_url = os.environ.get('SONOS_CLOUD_URL', 'http://127.0.0.1:6000')
        # cloud_fn is a callable that should perform HTTP request to cloud service
        try:
            return cloud_fn(cloud_url)
        except Exception as e:
            logger.warning(f"Cloud action failed: {e}; falling back to local SoCo")
    except Exception as e:
        logger.warning(f"control_with_fallback cloud check error: {e}")
    # local fallback
    try:
        local_url = os.environ.get('SOCO_LOCAL_URL', 'http://127.0.0.1:5001')
        return local_fn(local_url)
    except Exception as e:
        logger.error(f"Local SoCo action failed: {e}")
        raise


def _http_get_prepare():
    """GET the local /api/prepare endpoint to prepare zones for Azan."""
    try:
        import urllib.request
        req = urllib.request.Request('http://127.0.0.1:5000/api/prepare')
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode('utf-8')
            logger.info(f"Scheduled prepare triggered: {resp.status} {resp_body}")
    except Exception as e:
        logger.error(f"Scheduled prepare GET failed: {e}")


def _append_play_history(filename, when=None):
    """Append a successful play event to `logs/play_history.json` for later scheduling decisions."""
    # Deprecated: replaced by SQLite-backed play history helpers.
    try:
        append_play_history_sql(filename, when=when)
    except Exception as e:
        logger.warning(f"Failed to append play history (sqlite): {e}")


def init_db(db_path=None):
    """Initialize SQLite DB and ensure required tables exist."""
    db = db_path or DB_PATH
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file TEXT NOT NULL,
                ts TEXT NOT NULL
            )
        ''')
        # Settings table (key/value) for production settings
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        # Test settings (separate table) used by testing environment
        c.execute('''
            CREATE TABLE IF NOT EXISTS test_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"init_db failed: {e}")


def _read_settings_table(test: bool = False):
    """Return dict of settings from DB (production or test table)."""
    table = 'test_settings' if test else 'settings'
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"SELECT key, value FROM {table}")
        rows = c.fetchall()
        conn.close()
        return {k: v for k, v in rows}
    except Exception as e:
        logger.warning(f"_read_settings_table failed: {e}")
        return {}


def _write_setting(key: str, value: str, test: bool = False):
    table = 'test_settings' if test else 'settings'
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"INSERT INTO {table} (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"_write_setting failed: {e}")
        return False


def append_play_history_sql(filename, when=None):
    """Insert a play history row into SQLite and prune old entries."""
    try:
        os.makedirs('logs', exist_ok=True)
        tz = get_prayer_tz() or ZoneInfo('UTC')
        ts = (when or datetime.now(tz)).isoformat()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO play_history (file, ts) VALUES (?, ?)', (filename, ts))
        conn.commit()
        try:
            # Keep only recent 100 rows
            c.execute('DELETE FROM play_history WHERE id NOT IN (SELECT id FROM play_history ORDER BY id DESC LIMIT 100)')
            conn.commit()
        except Exception:
            pass
        conn.close()
    except Exception as e:
        logger.warning(f"append_play_history_sql failed: {e}")


def read_recent_play_history(limit=100):
    """Return recent play history rows as list of dicts ordered oldest->newest."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT file, ts FROM play_history ORDER BY id DESC LIMIT ?', (limit,))
        rows = c.fetchall()
        conn.close()
        rows.reverse()
        return [{'file': r[0], 'ts': r[1]} for r in rows]
    except Exception as e:
        logger.warning(f"read_recent_play_history failed: {e}")
        return []


def schedule_prayers_for_date(target_date: date):
    """Compute prayer times for `target_date` and schedule Azan jobs.

    Returns the number of Azan jobs successfully scheduled (0 if none).
    """
    global scheduler
    if not SCHEDULER_AVAILABLE:
        logger.warning("Scheduler or prayer-time libraries not available; skipping scheduling")
        return 0

    scheduled_count = 0
    try:
        # Get coordinates from DB settings if provided, else environment, else default to Dubai
        try:
            settings = _read_settings_table(test=False)
            lat = float(settings.get('prayer_lat') or os.environ.get('PRAYER_LAT', '25.2048'))
            lon = float(settings.get('prayer_lon') or os.environ.get('PRAYER_LON', '55.2708'))
        except Exception:
            lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
            lon = float(os.environ.get('PRAYER_LON', '55.2708'))
        tz = get_prayer_tz()
        # Prefer computing times with the frontend `adhan` implementation via our Node helper
        times = None
        try:
            script = os.path.join(os.path.dirname(__file__), 'scripts', 'compute_prayer_times.mjs')
            if os.path.exists(script):
                cmd = ['node', script, target_date.isoformat()]
                # Set TZ environment variable to Asia/Dubai for the subprocess
                env = os.environ.copy()
                env['TZ'] = 'Asia/Dubai'
                p = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, env=env)
                out, err = p.communicate(timeout=5)
                if p.returncode == 0 and out:
                    try:
                        node_data = json.loads(out)
                        # node_data contains times as HH:MM strings; convert to same structure as praytimes.getTimes
                        times = {
                            'fajr': node_data.get('fajr'),
                            'sunrise': node_data.get('sunrise'),
                            'dhuhr': node_data.get('dhuhr'),
                            'asr': node_data.get('asr'),
                            'maghrib': node_data.get('maghrib'),
                            'isha': node_data.get('isha')
                        }
                    except Exception:
                        logger.warning(f"Node helper returned invalid JSON for prayertimes: {out}")
                else:
                    logger.warning(f"Node helper failed for prayertimes: rc={p.returncode} err={err}")
        except Exception as e:
            logger.warning(f"Failed to run node helper for prayer schedule: {e}")

        # Fallback to Python praytimes if node helper did not produce times
        if times is None:
            pt = praytimes.PrayTimes()
            # praytimes expects a (year, month, day) tuple and a timezone offset in hours.
            # Compute the local timezone offset for the target date (may include DST)
            try:
                local_dt = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
                offset_td = local_dt.utcoffset() or timedelta(0)
                tz_offset_hours = offset_td.total_seconds() / 3600.0
            except Exception:
                tz_offset_hours = 0
            # Pass the computed offset so returned times are in local time
            times = pt.getTimes((target_date.year, target_date.month, target_date.day), (lat, lon), tz_offset_hours)
        prayer_keys = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
        # Load recent play history from SQLite
        try:
            play_history = read_recent_play_history(100)
        except Exception:
            play_history = []
        for key in prayer_keys:
            tstr = times.get(key)
            if not tstr:
                continue
            parts = tstr.split(':')
            hour = int(parts[0])
            minute = int(parts[1])
            # Create timezone-aware datetime using zoneinfo-compatible tz
            scheduled_dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=tz)
            now = datetime.now(tz)
            # Consider the prayer "served on time" only if a recorded play exists within
            # +/- tolerance minutes of the scheduled time. This prevents manual/test plays
            # outside the on-time window from affecting scheduling.
            played_on_time = False
            try:
                # Allow overriding the play tolerance via environment variable
                try:
                    tol_minutes = int(os.environ.get('PRAYER_PLAY_TOL_MIN', '5'))
                except Exception:
                    tol_minutes = 5
                for entry in play_history:
                    try:
                        p_ts = datetime.fromisoformat(entry.get('ts'))
                        # Normalize timezone if naive
                        if p_ts.tzinfo is None:
                            p_ts = p_ts.replace(tzinfo=tz)
                        delta = abs((p_ts - scheduled_dt).total_seconds())
                        if delta <= tol_minutes * 60:
                            # match by file name (fajr vs azan)
                            fname = 'fajr.mp3' if key == 'fajr' else 'azan.mp3'
                            if entry.get('file') and fname in entry.get('file'):
                                played_on_time = True
                                break
                    except Exception:
                        continue
            except Exception:
                played_on_time = False

            if scheduled_dt <= now and not played_on_time:
                logger.debug(f"Skipping past prayer {key} at {scheduled_dt}")
                continue
            if played_on_time:
                logger.info(f"Prayer {key} at {scheduled_dt} already played on time; skipping schedule")
                continue
            job_id = f"azan-{target_date.isoformat()}-{key}"
            existing = [j.id for j in scheduler.get_jobs()]
            if job_id in existing:
                logger.info(f"Job {job_id} already scheduled; skipping")
                continue
            logger.info(f"Scheduling {key} Azan at {scheduled_dt.isoformat()} (job id: {job_id})")
            filename = 'fajr.mp3' if key == 'fajr' else 'azan.mp3'
            # Use textual reference for the callable so APScheduler can serialize jobs
            # when using a persistent jobstore (e.g., SQLAlchemyJobStore).
            scheduler.add_job('server:_http_post_play', trigger=DateTrigger(run_date=scheduled_dt), args=[filename], id=job_id)
            scheduled_count += 1
    except Exception as e:
        logger.error(f"Failed to schedule prayers for {target_date}: {e}")
    return scheduled_count
def schedule_today_and_rescheduler():
    """Schedule today's prayers and a daily rescheduler at 00:05 local time."""
    if not SCHEDULER_AVAILABLE:
        return
    tz = get_prayer_tz()
    try:
        today = datetime.now(tz).date() if tz is not None else date.today()
    except Exception:
        today = date.today()

    # Attempt to schedule today's prayers and record how many jobs were added.
    added = schedule_prayers_for_date(today)

    # Schedule the daily rescheduler (next day at 00:05) using a module-level
    # textual reference so APScheduler can persist the job in a SQLAlchemy jobstore.
    try:
        tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time()) + timedelta(minutes=5)
        try:
            tomorrow = tomorrow.replace(tzinfo=tz)
        except Exception:
            pass
        if 'rescheduler-daily' not in [j.id for j in scheduler.get_jobs()]:
            scheduler.add_job('server:_reschedule_daily_job', trigger=DateTrigger(run_date=tomorrow), id='rescheduler-daily')
            logger.info(f"Scheduled daily rescheduler at {tomorrow}")
    except Exception as e:
        logger.warning(f"Failed to schedule daily rescheduler: {e}")

    # If nothing was scheduled for today (device may have been down at midnight),
    # add a retry job that will attempt to schedule today's prayers until successful.
    # Start with 5-minute retries for the first 6 attempts, then switch to hourly.
    if added == 0:
        try:
            # Use module-level wrapper `_missed_scheduler_wrapper` so jobstore can persist it
            if 'missed-scheduler' not in [j.id for j in scheduler.get_jobs()]:
                scheduler.add_job('server:_missed_scheduler_wrapper', trigger=IntervalTrigger(minutes=5), id='missed-scheduler')
                logger.info("Scheduled missed-scheduler job: 5-minute retries (first 6 attempts), then hourly")
        except Exception as e:
            logger.warning(f"Failed to schedule missed-scheduler: {e}")
    else:
        # If we scheduled jobs now, ensure the daily rescheduler is also scheduled
        try:
            # schedule textual module-level rescheduler (already added above in normal flow)
            tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time()) + timedelta(minutes=5)
            try:
                tomorrow = tomorrow.replace(tzinfo=tz)
            except Exception:
                pass
            if 'rescheduler-daily' not in [j.id for j in scheduler.get_jobs()]:
                scheduler.add_job('server:_reschedule_daily_job', trigger=DateTrigger(run_date=tomorrow), id='rescheduler-daily')
                logger.info(f"Scheduled daily rescheduler at {tomorrow}")
        except Exception:
            pass


@app.route('/api/scheduler/jobs', methods=['GET'])
def list_scheduled_jobs():
    """Return a list of scheduled jobs (if scheduler is available)."""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'available': False, 'jobs': []})
    jobs = []
    prayer_tz = get_prayer_tz()
    for j in scheduler.get_jobs():
        nrt = j.next_run_time
        if nrt is None:
            nrt_str = None
            nrt_local = None
        else:
            try:
                nrt_str = nrt.isoformat()
            except Exception:
                nrt_str = str(nrt)
            try:
                if prayer_tz is not None:
                    nrt_local = nrt.astimezone(prayer_tz).isoformat()
                else:
                    nrt_local = nrt.isoformat()
            except Exception:
                nrt_local = str(nrt)
        jobs.append({'id': j.id, 'next_run_time': nrt_str, 'next_run_time_in_prayer_tz': nrt_local})
    return jsonify({'available': True, 'jobs': jobs})


@app.route('/api/scheduler/force-schedule', methods=['POST'])
def api_force_schedule_today():
    """Force a run of today's scheduling (useful for testing). Returns number of jobs scheduled."""
    if not SCHEDULER_AVAILABLE:
        return jsonify({'available': False, 'jobs_added': 0, 'message': 'Scheduler not available'})
    try:
        tz = get_prayer_tz()
        try:
            tgt = datetime.now(tz).date() if tz is not None else date.today()
        except Exception:
            tgt = date.today()
        added = schedule_prayers_for_date(tgt)
        # Ensure daily rescheduler exists
        try:
            schedule_today_and_rescheduler()
        except Exception:
            pass
        return jsonify({'available': True, 'jobs_added': added})
    except Exception as e:
        return jsonify({'available': False, 'error': str(e)}), 500


@app.route('/api/scheduler/simulate-play', methods=['POST'])
def api_simulate_play():
    """Simulate/apply a recorded play entry for testing scheduling logic.

    Accepts JSON: {"file": "azan.mp3", "ts": "optional ISO timestamp"}
    If `ts` is omitted, uses current time in local timezone.
    This endpoint appends into `logs/play_history.json` and returns the last entries.
    """
    try:
        data = request.get_json(silent=True) or {}
        fname = (data.get('file') or 'azan.mp3').strip()
        ts_str = data.get('ts')
        try:
            tz = get_localzone()
        except Exception:
            tz = None
        if ts_str:
            try:
                when = datetime.fromisoformat(ts_str)
                if when.tzinfo is None and tz is not None:
                    when = when.replace(tzinfo=tz)
            except Exception:
                return jsonify({'status': 'error', 'message': 'Invalid ts format; use ISO8601'}), 400
        else:
            when = datetime.now(tz)
        # Append to play history
        try:
            _append_play_history(fname, when=when)
        except Exception as e:
            logger.warning(f"Failed to append simulated play history: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
        # Return recent history tail (from SQLite)
        try:
            recent = read_recent_play_history(10)
        except Exception:
            recent = []
        return jsonify({'status': 'ok', 'appended': {'file': fname, 'ts': when.isoformat()}, 'history_tail': recent})
    except Exception as e:
        logger.error(f"simulate-play error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/test/play', methods=['POST'])
def api_test_play():
    """Test-only play endpoint. Simulates a play and appends play-history for testing.

    Accepts JSON: {"file":"azan.mp3","volume":50,"ts":"optional ISO"}
    This endpoint is safe for testing and does not perform real Sonos control.
    """
    try:
        data = request.get_json(silent=True) or {}
        fname = (data.get('file') or 'azan.mp3').strip()
        ts_str = data.get('ts')
        # Append to play history so scheduler logic can see it
        try:
            if ts_str:
                when = datetime.fromisoformat(ts_str)
                _append_play_history(fname, when=when)
            else:
                _append_play_history(fname)
        except Exception:
            try:
                _append_play_history(fname)
            except Exception:
                pass
        return jsonify({'status': 'ok', 'simulated': True, 'file': fname})
    except Exception as e:
        logger.error(f"test-play error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """Get or update production settings stored in DB.

    GET: returns JSON object of settings (keys: prayer_lat, prayer_lon, calc_method, asr_madhab, css_mode, adhan_mode, sonos_mode)
    POST: accepts JSON with any of those keys to update them.
    """
    try:
        if request.method == 'GET':
            data = _read_settings_table(test=False)
            # Provide defaults when missing
            defaults = {
                'prayer_lat': '25.2048',
                'prayer_lon': '55.2708',
                'calc_method': 'IACAD',
                'asr_madhab': 'Shafi',
                'css_mode': 'online',
                'adhan_mode': 'online',
                'sonos_mode': 'online'
            }
            for k, v in defaults.items():
                data.setdefault(k, v)
            # Do not expose the passcode via the public GET settings API
            # (passcode is used only for POST enforcement).
            if 'passcode' in data:
                try:
                    data.pop('passcode')
                except Exception:
                    pass
            return jsonify(data)
        else:
                payload = request.get_json(silent=True) or {}
                # Optional enforcement: require a passcode header for production settings
                enforce = os.environ.get('BILAL_ENFORCE_SETTINGS_API', '')
                if str(enforce).lower() in ('1', 'true', 'yes'):
                    # Expect header 'X-BILAL-PASSCODE'
                    received = request.headers.get('X-BILAL-PASSCODE', '')
                    try:
                        settings = _read_settings_table(test=False)
                        stored_pass = settings.get('passcode', '1234')
                    except Exception:
                        stored_pass = '1234'
                    if not received or str(received) != str(stored_pass):
                        logger.warning('Forbidden settings POST: missing/invalid X-BILAL-PASSCODE')
                        return jsonify({'status': 'error', 'message': 'forbidden: invalid passcode header'}), 403

                for k, v in payload.items():
                    try:
                        _write_setting(k, str(v), test=False)
                    except Exception:
                        logger.warning(f"Failed to write setting {k}")
                return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"api_settings error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/test/settings', methods=['GET', 'POST'])
def api_test_settings():
    """Get or update test settings stored in DB (separate table).
    Same schema as production settings but applied to test environment.
    """
    try:
        if request.method == 'GET':
            data = _read_settings_table(test=True)
            defaults = {
                'prayer_lat': '25.2048',
                'prayer_lon': '55.2708',
                'calc_method': 'IACAD',
                'asr_madhab': 'Shafi',
                'css_mode': 'online',
                'adhan_mode': 'online',
                'sonos_mode': 'online'
            }
            for k, v in defaults.items():
                data.setdefault(k, v)
            return jsonify(data)
        else:
            payload = request.get_json(silent=True) or {}
            for k, v in payload.items():
                try:
                    _write_setting(k, str(v), test=True)
                except Exception:
                    logger.warning(f"Failed to write test setting {k}")
            return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"api_test_settings error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/transport', methods=['GET'])
def api_transport():
    """Return detailed transport and track info for discovered Sonos speakers."""
    try:
        speakers = get_sonos_speakers()
        if not speakers:
            return jsonify({'status': 'error', 'message': 'No speakers found'}), 404
        # Choose coordinator
        coordinator = next((s for s in speakers if getattr(s, 'is_coordinator', False)), speakers[0])
        result = {'coordinator': {'name': coordinator.player_name, 'uid': getattr(coordinator, 'uid', None)}, 'speakers': []}
        for s in speakers:
            try:
                transport = s.get_current_transport_info()
            except Exception:
                transport = {}
            try:
                track = s.get_current_track_info()
            except Exception:
                track = {}
            result['speakers'].append({
                'uid': getattr(s, 'uid', None),
                'name': getattr(s, 'player_name', None),
                'is_coordinator': getattr(s, 'is_coordinator', False),
                'volume': getattr(s, 'volume', None),
                'transport': transport,
                'track': track
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"api_transport error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/transport/stop', methods=['POST'])
def api_transport_stop():
    """Stop coordinator playback and unjoin other speakers (best-effort).

    Optional JSON payload: {"unjoin": true} (default true)
    """
    try:
        payload = request.get_json(silent=True) or {}
        do_unjoin = payload.get('unjoin', True)
        speakers = get_sonos_speakers()
        if not speakers:
            return jsonify({'status': 'error', 'message': 'No speakers found'}), 404
        coordinator = next((s for s in speakers if getattr(s, 'is_coordinator', False)), speakers[0])
        results = {'coordinator': coordinator.player_name, 'stopped': False, 'unjoined': []}
        try:
            coordinator.stop()
            results['stopped'] = True
        except Exception as e:
            logger.warning(f"Failed to stop coordinator {coordinator.player_name}: {e}")
        if do_unjoin:
            for s in speakers:
                if s == coordinator:
                    continue
                try:
                    s.unjoin()
                    results['unjoined'].append(getattr(s, 'player_name', None))
                except Exception as e:
                    logger.warning(f"Failed to unjoin {getattr(s, 'player_name', None)}: {e}")
        # Log a stop event for the active session if present
        try:
            event = {'event': 'stop', 'timestamp': datetime.now(get_prayer_tz() or ZoneInfo('UTC')).isoformat(), 'coordinator': coordinator.player_name}
            _write_play_session_event(event)
        except Exception:
            pass
        return jsonify(results)
    except Exception as e:
        logger.error(f"api_transport_stop error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
    global PLAYBACK_ACTIVE, AZAN_LOCK
    if AZAN_LOCK:
        logger.warning("Azan already in progress, blocking duplicate playback.")
        return jsonify({"status": "error", "message": "Azan in progress, playback blocked."}), 429
    data = request.json
    # Incoming requests may specify prayer-specific filenames (e.g. dhuhr.mp3).
    # The deployment only contains two files:
    # - `fajr.mp3` for Fajr
    # - `azan.mp3` for all other Azan times
    requested = (data.get('file') or 'fajr.mp3').strip()
    # Normalize and map to available files
    if 'fajr' in requested.lower():
        filename = 'fajr.mp3'
    else:
        filename = 'azan.mp3'

    logger.info(f"Received Play Request: {requested} -> mapped to: {filename}")
    # Create a play session id and timezone for structured logging
    session_id = str(uuid.uuid4())
    try:
        tz = get_prayer_tz() or ZoneInfo('UTC')
    except Exception:
        tz = None

    try:
        # Prefer cloud control, fallback to local SoCo
        def cloud_action(cloud_url):
            # cloud microservice expects device_id and url; here we use coordinator discovery to find first cloud-device
            # For simplicity, we call cloud discover and pick the first player id (if any) and then play
            r = requests.get(f"{cloud_url}/cloud/discover", timeout=5)
            if r.status_code != 200:
                raise Exception('cloud discover failed')
            data = r.json()
            # data expected to be list of players
            if not data:
                raise Exception('no cloud devices')
            device = data[0]
            # Normalize device id selection from a variety of possible keys returned
            device_id = None
            if isinstance(device, dict):
                for k in ('id', 'playerId', 'player_id', 'uid', 'playerID'):
                    v = device.get(k)
                    if v:
                        device_id = v
                        break
            # If device is an object with attributes (unlikely), try attribute access
            if not device_id:
                try:
                    device_id = getattr(device, 'id', None) or getattr(device, 'playerId', None) or getattr(device, 'uid', None)
                except Exception:
                    device_id = None
            if not device_id:
                raise Exception('no device id')
            local_ip = get_local_ip()
            audio_url = f"http://{local_ip}:5000/audio/{filename}"
            pr = requests.post(f"{cloud_url}/cloud/play", json={'device_id': device_id, 'url': audio_url}, timeout=5)
            if pr.status_code != 200:
                raise Exception('cloud play failed')
            return {'status': 'ok', 'mode': 'cloud'}

        def local_action(local_url):
            # Call local SoCo server to discover coordinator and play
            r = requests.get(f"{local_url}/local/discover", timeout=5)
            if r.status_code != 200:
                raise Exception('local discover failed')
            devices = r.json()
            if not devices:
                raise Exception('no local devices')
            # pick first device name
            name = devices[0].get('name')
            local_ip = get_local_ip()
            audio_url = f"http://{local_ip}:5000/audio/{filename}"
            pr = requests.post(f"{local_url}/local/play", json={'device_name': name, 'url': audio_url}, timeout=5)
            if pr.status_code not in (200, 204):
                raise Exception('local play failed')
            return {'status': 'ok', 'mode': 'local'}

        result = control_with_fallback(cloud_action, local_action)
        # If cloud/local handled playback, return success
        if result and result.get('status') == 'ok':
            return jsonify({'status': 'success', 'message': 'Playback Started', 'mode': result.get('mode')})
        # otherwise continue into original local logic as a last resort

        speakers = get_sonos_speakers()
        if not speakers:
            logger.error("No speakers found for Azan playback")
            return jsonify({"status": "error", "message": "No speakers"}), 404

        # Snapshot all zones: volume, uri, position
        global SONOS_SNAPSHOT
        SONOS_SNAPSHOT = {}
        AZAN_LOCK = True
        error_count = 0
        logger.info("Starting snapshot of current Sonos state")
        
        # Find the coordinator
        coordinator = next((s for s in speakers if s.is_coordinator), speakers[0])
        logger.info(f"Coordinator: {coordinator.player_name}")
        
        # Get coordinator's track and transport info
        track_info = coordinator.get_current_track_info()
        transport_info = coordinator.get_current_transport_info()
        logger.info(f"Coordinator track: uri={track_info.get('uri')}, position={track_info.get('position')}, state={transport_info.get('current_transport_state')}")
        
        for s in speakers:
            try:
                SONOS_SNAPSHOT[s.uid] = {
                    "volume": s.volume,
                    "uri": track_info.get("uri"),
                    "position": track_info.get("position"),
                    "state": transport_info.get("current_transport_state")
                }
                logger.info(f"Snapped {s.player_name}: vol={s.volume}, uri={track_info.get('uri')}, position={track_info.get('position')}")
                # Set volume to 50%
                s.volume = 50
                logger.info(f"Set volume to 50% for {s.player_name}")
            except Exception as e:
                logger.warning(f"Snapshot failed for {s.player_name}: {e}")
                error_count += 1
        if error_count == len(speakers):
            logger.error("Failed to snapshot any speakers")
            AZAN_LOCK = False
            return jsonify({"status": "error", "message": "Failed to snapshot all speakers."}), 500

        # Use the elected coordinator determined earlier (do not overwrite)
        local_ip = get_local_ip()
        audio_url = f"http://{local_ip}:5000/audio/{filename}"
        logger.info(f"Playing URL: {audio_url} on {coordinator.player_name}")

        # Set metadata for display
        title = "Azan by Bilal App"
        meta = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
<item id="0" parentID="0" restricted="0">
<dc:title>{title}</dc:title>
<upnp:class>object.item.audioItem</upnp:class>
<res protocolInfo="http-get:*:audio/mpeg:*">{audio_url}</res>
</item>
</DIDL-Lite>"""

        try:
            coordinator.play_uri(audio_url, meta=meta)
            # Give the speaker a short moment to accept the URI and update state
            time.sleep(1)
            # Verify the coordinator actually loaded/started the Azan URI
            try:
                post_track = coordinator.get_current_track_info()
                post_transport = coordinator.get_current_transport_info()
                post_uri = post_track.get('uri') or ''
                post_state = post_transport.get('current_transport_state')
                logger.info(f"Post-play check: uri={post_uri}, state={post_state}")
                # Consider start successful only if the coordinator reports the Azan URI or is PLAYING
                if (audio_url in post_uri) or (post_state == 'PLAYING'):
                    AZAN_STARTED = True
                    logger.info("Azan start confirmed on coordinator")
                    # Record play history for scheduling decisions (mark when playback actually started)
                    try:
                        _append_play_history(filename, when=datetime.now(tz))
                    except Exception:
                        pass
                    # Structured play-session start event
                    try:
                        event = {
                            'event': 'start',
                            'session_id': session_id,
                            'file': filename,
                            'coordinator': coordinator.player_name,
                            'coordinator_uid': getattr(coordinator, 'uid', None),
                            'speakers': [getattr(s, 'player_name', str(s)) for s in speakers],
                            'start_ts': (datetime.now(tz).isoformat() if tz is not None else datetime.now().isoformat())
                        }
                        _write_play_session_event(event)
                    except Exception as e:
                        logger.warning(f"Failed to write session start event: {e}")
                else:
                    # Treat as failure: do not retry later
                    logger.error("Coordinator did not start Azan (URI/state mismatch). Aborting single attempt.")
                    AZAN_LOCK = False
                    AZAN_STARTED = False
                    return jsonify({"status": "error", "message": "Azan playback failed to start."}), 500
            except Exception as e:
                logger.error(f"Post-play verification failed: {e}")
                AZAN_LOCK = False
                AZAN_STARTED = False
                return jsonify({"status": "error", "message": "Azan playback verification failed."}), 500
        except Exception as e:
            logger.error(f"Azan playback failed: {e}")
            # Clear lock and do NOT retry — caller wanted single-attempt semantics
            AZAN_LOCK = False
            AZAN_STARTED = False
            return jsonify({"status": "error", "message": "Azan playback failed."}), 500

        # Start Monitoring Thread
        PLAYBACK_ACTIVE = True
        threading.Thread(target=monitor_playback, args=(coordinator, speakers, audio_url, session_id)).start()

        return jsonify({"status": "success", "message": "Playback Started"})

    except Exception as e:
        logger.error(f"Play Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def monitor_playback(coordinator, speakers, audio_url, session_id=None):
    """
    Monitors playback for 3 minutes, enforcing Azan priority by overriding interruptions and resuming from interrupted position.
    Restores state after the full duration.
    """
    global PLAYBACK_ACTIVE, SONOS_SNAPSHOT, AZAN_LOCK
    logger.info("Playback Monitor Started...")
    logger.info(f"Monitoring Azan URI: {audio_url}")
    start_time = time.time()
    duration = 180  # 3 minutes
    last_azan_position = None
    resume_attempted = False
    while time.time() - start_time < duration:
        try:
            info = coordinator.get_current_transport_info()
            state = info['current_transport_state']
            track_info = coordinator.get_current_track_info()
            current_uri = track_info.get('uri')
            logger.debug(f"Playback state: {state}, URI: {current_uri}")
            if state == 'STOPPED' and current_uri == audio_url:
                logger.info("Azan finished and stopped, starting restore immediately")
                break
            if current_uri == audio_url:
                # Get Azan duration
                duration_str = track_info.get('duration', '0:02:10')
                duration_parts = duration_str.split(':')
                if len(duration_parts) == 3:
                    azan_duration_seconds = int(duration_parts[0])*3600 + int(duration_parts[1])*60 + int(duration_parts[2])
                else:
                    azan_duration_seconds = 130  # default
                # Update last known Azan position
                last_azan_position = track_info.get('position', '0:00:00')
                # Check if Azan is near end
                pos_str = last_azan_position
                pos_parts = pos_str.split(':')
                if len(pos_parts) == 3:
                    pos_seconds = int(pos_parts[0])*3600 + int(pos_parts[1])*60 + int(pos_parts[2])
                    if pos_seconds >= azan_duration_seconds:
                        logger.info(f"Azan position {pos_str} >= {azan_duration_seconds}s, Azan finished")
                        break
            elif current_uri != audio_url:
                # Only attempt a single controlled resume if the Azan actually started previously
                logger.info(f"Detected non-Azan URI: {current_uri}. last_azan_position={last_azan_position}, AZAN_STARTED={AZAN_STARTED}, resume_attempted={resume_attempted}")
                if not AZAN_STARTED:
                    logger.info("Azan was never started successfully; skipping restart attempt.")
                elif resume_attempted:
                    logger.info("Resume already attempted once; skipping further resume attempts.")
                elif not last_azan_position or last_azan_position == '0:00:00':
                    logger.info("No valid last Azan position available; skipping resume to avoid restarting from beginning.")
                else:
                    logger.info(f"Attempting single resume of Azan from position {last_azan_position}.")
                    resume_attempted = True
                    try:
                        # Force resume Azan once from last known position
                        coordinator.stop()
                        time.sleep(1)
                        title = "Azan by Bilal App"
                        meta = f"""<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
<item id="0" parentID="0" restricted="0">
<dc:title>{title}</dc:title>
<upnp:class>object.item.audioItem</upnp:class>
<res protocolInfo="http-get:*:audio/mpeg:*">{audio_url}</res>
</item>
</DIDL-Lite>"""
                        coordinator.play_uri(audio_url, meta=meta)
                        # Wait briefly and attempt to seek to last position; if seek fails, do NOT retry
                        time.sleep(1)
                        try:
                            coordinator.seek(last_azan_position)
                            logger.info(f"Seeked to {last_azan_position}")
                        except Exception as e:
                            logger.warning(f"Seek failed during single-resume attempt: {e}. Will not retry to avoid restarting from beginning.")
                        # Re-group if needed (best-effort)
                        for s in speakers:
                            if s != coordinator and not s.is_coordinator:
                                try:
                                    s.join(coordinator)
                                except Exception as e:
                                    logger.warning(f"Re-group failed for {s.player_name}: {e}")
                    except Exception as e:
                        logger.error(f"Single resume attempt failed: {e}. Skipping further resume attempts.")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Monitor Error: {e}")
            break
    # After 3 minutes, restore
    logger.info("Azan duration completed. Starting restore process...")
    PLAYBACK_ACTIVE = False
    AZAN_LOCK = False
    # Restore all zones
    for s in speakers:
        snap = SONOS_SNAPSHOT.get(s.uid)
        if snap:
            logger.info(f"Restoring {s.player_name} with snapshot: {snap}")
            try:
                s.volume = snap["volume"]
                logger.info(f"Restored volume to {snap['volume']} for {s.player_name}")
            except Exception as e:
                logger.warning(f"Restore volume failed for {s.player_name}: {e}")
            # Ungroup first
            if s != coordinator:
                try:
                    s.unjoin()
                    logger.info(f"Ungrouped {s.player_name}")
                except Exception as e:
                    logger.warning(f"Ungroup failed for {s.player_name}: {e}")
            # Resume previous music/radio if was playing
            if snap["state"] == "PLAYING" and snap["uri"]:
                # Determine whether the snapped URI is a local audio file served by this app
                # or an external/streaming URI (radio). For streaming URIs we should not
                # attempt to seek back to a saved position because live streams either
                # don't support seeking or seeking would restart the stream.
                uri = snap["uri"] or ''
                is_stream = ('sid=' in uri) or ('/audio/' not in uri)
                if is_stream:
                    logger.info(f"Skipping seek/position restore for streaming URI: {uri} for {s.player_name}")
                    try:
                        # Best-effort: restore the URI so the speaker returns to the same stream
                        s.play_uri(uri)
                        logger.info(f"Restored streaming URI for {s.player_name}: {uri}")
                    except Exception as e:
                        logger.warning(f"Restore streaming URI failed for {s.player_name}: {e}")
                else:
                    logger.info(f"Attempting to resume {uri} at {snap['position']} for {s.player_name}")
                    try:
                        s.play_uri(uri)
                        # Only attempt to seek for local/audio files where stored positions make sense
                        if snap["position"] and snap["position"] != 'NOT_IMPLEMENTED':
                            time.sleep(1)
                            s.seek(snap["position"])
                            logger.info(f"Seeked to {snap['position']} for {s.player_name}")
                        logger.info(f"Resumed playback for {s.player_name}: {uri} at {snap['position']}")
                    except Exception as e:
                        logger.warning(f"Restore playback failed for {s.player_name}: {e}")
            else:
                logger.info(f"No playback to resume for {s.player_name} (state: {snap['state']}, uri: {snap['uri']})")
        else:
            logger.warning(f"No snapshot found for {s.player_name}")
    logger.info("Azan playback and restore completed")
    # Structured play-session end event
    try:
        try:
            tz = get_prayer_tz() or ZoneInfo('UTC')
        except Exception:
            tz = None
        end_event = {
            'event': 'end',
            'session_id': session_id,
            'file': audio_url.split('/')[-1] if audio_url else None,
            'end_ts': (datetime.now(tz).isoformat() if tz is not None else datetime.now().isoformat()),
            'restored': True
        }
        _write_play_session_event(end_event)
    except Exception as e:
        logger.warning(f"Failed to write session end event: {e}")

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    # Optionally start an in-process scheduler. When running a dedicated
    # scheduler service we prefer that service to own the scheduler; set
    # BILAL_RUN_SCHEDULER=0 in the backend unit to disable the in-process
    # scheduler.
    run_scheduler_flag = os.environ.get('BILAL_RUN_SCHEDULER', '1')
    run_scheduler = str(run_scheduler_flag).lower() not in ('0', 'false', 'no')

    if SCHEDULER_AVAILABLE and run_scheduler:
        try:
            # Ensure DB exists for jobstore and play history
            try:
                init_db(DB_PATH)
            except Exception:
                pass
            if globals().get('SQLALCHEMY_AVAILABLE'):
                jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{DB_PATH}')}
                scheduler = BackgroundScheduler(jobstores=jobstores)
                logger.info('APScheduler + SQLAlchemy detected: persistent jobstore enabled')
            else:
                scheduler = BackgroundScheduler()
                logger.info('APScheduler detected but SQLAlchemy not available: using in-memory scheduler (no persistence)')
            scheduler.start()
            logger.info("BackgroundScheduler started")
            # Schedule today's prayers and a daily rescheduler job
            schedule_today_and_rescheduler()
            logger.info(f"Scheduled jobs: {[j.id for j in scheduler.get_jobs()]}")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
    else:
        if not SCHEDULER_AVAILABLE:
            logger.info("Scheduler not available in this environment; automatic scheduling disabled")
            # If we captured import-time errors, log the traceback to help operators
            if globals().get('SCHEDULER_IMPORT_ERROR'):
                logger.warning(f"Scheduler import error (missing dependencies?):\n{globals().get('SCHEDULER_IMPORT_ERROR')}")
        else:
            logger.info("BILAL_RUN_SCHEDULER=0; skipping in-process scheduler startup")

    app.run(host='0.0.0.0', port=5000)

# When running under gunicorn (imported module), __name__ != '__main__'.
# Start the scheduler in exactly one process by using a filesystem lock so
# multiple gunicorn workers do not each start duplicate schedulers.
def _try_start_scheduler_with_lock():
    global scheduler
    LOCK_PATH = '/tmp/bilal_scheduler.lock'
    if not SCHEDULER_AVAILABLE:
        logger.info('Scheduler not available; skipping automatic scheduler start')
        return
    try:
        fd = open(LOCK_PATH, 'w')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info('Another process holds scheduler lock; not starting scheduler in this worker')
            fd.close()
            return
        # We acquired the lock — start the scheduler in this process
        try:
            # Ensure DB exists for jobstore and play history
            try:
                init_db(DB_PATH)
            except Exception:
                pass
            if SQLALCHEMY_AVAILABLE:
                jobstores = {'default': SQLAlchemyJobStore(url=f'sqlite:///{DB_PATH}')}
                scheduler = BackgroundScheduler(jobstores=jobstores)
            else:
                scheduler = BackgroundScheduler()
            scheduler.start()
            logger.info('BackgroundScheduler started (lock owner)')
            schedule_today_and_rescheduler()
            logger.info(f"Scheduled jobs: {[j.id for j in scheduler.get_jobs()]}")
        except Exception as e:
            logger.error(f'Failed to start scheduler under lock: {e}')
    except Exception as e:
        logger.warning(f'Failed to acquire/start scheduler lock: {e}')

# Try to start scheduler now (safe for gunicorn workers)
_try_start_scheduler_with_lock()
