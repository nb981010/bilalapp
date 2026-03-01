"""
db.py — Central SQLite persistence for Bilal Azan Server.

All application data (play history, played-today dedup markers, and
prayer schedule) lives in ``bilal.sqlite`` next to the project root.
APScheduler continues to use ``jobs.sqlite`` for its own job store.

Tables
------
prayer_schedule   Scheduled prayer times by date/prayer (one row per day/prayer).
play_history      Every individualplayback attempt with result & metadata.
played_markers    Dedup guard: one row per (date, prayer) to prevent double-plays.

Usage
-----
    import db
    db.init_db()                             # idempotent – call at app startup
    db.upsert_prayer_schedule(date_str, prayer, utc_iso, job_id)
    db.record_play(prayer=prayer, file=file, correlation_id=cid, status='success')
    db.mark_played(prayer)
    db.has_played_today(prayer)  -> bool
    db.get_played_markers(days=1) -> list[dict]
    db.get_play_history(days=7)   -> list[dict]
    db.get_prayer_schedule(date_str) -> list[dict]
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "bilal.sqlite")

# -----------------------------------------------------------------
# Schema
# -----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prayer_schedule (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,           -- YYYY-MM-DD (local)
    prayer       TEXT    NOT NULL,           -- fajr/dhuhr/asr/maghrib/isha
    scheduled_utc TEXT   NOT NULL,           -- ISO-8601 UTC
    job_id       TEXT,                       -- APScheduler job id
    created_at   TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(date, prayer)
);
CREATE INDEX IF NOT EXISTS idx_ps_date    ON prayer_schedule(date);

CREATE TABLE IF NOT EXISTS play_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    prayer         TEXT,                     -- prayer name
    file           TEXT,                     -- audio file played
    ts             TEXT    NOT NULL,         -- ISO-8601 UTC playback timestamp
    status         TEXT,                     -- 'success' | 'error' | 'skipped' | 'no_speakers'
    zones_played   INTEGER,
    zones_total    INTEGER,
    job_id         TEXT,
    correlation_id TEXT,
    message        TEXT,                     -- error message if any
    created_at     TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ph_ts     ON play_history(ts);
CREATE INDEX IF NOT EXISTS idx_ph_prayer ON play_history(prayer);

CREATE TABLE IF NOT EXISTS played_markers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,             -- YYYY-MM-DD UTC
    prayer     TEXT    NOT NULL,
    ts         TEXT,                         -- ISO-8601 UTC when marked
    details    TEXT,                         -- JSON blob (correlation_id, file …)
    created_at TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(date, prayer)
);
CREATE INDEX IF NOT EXISTS idx_pm_date ON played_markers(date);
"""


def _connect() -> sqlite3.Connection:
    """Return a new SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False,
                           timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Idempotent — safe to call on every startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


# -----------------------------------------------------------------
# Prayer schedule
# -----------------------------------------------------------------

def upsert_prayer_schedule(date: str, prayer: str,
                            scheduled_utc: str, job_id: str = None) -> None:
    """Insert or replace a prayer schedule row."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO prayer_schedule(date, prayer, scheduled_utc, job_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date, prayer)
               DO UPDATE SET scheduled_utc=excluded.scheduled_utc,
                             job_id=excluded.job_id""",
            (date, prayer, scheduled_utc, job_id),
        )


def get_prayer_schedule(date: str) -> List[dict]:
    """Return all prayer rows for *date* ordered by scheduled_utc."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, prayer, scheduled_utc, job_id FROM prayer_schedule "
            "WHERE date = ? ORDER BY scheduled_utc",
            (date,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_prayer_schedule_range(start_date: str, end_date: str) -> List[dict]:
    """Return prayer schedule rows for a date range (inclusive)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, prayer, scheduled_utc, job_id FROM prayer_schedule "
            "WHERE date BETWEEN ? AND ? ORDER BY date, scheduled_utc",
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------
# Play history
# -----------------------------------------------------------------

def record_play(
    prayer: str = None,
    file: str = None,
    ts: str = None,
    status: str = None,
    zones_played: int = None,
    zones_total: int = None,
    job_id: str = None,
    correlation_id: str = None,
    message: str = None,
) -> None:
    """Append a playback attempt record."""
    if not ts:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with _connect() as conn:
        conn.execute(
            """INSERT INTO play_history
               (prayer, file, ts, status, zones_played, zones_total, job_id, correlation_id, message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (prayer, file, ts, status, zones_played, zones_total, job_id, correlation_id, message),
        )


def get_play_history(days: int = 7) -> List[dict]:
    """Return play_history rows for the last *days* UTC days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT prayer, file, ts, status, zones_played, zones_total, "
            "       job_id, correlation_id, message, created_at "
            "FROM play_history WHERE date(ts) >= ? ORDER BY ts DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------
# Played markers (dedup guard)
# -----------------------------------------------------------------

def has_played_today(prayer: str) -> bool:
    """Return True if *prayer* has been recorded as played for today (UTC date)."""
    if not prayer:
        return False
    today = datetime.now(timezone.utc).date().isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM played_markers WHERE date = ? AND prayer = ? LIMIT 1",
            (today, prayer),
        ).fetchone()
    return row is not None


def mark_played(prayer: str, details: dict = None) -> None:
    """Record that *prayer* was played today. Ignores duplicates (UNIQUE constraint)."""
    if not prayer:
        return
    today = datetime.now(timezone.utc).date().isoformat()
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    details_json = json.dumps(details) if isinstance(details, dict) else None
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO played_markers(date, prayer, ts, details)
               VALUES (?, ?, ?, ?)""",
            (today, prayer, ts, details_json),
        )


def get_played_markers(days: int = 1) -> List[dict]:
    """Return played_markers rows for the last *days* UTC days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, prayer, ts, details FROM played_markers "
            "WHERE date >= ? ORDER BY date DESC, ts DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------
# Migration helper — one-time import from legacy JSON files
# -----------------------------------------------------------------

def migrate_from_json(
    played_markers_path: Optional[str] = None,
    play_history_path: Optional[str] = None,
) -> dict:
    """Import existing JSON data into SQLite. Safe to call multiple times (idempotent).

    Returns counts of rows inserted for each table.
    """
    import json as _json

    init_db()
    inserted = {"played_markers": 0, "play_history": 0}

    if played_markers_path and os.path.exists(played_markers_path):
        try:
            with open(played_markers_path, "r", encoding="utf-8") as f:
                markers = _json.load(f)
            with _connect() as conn:
                for m in markers:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO played_markers(date, prayer, ts) VALUES(?,?,?)",
                        (m.get("date"), m.get("prayer"), m.get("ts")),
                    )
                    inserted["played_markers"] += cur.rowcount
        except Exception as e:
            print(f"[db.migrate] played_markers migration error: {e}")

    if play_history_path and os.path.exists(play_history_path):
        try:
            with open(play_history_path, "r", encoding="utf-8") as f:
                hist = _json.load(f)
            with _connect() as conn:
                for h in hist:
                    cur = conn.execute(
                        "INSERT INTO play_history(file, ts, job_id, message) VALUES(?,?,?,?)",
                        (h.get("file"), h.get("ts"), h.get("job_id"), h.get("note")),
                    )
                    inserted["play_history"] += cur.rowcount
        except Exception as e:
            print(f"[db.migrate] play_history migration error: {e}")

    return inserted
