#!/usr/bin/env python3
"""Print today's Azan schedule status by reading the APScheduler DB, bilal.sqlite and logs.

Usage: python scripts/whatsup.py

For status reporting it preferentially reads from bilal.sqlite (prayer_schedule,
played_markers, play_history tables).  Falls back to APScheduler DB + log parsing
when bilal.sqlite is not yet populated.
"""
from __future__ import annotations
import os
import re
import sqlite3
import sys
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

RE_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - .* - (?:INFO|WARNING|ERROR) - (.*)$")


def read_bilal_schedule(bilal_db: str, date_str: str) -> dict:
    """Read prayer scheduled times from bilal.sqlite prayer_schedule table.
    Returns {prayer: datetime_utc}.
    """
    if not os.path.exists(bilal_db):
        return {}
    try:
        conn = sqlite3.connect(bilal_db)
        rows = conn.execute(
            "SELECT prayer, scheduled_utc FROM prayer_schedule WHERE date = ?",
            (date_str,)
        ).fetchall()
        conn.close()
        jobs = {}
        for prayer, utc_str in rows:
            try:
                dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
                jobs[prayer] = dt
            except Exception:
                pass
        return jobs
    except Exception:
        return {}


def read_bilal_outcomes(bilal_db: str, date_str: str) -> dict:
    """Read play outcomes from bilal.sqlite play_history for a given date.
    Returns {prayer: {'status': ..., 'ts': ..., 'message': ...}}.
    """
    if not os.path.exists(bilal_db):
        return {}
    try:
        conn = sqlite3.connect(bilal_db)
        rows = conn.execute(
            "SELECT prayer, ts, status, zones_played, zones_total, message "
            "FROM play_history WHERE date(ts) = ? ORDER BY ts ASC",
            (date_str,)
        ).fetchall()
        conn.close()
        out = {}
        for prayer, ts, status, zp, zt, msg in rows:
            if prayer:
                out[prayer.lower()] = {'status': status, 'ts': ts,
                                       'zones_played': zp, 'zones_total': zt,
                                       'message': msg}
        return out
    except Exception:
        return {}


def read_db_jobs(db_path: str, date_str: str):
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    q = "SELECT id, next_run_time, job_state FROM apscheduler_jobs WHERE id LIKE ?"
    pattern = f'azan_job_{date_str}%_play'
    rows = cur.execute(q, (pattern,)).fetchall()
    jobs = {}
    for id_, nrt, state in rows:
        # id format: azan_job_YYYY-MM-DD_<prayer>_play
        parts = id_.split('_')
        # prayer usually at position -2 (before 'play')
        if len(parts) >= 4:
            prayer = parts[-2]
        else:
            prayer = id_
        jobs[prayer] = float(nrt) if nrt is not None else None
    conn.close()
    return jobs


def read_logs(log_paths):
    lines = []
    for p in log_paths:
        if not os.path.exists(p):
            continue
        with open(p, 'r', encoding='utf-8', errors='replace') as fh:
            for ln in fh:
                m = RE_LOG_LINE.match(ln.strip())
                if m:
                    ts_text, msg = m.groups()
                    # parse timestamp like 2025-12-05 00:15:00,021
                    try:
                        ts = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S,%f")
                    except Exception:
                        ts = None
                    lines.append((ts, msg.strip(), ln.strip()))
    return lines


def find_events_for_prayer(lines, prayer, scheduled_dt=None):
    """Find start/end events for a prayer but only consider log entries on the
    scheduled date (if provided) to avoid matching older runs.
    """
    start = None
    end = None

    # Determine the target date for matching
    target_date = None
    if scheduled_dt is not None:
        try:
            target_date = scheduled_dt.date()
        except Exception:
            target_date = None
    else:
        target_date = datetime.now().date()

    # Primary match: play_from_job START log from server.py, e.g.
    #   "[abc12345] play_from_job START: file=azan.mp3 prayer=asr force=False"
    # Also match legacy "play job for" patterns.
    for ts, msg, raw in lines:
        if ts is None:
            continue
        if target_date and ts.date() != target_date:
            continue
        low = msg.lower()
        if (
            ('play_from_job start' in low and f'prayer={prayer}' in low)
            or f'play job for {prayer}' in low
            or f"play job for '{prayer}'" in low
        ):
            start = ts
            break

    # Fallback 1: APScheduler "Running job" for the matching azan job id.
    if start is None and target_date is not None:
        date_str = target_date.isoformat()
        window = timedelta(minutes=10)
        for ts, msg, raw in lines:
            if ts is None:
                continue
            if ts.date() != target_date:
                continue
            low = msg.lower()
            if 'running job' in low and f'azan-{date_str}-{prayer}' in low:
                start = ts
                break

    # Fallback 2: legacy 'starting playback' within +-10 min of scheduled time.
    if start is None and scheduled_dt is not None:
        window = timedelta(minutes=10)
        for ts, msg, raw in lines:
            if ts is None:
                continue
            if target_date and ts.date() != target_date:
                continue
            low = msg.lower()
            if 'starting playback' in low or 'starting playback on' in low:
                if abs(ts - scheduled_dt) <= window:
                    start = ts
                    break

    # Find end: first success/failure log after start on the same date.
    # Covers server.py: 'play success', 'playback failed', 'no speakers discovered'
    # and legacy: 'playback finished', 'playback stopped'.
    if start is not None:
        for ts, msg, raw in lines:
            if ts is None:
                continue
            if ts <= start:
                continue
            if target_date and ts.date() != target_date:
                continue
            low = msg.lower()
            if (
                'play success' in low
                or 'playback failed' in low
                or 'no speakers discovered' in low
                or 'playback finished' in low
                or 'playback stopped' in low
            ):
                end = ts
                break

    return start, end


def format_duration(delta: timedelta | None) -> str:
    if delta is None:
        return ''
    total_seconds = int(delta.total_seconds())
    ms = int(delta.microseconds / 1000)
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def main():
    parser = argparse.ArgumentParser(description='Show Azan play status for past N days')
    parser.add_argument('--days', type=int, default=2, help='Number of days to report (including today)')
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    bilal_db  = os.path.join(repo_root, 'bilal.sqlite')      # application DB (new)
    aps_db    = os.path.join(repo_root, 'jobs.sqlite')        # APScheduler DB (fallback)
    legacy_db = os.path.join(repo_root, 'apscheduler_jobs.sqlite')

    # read logs once (used as fallback when bilal.sqlite has no data yet)
    log_paths = [os.path.join(repo_root, 'logs', 'out.log'),
                 os.path.join(repo_root, 'logs', 'sys.log')]
    lines = read_logs(log_paths)

    prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

    print("Date\tPrayer\tScheduled (UTC)\tPlayed (UTC)\tStatus\tZones\tDetails")

    today = datetime.now().date()
    for delta_days in range(0, args.days):
        target_date = today - timedelta(days=delta_days)
        date_str = target_date.isoformat()

        # --- Scheduled times: prefer bilal.sqlite, fall back to APScheduler DB ---
        schedule = read_bilal_schedule(bilal_db, date_str)
        if not schedule:
            # Fall back to APScheduler job store
            aps_path = aps_db if os.path.exists(aps_db) else (legacy_db if os.path.exists(legacy_db) else None)
            if aps_path:
                try:
                    raw_jobs = read_db_jobs(aps_path, date_str)
                    for p, epoch in raw_jobs.items():
                        if epoch:
                            schedule[p] = datetime.fromtimestamp(epoch, tz=timezone.utc)
                except Exception:
                    pass

        # --- Outcomes: prefer bilal.sqlite play_history ---
        outcomes = read_bilal_outcomes(bilal_db, date_str)

        for p in prayers:
            scheduled_dt = schedule.get(p)
            scheduled_s = scheduled_dt.strftime('%H:%M:%S') if scheduled_dt else ''

            outcome = outcomes.get(p)
            if outcome:
                status_raw  = outcome.get('status') or 'unknown'
                ts_str      = outcome.get('ts') or ''
                zones_p     = outcome.get('zones_played')
                zones_t     = outcome.get('zones_total')
                msg         = outcome.get('message') or ''

                # Parse played timestamp
                played_s = ''
                try:
                    played_dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    played_s  = played_dt.strftime('%H:%M:%S')
                except Exception:
                    played_s = ts_str[:19] if ts_str else ''

                zones_s = f"{zones_p}/{zones_t}" if zones_p is not None else ''

                if status_raw == 'success':
                    status_label = 'Success'
                elif status_raw == 'no_speakers':
                    status_label = 'Failure (no speakers)'
                elif status_raw == 'error':
                    status_label = f'Failure ({msg[:40]})' if msg else 'Failure'
                elif status_raw == 'skipped':
                    status_label = 'Skipped (already played)'
                else:
                    status_label = status_raw

                print(f"{date_str}\t{p.capitalize()}\t{scheduled_s}\t{played_s}\t{status_label}\t{zones_s}\t{msg[:60]}")
            else:
                # Fall back to log-based detection
                start, end = find_events_for_prayer(lines, p, scheduled_dt)
                if start and end:
                    status_label = 'Success (log)'
                    played_s = start.strftime('%H:%M:%S')
                elif start:
                    status_label = 'Started (log)'
                    played_s = start.strftime('%H:%M:%S')
                else:
                    status_label = 'Failure' if scheduled_dt and scheduled_dt < datetime.now(timezone.utc) else 'Pending'
                    played_s = ''
                print(f"{date_str}\t{p.capitalize()}\t{scheduled_s}\t{played_s}\t{status_label}\t\t")


if __name__ == '__main__':
    main()
