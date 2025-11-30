#!/usr/bin/env python3
"""
Idempotent migration to create `sonos_cloud_tokens` table in the BILAL_DB_PATH SQLite file.
Run: python3 scripts/migrate_sonos_tokens.py
"""
import os
import sqlite3

DB_PATH = os.environ.get('BILAL_DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'bilal_jobs.sqlite'))


def init_db(path):
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS sonos_cloud_tokens (
            id INTEGER PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT,
            expires_at INTEGER
        )
    ''')
    conn.commit()
    conn.close()


if __name__ == '__main__':
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db(DB_PATH)
    print(f"Ensured sonos_cloud_tokens exists in {DB_PATH}")
