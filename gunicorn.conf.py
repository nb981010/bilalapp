"""
Gunicorn configuration for Bilal Azan Server.

Key concerns addressed here:
- APScheduler must run in the *worker* process, not in the gunicorn arbiter.
  With --preload the app module is loaded once by the arbiter before forking.
  Threads do not survive a fork, so any scheduler started in the arbiter would
  be dead in the worker.  We therefore defer all scheduler initialisation to
  the post_fork hook below.
- A single worker is used to avoid multiple concurrent APScheduler instances
  fighting over the SQLite job-store and duplicating Azan playback.
"""

import logging

workers = 1
bind = "0.0.0.0:5000"
timeout = 120
preload_app = True  # load app once in arbiter; workers inherit without re-importing

_log = logging.getLogger("gunicorn.error")


def post_fork(server, worker):
    """Initialise the APScheduler in the worker process after the fork.

    The arbiter loaded the module (running the module-level else: block) but
    we deliberately skipped scheduler startup there.  Here we reset the global
    state and start the scheduler cleanly inside the worker.
    """
    try:
        import server as bilal_server  # noqa: F811 – intentional shadow

        # Reset so init_scheduler treats this worker as a fresh start.
        bilal_server._scheduler_initialized = False
        bilal_server.SCHEDULER = None

        bilal_server._init_scheduler_background()
        server.log.info(f"[gunicorn post_fork] Scheduler init triggered for worker {worker.pid}")
    except Exception as exc:
        server.log.error(f"[gunicorn post_fork] Scheduler init failed: {exc}")


def worker_exit(server, worker):
    """Cleanly shut down the scheduler when a worker exits."""
    try:
        import server as bilal_server  # noqa: F811

        if bilal_server.SCHEDULER and bilal_server.SCHEDULER.running:
            bilal_server.SCHEDULER.shutdown(wait=False)
            server.log.info(f"[gunicorn worker_exit] Scheduler shut down for worker {worker.pid}")
    except Exception as exc:
        server.log.error(f"[gunicorn worker_exit] Scheduler shutdown failed: {exc}")
