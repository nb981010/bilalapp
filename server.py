import os
import time
import threading
import logging
import socket
import json
import subprocess
from datetime import datetime, date, timedelta
from flask import Flask, send_from_directory, jsonify, request
from subprocess import PIPE, Popen

# Optional scheduler/prayer time imports (installed by install.sh)
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    import praytimes
    from tzlocal import get_localzone
    import fcntl
    SCHEDULER_AVAILABLE = True
except Exception:
    SCHEDULER_AVAILABLE = False

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
    """Discover and return Sonos speakers."""
    logger.info("Starting Sonos speaker discovery")
    try:
        import soco
    except ImportError:
        logger.error("SoCo library not found.")
        return []
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Discovery attempt {attempt+1}/{max_retries}")
            zones = list(soco.discover(timeout=5) or [])
            if zones:
                logger.info(f"Discovered {len(zones)} Sonos speakers: {[z.player_name for z in zones]}")
                return zones
            else:
                logger.warning(f"No Sonos speakers found (attempt {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"Error during Sonos discovery (attempt {attempt+1}): {e}")
    logger.error("Failed to discover any Sonos speakers after all retries")
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
            p = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
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
        tgt = date.today()
        if date_q:
            try:
                tgt = datetime.fromisoformat(date_q).date()
            except Exception:
                pass
        lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
        lon = float(os.environ.get('PRAYER_LON', '55.2708'))
        tz = get_localzone()
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


def _append_play_history(filename, when=None):
    """Append a successful play event to `logs/play_history.json` for later scheduling decisions."""
    try:
        os.makedirs('logs', exist_ok=True)
        path = os.path.join('logs', 'play_history.json')
        entry = {
            'file': filename,
            'ts': (when or datetime.now()).isoformat()
        }
        # Load existing
        data = []
        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception:
            data = []
        data.append(entry)
        # Keep only recent entries (e.g., last 100)
        data = data[-100:]
        with open(path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Failed to append play history: {e}")


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
        # Get coordinates from environment variables if provided, else default to Dubai
        lat = float(os.environ.get('PRAYER_LAT', '25.2048'))
        lon = float(os.environ.get('PRAYER_LON', '55.2708'))
        tz = get_localzone()
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
        # Load recent play history to avoid treating test runs (far from scheduled time) as on-time plays.
        play_history = []
        try:
            with open(os.path.join('logs', 'play_history.json'), 'r') as f:
                play_history = json.load(f)
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
            scheduler.add_job(_http_post_play, trigger=DateTrigger(run_date=scheduled_dt), args=[filename], id=job_id)
            scheduled_count += 1
    except Exception as e:
        logger.error(f"Failed to schedule prayers for {target_date}: {e}")
    return scheduled_count
def schedule_today_and_rescheduler():
    """Schedule today's prayers and a daily rescheduler at 00:05 local time."""
    if not SCHEDULER_AVAILABLE:
        return
    tz = get_localzone()
    today = date.today()

    # Attempt to schedule today's prayers and record how many jobs were added.
    added = schedule_prayers_for_date(today)

    # Helper to schedule the daily rescheduler (next day at 00:05)
    def _schedule_daily_rescheduler():
        try:
            tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time()) + timedelta(minutes=5)
            tomorrow = tomorrow.replace(tzinfo=tz)
            def _resched():
                schedule_prayers_for_date(date.today())
            if 'rescheduler-daily' not in [j.id for j in scheduler.get_jobs()]:
                scheduler.add_job(_resched, trigger=DateTrigger(run_date=tomorrow), id='rescheduler-daily')
                logger.info(f"Scheduled daily rescheduler at {tomorrow}")
        except Exception as e:
            logger.warning(f"Failed to schedule daily rescheduler: {e}")

    # If nothing was scheduled for today (device may have been down at midnight),
    # add a retry job that will attempt to schedule today's prayers until successful.
    # Start with 5-minute retries for the first 6 attempts, then switch to hourly.
    if added == 0:
        try:
            def _try_schedule_missed():
                try:
                    key = date.today().isoformat()
                    MISSED_SCHED_ATTEMPTS[key] = MISSED_SCHED_ATTEMPTS.get(key, 0) + 1
                    attempts = MISSED_SCHED_ATTEMPTS[key]
                    logger.info(f"Missed-scheduler attempt #{attempts} for {key}")
                    cnt = schedule_prayers_for_date(date.today())
                    if cnt > 0:
                        logger.info(f"Missed-scheduler: scheduled {cnt} prayer jobs for today; removing retry job")
                        try:
                            scheduler.remove_job('missed-scheduler')
                        except Exception:
                            pass
                        # After successfully scheduling today's jobs, ensure the daily rescheduler exists
                        _schedule_daily_rescheduler()
                        return
                    # If we've tried 6 times at 5-minute intervals, switch to hourly retries
                    if attempts >= 6:
                        logger.info("Missed-scheduler reached 6 attempts; switching to hourly retries")
                        try:
                            scheduler.remove_job('missed-scheduler')
                        except Exception:
                            pass
                        # Add a new job that runs hourly
                        scheduler.add_job(_try_schedule_missed, trigger=IntervalTrigger(hours=1), id='missed-scheduler')
                        return
                    # Otherwise, continue retrying every 5 minutes (job remains)
                except Exception as e:
                    logger.warning(f"Missed-scheduler attempt failed: {e}")

            if 'missed-scheduler' not in [j.id for j in scheduler.get_jobs()]:
                scheduler.add_job(_try_schedule_missed, trigger=IntervalTrigger(minutes=5), id='missed-scheduler')
                logger.info("Scheduled missed-scheduler job: 5-minute retries (first 6 attempts), then hourly")
        except Exception as e:
            logger.warning(f"Failed to schedule missed-scheduler: {e}")
    else:
        # If we scheduled jobs now, ensure the daily rescheduler is also scheduled
        _schedule_daily_rescheduler()


@app.route('/api/scheduler/jobs', methods=['GET'])
def list_scheduled_jobs():
    """Return a list of scheduled jobs (if scheduler is available)."""
    if not SCHEDULER_AVAILABLE or not scheduler:
        return jsonify({'available': False, 'jobs': []})
    jobs = []
    for j in scheduler.get_jobs():
        jobs.append({'id': j.id, 'next_run_time': str(j.next_run_time)})
    return jsonify({'available': True, 'jobs': jobs})


@app.route('/api/scheduler/force-schedule', methods=['POST'])
def api_force_schedule_today():
    """Force a run of today's scheduling (useful for testing). Returns number of jobs scheduled."""
    if not SCHEDULER_AVAILABLE:
        return jsonify({'available': False, 'jobs_added': 0, 'message': 'Scheduler not available'})
    try:
        added = schedule_prayers_for_date(date.today())
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
        # Return recent history tail
        path = os.path.join('logs', 'play_history.json')
        recent = []
        try:
            with open(path, 'r') as f:
                recent = json.load(f)
        except Exception:
            recent = []
        return jsonify({'status': 'ok', 'appended': {'file': fname, 'ts': when.isoformat()}, 'history_tail': recent[-10:]})
    except Exception as e:
        logger.error(f"simulate-play error: {e}")
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

    try:
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
        threading.Thread(target=monitor_playback, args=(coordinator, speakers, audio_url)).start()

        return jsonify({"status": "success", "message": "Playback Started"})

    except Exception as e:
        logger.error(f"Play Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def monitor_playback(coordinator, speakers, audio_url):
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

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    # Initialize and start scheduler if available
    if SCHEDULER_AVAILABLE:
        try:
            scheduler = BackgroundScheduler()
            scheduler.start()
            logger.info("BackgroundScheduler started")
            # Schedule today's prayers and a daily rescheduler job
            schedule_today_and_rescheduler()
            logger.info(f"Scheduled jobs: {[j.id for j in scheduler.get_jobs()]}")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
    else:
        logger.info("Scheduler not available in this environment; automatic scheduling disabled")

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
