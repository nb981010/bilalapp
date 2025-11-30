#!/opt/bilalapp/.venv/bin/python3
"""Scheduler runner: start APScheduler using the existing server lock logic.

This script imports `server._try_start_scheduler_with_lock` so the same
lock-based leader election is used (safe if the HTTP app is later run under
multiple workers). It then stays alive indefinitely so systemd can manage it.
"""
import time
import sys, os
# Ensure application directory is on sys.path so `from server import ...` works
app_dir = '/opt/bilalapp'
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
# Make sure current working directory is the application dir so relative
# log paths in `server.py` resolve to `/opt/bilalapp/logs/*` when imported.
try:
    os.chdir(app_dir)
except Exception:
    # Best effort; if chdir fails we'll still try to import and surface errors.
    pass
try:
    from server import _try_start_scheduler_with_lock
except Exception as e:
    import sys as _sys
    _sys.stderr.write(f"Failed to import server._try_start_scheduler_with_lock: {e}\n")
    raise


def main():
    # Use the same lock-start helper that's used when running under gunicorn.
    _try_start_scheduler_with_lock()
    # Keep process alive to let scheduler run in this process.
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
