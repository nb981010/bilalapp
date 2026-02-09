#!/usr/bin/env python3
"""Print today's Azan schedule status by reading the APScheduler DB and logs.

Usage: python scripts/whatsup.py

Looks for jobs in `apscheduler_jobs.sqlite` with ids like
`azan_job_YYYY-MM-DD_<prayer>_play` and extracts scheduled times.
Then scans `logs/out.log` and `logs/sys.log` to find start/end log timestamps
for each prayer and prints a compact table.
"""
from __future__ import annotations
import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
import json
import sys
import argparse


RE_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - .* - (?:INFO|WARNING|ERROR) - (.*)$")


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

    # prefer exact match with prayer in message, but only on target_date
    for ts, msg, raw in lines:
        if ts is None:
            continue
        if target_date and ts.date() != target_date:
            continue
        low = msg.lower()
        if f"play job for {prayer}" in low or f"play job for '{prayer}'" in low:
            start = ts
            break

    # fallback: find 'Starting playback' within +- 10 minutes of scheduled_dt on same date
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

    # find end: first 'Playback finished' after start on same date
    if start is not None:
        for ts, msg, raw in lines:
            if ts is None:
                continue
            if ts <= start:
                continue
            if target_date and ts.date() != target_date:
                continue
            low = msg.lower()
            if 'playback finished' in low or 'playback stopped' in low:
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
    db_path = os.path.join(repo_root, 'apscheduler_jobs.sqlite')
    db_path = os.path.abspath(db_path)

    # read logs once
    log_paths = [os.path.join(repo_root, 'logs', 'out.log'), os.path.join(repo_root, 'logs', 'sys.log')]
    lines = read_logs(log_paths)

    prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

    # Print header
    print("Date\tPrayer\tStart (log)\tEnd (log)\tDuration\tStatus")

    today = datetime.now().date()
    for delta_days in range(0, args.days):
        target_date = today - timedelta(days=delta_days)
        date_str = target_date.isoformat()

        # read persisted play jobs for the date
        try:
            jobs = read_db_jobs(db_path, date_str)
        except FileNotFoundError:
            # No DB available; fall back to log-only detection
            jobs = {}
            if delta_days == 0:
                # only print notice once (for today)
                print(f"apscheduler DB not found at {db_path}; falling back to logs")

        for p in prayers:
            scheduled_epoch = jobs.get(p)
            scheduled_dt = None
            if scheduled_epoch:
                try:
                    scheduled_dt = datetime.fromtimestamp(scheduled_epoch)
                except Exception:
                    scheduled_dt = None

            start, end = find_events_for_prayer(lines, p, scheduled_dt)
            if start and end:
                duration = end - start
                status = 'Success'
            elif start and not end:
                duration = None
                status = 'Started'
            else:
                duration = None
                status = 'Failure'

            start_s = start.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if start else ''
            end_s = end.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if end else ''
            dur_s = format_duration(duration)
            print(f"{date_str}\t{p.capitalize()}\t{start_s}\t{end_s}\t{dur_s}\t{status}")


if __name__ == '__main__':
    main()
