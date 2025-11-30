#!/usr/bin/env python3
"""
Simple migration helper to ensure the `audio_files` table exists in the SQLite DB.
Run: python3 scripts/create_audio_table.py [path/to/db]
"""
import sqlite3
import sys
import os
from datetime import datetime

DB = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('BILAL_DB_PATH', 'bilal_jobs.sqlite')

SQL = '''
CREATE TABLE IF NOT EXISTS audio_files (
    filename TEXT PRIMARY KEY,
    qari_name TEXT,
    uploaded_by TEXT,
    uploaded_at TEXT
);
'''

if __name__ == '__main__':
    print(f"Ensuring audio_files table in DB: {DB}")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(SQL)
    conn.commit()
    conn.close()
    print('Done.')
