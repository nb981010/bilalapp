#!/usr/bin/env python3
"""Migrate existing logs/play_history.json into SQLite DB used by the app.
Idempotent: will skip rows that already exist (matching file+ts).
"""
import json
import os
import sqlite3
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = APP_DIR / 'logs'
JSON_PATH = LOGS_DIR / 'play_history.json'
DB_PATH = APP_DIR / os.environ.get('BILAL_DB_PATH', 'bilal_jobs.sqlite')


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file TEXT NOT NULL,
            ts TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def row_exists(conn, file, ts):
    c = conn.cursor()
    c.execute('SELECT COUNT(1) FROM play_history WHERE file=? AND ts=?', (file, ts))
    return c.fetchone()[0] > 0


def migrate():
    init_db(DB_PATH)
    if not JSON_PATH.exists():
        print(f"No {JSON_PATH} to migrate.")
        return 0
    try:
        data = json.loads(JSON_PATH.read_text())
        if not isinstance(data, list):
            print("play_history.json not a list; aborting")
            return 0
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        return 0
    conn = sqlite3.connect(DB_PATH)
    inserted = 0
    for entry in data:
        try:
            file = entry.get('file')
            ts = entry.get('ts')
            if not file or not ts:
                continue
            if row_exists(conn, file, ts):
                continue
            c = conn.cursor()
            c.execute('INSERT INTO play_history (file, ts) VALUES (?, ?)', (file, ts))
            inserted += 1
        except Exception:
            continue
    conn.commit()
    conn.close()
    print(f"Imported {inserted} rows into {DB_PATH}")
    return inserted


if __name__ == '__main__':
    migrated = migrate()
    print('DONE')
