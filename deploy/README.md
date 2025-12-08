Deployment / Hardening notes

1) Systemd service (recommended)

To install the service (requires root):

sudo cp deploy/bilal-server.service /etc/systemd/system/bilal-server.service
sudo systemctl daemon-reload
sudo systemctl enable --now bilal-server.service

Check status:

sudo journalctl -u bilal-server.service -f

2) Cron watchdog (safe fallback)

Install a cron job for the `nbc` user to run the watchdog every 5 minutes:

(crontab -u nbc -l 2>/dev/null; echo "*/5 * * * * /home/nbc/bilalapp/tools/ensure_server_running.sh") | crontab -u nbc -

The watchdog script will try the health endpoint and restart the server via nohup if it's not responding.

3) Why this change

Root cause: the rescheduler cron ran at local 00:15 but the wrapper used `datetime.utcnow()` as the target date. When local timezone != UTC this produced the previous UTC date and the scheduler skipped adding jobs (they appeared in the past relative to UTC). Result: no azan jobs for the local day were scheduled.

Fix: `schedule_today_jobs_wrapper` now computes the target date using the local timezone (via `tzlocal` when available, or ZoneInfo('Asia/Dubai') fallback), ensuring the daily rescheduler always creates jobs for the intended local date.

Additionally: adding a systemd unit and a lightweight watchdog ensure the server stays running and will be restarted automatically if it crashes or the process is killed.

4) Next steps (optional)
- Consider running the service under a proper process manager (systemd as above) and removing the nohup-based startup from any other scripts.
- Add more robust health checks (e.g., check playback functionality) and alerting (email/Slack) for failures.

5) Ensure dependencies are installed (important)

It's critical the Python environment has `apscheduler` and `SQLAlchemy` available, otherwise the server will start in a degraded mode (non-persistent scheduler). Recommended steps:

```bash
# create a venv (one-time)
python3 -m venv /home/nbc/bilalapp/.venv
source /home/nbc/bilalapp/.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.TXT
```

Then edit `/etc/systemd/system/bilal-server.service` ExecStart to use the venv python, for example:

```
ExecStart=/home/nbc/bilalapp/.venv/bin/python /home/nbc/bilalapp/server.py
```

Reload and restart systemd after editing service file:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bilal-server.service
sudo systemctl enable bilal-server.service
```
