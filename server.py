import os
import time
import threading
import logging
import socket
import json
from datetime import datetime, date, timedelta
import subprocess
import shlex
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from flask import Flask, send_from_directory, jsonify, request

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'sys.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BilalServer")

app = Flask(__name__, static_folder='.')

# Global State
SONOS_GROUPS = {}  # Store group snapshots
PLAYBACK_ACTIVE = False
PLAY_SESSIONS_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'play_sessions.log')
# Current play metadata for watchdog
CURRENT_PLAY = None
# default timeout (seconds) after which we force-stop if playback hasn't ended
PLAYBACK_TIMEOUT_SECONDS = int(os.environ.get('BILAL_PLAYBACK_TIMEOUT', '180'))
DB_PATH = os.path.join(os.path.dirname(__file__), 'play_sessions.db')
PLAY_DURATION_MARGIN = int(os.environ.get('BILAL_PLAYBACK_MARGIN', '10'))  # seconds to add to mp3 duration
ALERT_ON_FORCED_STOP = os.environ.get('BILAL_ALERT_ON_FORCED_STOP', 'false').lower() in ('1','true','yes')

import sqlite3


def _init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                event TEXT,
                prayer TEXT,
                job_id TEXT,
                file TEXT,
                coordinator TEXT,
                coordinator_name TEXT,
                details TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to init DB: {e}")


def _db_write_session(entry: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('''INSERT INTO sessions (timestamp,event,prayer,job_id,file,coordinator,coordinator_name,details) VALUES (?,?,?,?,?,?,?,?)''', (
            entry.get('timestamp'), entry.get('event'), entry.get('prayer'), entry.get('job_id'), entry.get('file'), entry.get('coordinator'), entry.get('coordinator_name'), json.dumps(entry)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to write session to DB: {e}")

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


def _write_play_session_event(event_type: str, payload: dict):
    """Append a JSON line to play_sessions.log with timestamp and event type."""
    try:
        os.makedirs(os.path.dirname(PLAY_SESSIONS_LOG), exist_ok=True)
        entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'event': event_type,
            **payload
        }
        with open(PLAY_SESSIONS_LOG, 'a') as fh:
            fh.write(json.dumps(entry) + "\n")
        # persist to sqlite as well
        try:
            _db_write_session(entry)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Failed to write play session event: {e}")

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
    data = request.json or {}
    filename = data.get('file', 'azan.mp3')
    prayer = data.get('prayer')
    job_id = data.get('job_id')

    logger.info(f"Received Play Request: {filename} (prayer={prayer} job_id={job_id})")

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
        
        # Structured play-start event and watchdog metadata
        try:
            _write_play_session_event('play_start', {
                'file': filename,
                'prayer': prayer,
                'job_id': job_id,
                'coordinator': coordinator.uid,
                'coordinator_name': coordinator.player_name,
                'audio_url': audio_url
            })
        except Exception:
            pass

        # set watchdog metadata
        try:
            global CURRENT_PLAY
            CURRENT_PLAY = {
                'file': filename,
                'prayer': prayer,
                'job_id': job_id,
                'audio_url': audio_url,
                'start_ts': time.time(),
                'timeout': PLAYBACK_TIMEOUT_SECONDS
            }
        except Exception:
            pass
        # if possible, determine exact duration of the file and adjust timeout (A)
        try:
            from mutagen.mp3 import MP3
            audio_path = os.path.join(os.path.dirname(__file__), 'audio', filename)
            if os.path.exists(audio_path):
                audio = MP3(audio_path)
                duration = int(audio.info.length)
                margin = PLAY_DURATION_MARGIN
                CURRENT_PLAY['timeout'] = duration + margin
                logger.info(f"Set playback timeout to {CURRENT_PLAY['timeout']}s based on file duration {duration}s plus margin {margin}s")
        except Exception:
            pass
        # Set Volume (Optional: Set standard volume for Azan)
        try:
            coordinator.group.volume = 45
        except:
            pass

        # Play
        coordinator.play_uri(audio_url)
        
        # Start Monitoring Thread
        PLAYBACK_ACTIVE = True
        threading.Thread(target=monitor_playback, args=(coordinator,)).start()

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
            # If playback finished for this coordinator, record and restore
            if state != 'PLAYING' and state != 'TRANSITIONING':
                logger.info(f"Playback finished (State: {state}). Restoring...")
                # Structured play-end event
                try:
                    _write_play_session_event('play_end', {
                        'coordinator': coordinator.uid,
                        'coordinator_name': coordinator.player_name,
                        'state': state
                    })
                except Exception:
                    pass
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
        # Additional watchdog: if we exceeded expected timeout and current play still references our audio, force stop
        try:
            global CURRENT_PLAY
            if CURRENT_PLAY is not None:
                elapsed = time.time() - CURRENT_PLAY.get('start_ts', 0)
                timeout = int(CURRENT_PLAY.get('timeout', PLAYBACK_TIMEOUT_SECONDS))
                if elapsed > timeout:
                    # try to determine if coordinator is still playing our file
                    try:
                        track_info = {}
                        try:
                            track_info = coordinator.get_current_track_info() or {}
                        except Exception:
                            pass

                        uri = track_info.get('uri') or ''
                        # simple heuristic: check if our audio filename is in the current uri
                        if CURRENT_PLAY.get('audio_url') and (CURRENT_PLAY['audio_url'].split('/')[-1] in uri or CURRENT_PLAY['file'] in uri or CURRENT_PLAY['audio_url'] in uri):
                            logger.warning(f"Playback exceeded timeout ({timeout}s). Forcing stop for {CURRENT_PLAY.get('file')}")
                            _write_play_session_event('play_forced_stop', {'coordinator': coordinator.uid, 'coordinator_name': coordinator.player_name, 'reason': 'timeout'})
                            try:
                                coordinator.stop()
                            except Exception:
                                pass
                            try:
                                for s in coordinator.group.members:
                                    if s != coordinator:
                                        try:
                                            s.unjoin()
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                            PLAYBACK_ACTIVE = False
                            CURRENT_PLAY = None
                            break
                        else:
                            # If we couldn't find uri info but elapsed significantly exceeds timeout, force stop anyway (aggressive D)
                            if elapsed > (timeout + 30):
                                logger.warning(f"Playback significantly exceeded timeout (> {timeout+30}s). Forcing stop without URI match.")
                                _write_play_session_event('play_forced_stop', {'coordinator': coordinator.uid, 'coordinator_name': coordinator.player_name, 'reason': 'timeout_no_uri_match'})
                                try:
                                    coordinator.stop()
                                except Exception:
                                    pass
                                try:
                                    for s in coordinator.group.members:
                                        if s != coordinator:
                                            try:
                                                s.unjoin()
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                PLAYBACK_ACTIVE = False
                                CURRENT_PLAY = None
                                break
                    except Exception:
                        pass
        except Exception:
            pass

        time.sleep(3) # Check every 3 seconds


# ------------------------------
# Prayer times endpoint (compute with Node/Adhan script)
# ------------------------------

def _compute_with_node(d: date):
    """Fallback: invoke the repository Node script which uses Adhan to compute times."""
    node = None
    for p in ("/usr/bin/node", "/usr/local/bin/node", "node"):
        try:
            which = subprocess.run([p, "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if which.returncode == 0:
                node = p
                break
        except Exception:
            continue
    if node is None:
        raise RuntimeError("node not found for computing prayer times")

    script = os.path.join(os.path.dirname(__file__), 'scripts', 'compute_prayer_times.mjs')
    cmd = [node, script, d.isoformat()]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Node script failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


# ------------------------------
# Scheduler: compute prayer times and schedule prepare/play jobs
# ------------------------------
JOBSTORE_DB = os.path.join(os.path.dirname(__file__), 'apscheduler_jobs.sqlite')
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{JOBSTORE_DB}')
}

# Create scheduler using persistent job store
scheduler = BackgroundScheduler(jobstores=jobstores)
_SCHEDULE_JOB_PREFIX = 'azan_job_'


def _run_prepare_job(prayer_key: str, prayer_name: str):
    logger.info(f"Running scheduled PREPARE for {prayer_name} ({prayer_key})")
    try:
        with app.test_request_context('/api/prepare', method='GET'):
            prepare_group()
    except Exception as e:
        logger.error(f"Error running PREPARE for {prayer_name}: {e}")


def _run_play_job(prayer_key: str, prayer_name: str, job_id: str = None, filename: str = 'azan.mp3'):
    logger.info(f"Running scheduled PLAY for {prayer_name} ({prayer_key})")
    try:
        payload = {'file': filename, 'prayer': prayer_name, 'job_id': job_id}
        with app.test_request_context('/api/play', method='POST', json=payload):
            play_audio()
    except Exception as e:
        logger.error(f"Error running PLAY for {prayer_name}: {e}")


def _schedule_jobs_for_date(d: date):
    try:
        times = _compute_with_node(d)
    except Exception as e:
        logger.error(f"Failed to compute prayer times for {d}: {e}")
        return

    prayer_keys = [('fajr','Fajr'), ('dhuhr','Dhuhr'), ('asr','Asr'), ('maghrib','Maghrib'), ('isha','Isha')]
    now = datetime.now()

    for key, name in prayer_keys:
        tstr = times.get(key)
        if not tstr:
            continue
        try:
            hh, mm = [int(x) for x in tstr.split(':')]
        except Exception:
            logger.warning(f"Invalid time format for {key} on {d}: {tstr}")
            continue

        dt = datetime(d.year, d.month, d.day, hh, mm)

        # Schedule PREPARE 1 minute before
        prep_dt = dt - timedelta(minutes=1)
        if prep_dt > now:
            job_id = f"{_SCHEDULE_JOB_PREFIX}{d.isoformat()}_{key}_prepare"
            try:
                scheduler.add_job('server:_run_prepare_job', args=[key, name], trigger=DateTrigger(run_date=prep_dt), id=job_id, replace_existing=True)
                logger.info(f"Scheduled PREPARE for {name} at {prep_dt}")
            except Exception as e:
                logger.error(f"Failed to schedule prepare job {job_id}: {e}")

        # Schedule PLAY at the prayer time
        if dt > now:
            job_id = f"{_SCHEDULE_JOB_PREFIX}{d.isoformat()}_{key}_play"
            try:
                scheduler.add_job('server:_run_play_job', args=[key, name, job_id, 'azan.mp3'], trigger=DateTrigger(run_date=dt), id=job_id, replace_existing=True)
                logger.info(f"Scheduled PLAY for {name} at {dt}")
            except Exception as e:
                logger.error(f"Failed to schedule play job {job_id}: {e}")


def schedule_startup_jobs():
    # Do not remove persisted jobs from the job store on startup.
    # Instead, ensure today's and tomorrow's jobs exist (idempotent via replace_existing=True).
    today = date.today()
    tomorrow = today + timedelta(days=1)
    _schedule_jobs_for_date(today)
    _schedule_jobs_for_date(tomorrow)
    schedule_daily_reschedule()

    try:
        # Use a module-level callable so the jobstore can serialize the reference.
        scheduler.add_job('server:schedule_daily_reschedule', 'cron', hour=0, minute=5, id=f"{_SCHEDULE_JOB_PREFIX}daily_reschedule", replace_existing=True)
    except Exception as e:
        logger.error(f"Failed to add daily reschedule job: {e}")
def schedule_daily_reschedule():
    """Helper run by a daily cron job (module-level so it can be serialized).
    Ensures today's and tomorrow's jobs are scheduled (idempotent).
    """
    try:
        today = date.today()
        _schedule_jobs_for_date(today)
        _schedule_jobs_for_date(today + timedelta(days=1))
    except Exception as e:
        logger.error(f"Daily reschedule failed: {e}")


@app.route('/api/prayertimes', methods=['GET'])
def api_prayertimes():
    """Return prayer times for a given date. Query param `date=YYYY-MM-DD` (optional, defaults to today)."""
    date_str = request.args.get('date')
    try:
        if date_str:
            parts = [int(p) for p in date_str.split('-')]
            d = date(parts[0], parts[1], parts[2])
        else:
            d = date.today()

        out = _compute_with_node(d)
        return jsonify(out)
    except Exception as e:
        logger.error(f"/api/prayertimes error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/scheduler/jobs', methods=['GET'])
def api_scheduler_jobs():
    """Return list of scheduled APScheduler jobs with next run times (debug endpoint)."""
    try:
        jobs_out = []
        for job in scheduler.get_jobs():
            try:
                nxt = getattr(job, 'next_run_time', None)
                # nxt may already be ISO string in some jobstores; handle both
                if hasattr(nxt, 'isoformat'):
                    nxt_val = nxt.isoformat()
                else:
                    nxt_val = str(nxt) if nxt is not None else None
                trig = None
                try:
                    trig = type(job.trigger).__name__
                except Exception:
                    trig = None

                jobs_out.append({
                    'id': getattr(job, 'id', None),
                    'name': getattr(job, 'name', None),
                    'func_ref': getattr(job, 'func_ref', None),
                    'next_run_time': nxt_val,
                    'trigger': trig
                })
            except Exception:
                # Fallback for unexpected job object shapes
                jobs_out.append({'id': str(job), 'raw': repr(job)})
        return jsonify(jobs_out)
    except Exception as e:
        logger.error(f"/api/scheduler/jobs error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/transport', methods=['GET'])
def api_transport():
    """Return detailed transport/player state for discovered Sonos speakers."""
    try:
        speakers = get_sonos_speakers()
        out = []
        for s in speakers:
            info = {}
            try:
                info = s.get_current_transport_info() or {}
            except Exception:
                info = {}

            group = None
            members = []
            try:
                if s.group and hasattr(s.group, 'members'):
                    group = s.group.coordinator.player_name if hasattr(s.group, 'coordinator') else None
                    for m in s.group.members:
                        members.append({'uid': m.uid, 'name': m.player_name})
            except Exception:
                pass

            out.append({
                'id': s.uid,
                'name': s.player_name,
                'volume': getattr(s, 'volume', None),
                'transport': info,
                'group_coordinator': group,
                'group_members': members
            })

        return jsonify(out)
    except Exception as e:
        logger.error(f"/api/transport error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/play_sessions', methods=['GET'])
def api_play_sessions():
    """Return recent play session events from the sqlite DB (or log file) as JSON. Query param `limit`."""
    try:
        limit = int(request.args.get('limit', '50'))
        # Read from sqlite if available
        rows = []
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute('SELECT id,timestamp,event,prayer,job_id,file,coordinator,coordinator_name,details FROM sessions ORDER BY id DESC LIMIT ?', (limit,))
            for r in cur.fetchall():
                try:
                    details = json.loads(r[8]) if r[8] else {}
                except Exception:
                    details = {}
                rows.append({
                    'id': r[0], 'timestamp': r[1], 'event': r[2], 'prayer': r[3], 'job_id': r[4], 'file': r[5], 'coordinator': r[6], 'coordinator_name': r[7], 'details': details
                })
            conn.close()
            return jsonify(rows)
        except Exception as e:
            logger.error(f"DB read failed: {e}. Falling back to log file.")
            # fall back to reading log file
            out = []
            if os.path.exists(PLAY_SESSIONS_LOG):
                with open(PLAY_SESSIONS_LOG, 'r') as fh:
                    lines = fh.readlines()[-limit:]
                    for line in reversed(lines):
                        try:
                            out.append(json.loads(line))
                        except Exception:
                            continue
            return jsonify(out)

    except Exception as e:
        logger.error(f"/api/play_sessions error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/transport/stop', methods=['POST'])
def api_transport_stop():
    """Stop playback on coordinator and optionally unjoin members. POST JSON: {"coordinator_id":"UID", "unjoin": true}
    If coordinator_id is omitted we attempt to pick the first playing coordinator."""
    data = request.json or {}
    coordinator_id = data.get('coordinator_id')
    unjoin = bool(data.get('unjoin', True))

    try:
        speakers = get_sonos_speakers()
        if not speakers:
            return jsonify({'status': 'error', 'message': 'No speakers found'}), 404

        coord = None
        if coordinator_id:
            for s in speakers:
                if s.uid == coordinator_id:
                    coord = s
                    break
        else:
            # pick first speaker that reports PLAYING or has group members
            for s in speakers:
                try:
                    info = s.get_current_transport_info()
                    state = info.get('current_transport_state')
                    if state == 'PLAYING' or (hasattr(s, 'group') and getattr(s.group, 'members', None)):
                        coord = s
                        break
                except Exception:
                    continue

        if not coord:
            coord = speakers[0]

        # Stop playback
        try:
            coord.stop()
        except Exception as e:
            logger.warning(f"Failed to stop on {coord.player_name}: {e}")

        # Optionally unjoin members
        if unjoin:
            try:
                for m in getattr(coord.group, 'members', []):
                    if m.uid != coord.uid:
                        try:
                            m.unjoin()
                        except Exception:
                            pass
            except Exception:
                pass

        # Log structured event
        try:
            evt = {'coordinator': coord.uid, 'coordinator_name': coord.player_name, 'unjoin': unjoin}
            _write_play_session_event('manual_stop', evt)
        except Exception:
            pass

        return jsonify({'status': 'success', 'coordinator': coord.player_name, 'unjoin': unjoin})

    except Exception as e:
        logger.error(f"/api/transport/stop error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    try:
        # Schedule today's and tomorrow's jobs and start the scheduler
        # initialize DB for session persistence
        _init_db()
        schedule_startup_jobs()
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Scheduler failed to start: {e}")

    app.run(host='0.0.0.0', port=5000)
