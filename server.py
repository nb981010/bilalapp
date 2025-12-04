import os
import time
import threading
import logging
import socket
from datetime import datetime

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
            if not SCHEDULER.get_job('azan_job_daily_reschedule'):
                # run daily at 00:05 local time to recompute next day's jobs
                SCHEDULER.add_job(schedule_daily_reschedule, 'cron', hour=0, minute=5, id='azan_job_daily_reschedule', name='schedule_daily_reschedule')
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
            if not SCHEDULER.get_job('azan_job_daily_reschedule'):
                SCHEDULER.add_job(schedule_daily_reschedule, 'cron', hour=0, minute=5, id='azan_job_daily_reschedule', name='schedule_daily_reschedule')
        except Exception:
            pass

    except Exception as e:
        logger.exception('schedule_daily_reschedule failed: %s', e)

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
    """Return a JSON list of scheduled jobs."""
    if SCHEDULER is None:
        # Try to initialize if possible
        init_scheduler()
    try:
        jobs = []
        if SCHEDULER is None:
            return jsonify([])
        for j in SCHEDULER.get_jobs():
            nrt = None
            if j.next_run_time:
                try:
                    nrt = j.next_run_time.isoformat()
                except Exception:
                    nrt = str(j.next_run_time)
            jobs.append({
                'id': j.id,
                'name': j.name,
                'next_run_time': nrt,
                'trigger': type(j.trigger).__name__,
                'func_ref': f"{j.func.__module__}:{j.func.__name__}" if hasattr(j, 'func') else None
            })
        return jsonify(jobs)
    except Exception as e:
        logger.exception('api_scheduler_jobs error: %s', e)
        return jsonify([]), 500


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
        speakers = get_sonos_speakers()
        if not speakers:
            logger.warning('No speakers found for scheduled play')
            return
        coordinator = speakers[0]
        local_ip = get_local_ip()
        audio_url = f"http://{local_ip}:5000/audio/{file}"
        start_playback(audio_url, coordinator)
    except Exception as e:
        logger.exception('Play job failed: %s', e)

if __name__ == '__main__':
    logger.info("Server Starting on Port 5000...")
    # Initialize scheduler (will load jobs from jobstore if present)
    try:
        init_scheduler()
    except Exception:
        logger.exception('Scheduler init failed')

    app.run(host='0.0.0.0', port=5000)
