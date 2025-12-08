#!/usr/bin/env python3
"""
Inspect APScheduler jobstore (`jobs.sqlite`) and print azan jobs.
Usage: python3 tools/inspect_jobstore.py [path/to/jobs.sqlite]
"""
import sys
import sqlite3
import pickle
from datetime import datetime

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else 'jobs.sqlite'

def try_unpickle(b):
    # Some job_state entries may be stored as bytes or memoryview
    try:
        if isinstance(b, memoryview):
            b = b.tobytes()
        if isinstance(b, str):
            b = b.encode('utf-8')
        return pickle.loads(b)
    except Exception as e:
        return None


def extract_kwargs(obj):
    # obj may be a dict-like state produced by apscheduler; try common shapes
    if obj is None:
        return None
    if isinstance(obj, dict):
        # direct keys
        if 'kwargs' in obj and isinstance(obj['kwargs'], dict):
            return obj['kwargs']
        # some versions embed job details under 'job_state' or similar
        for k in ('_job', 'job_state', 'job'):
            v = obj.get(k)
            if isinstance(v, dict) and 'kwargs' in v:
                return v['kwargs']
        # fallback: find any dict value that contains 'file'/'prayer'
        for v in obj.values():
            if isinstance(v, dict) and ('file' in v or 'prayer' in v):
                return v
    # If it's a custom object, try to read __dict__
    try:
        d = getattr(obj, '__dict__', None)
        if isinstance(d, dict):
            if 'kwargs' in d and isinstance(d['kwargs'], dict):
                return d['kwargs']
            for v in d.values():
                if isinstance(v, dict) and ('file' in v or 'prayer' in v):
                    return v
    except Exception:
        pass
    return None


def print_jobs(db_path):
    try:
        conn = sqlite3.connect(db_path)
    except Exception as e:
        print(f"Could not open database '{db_path}': {e}")
        return

    cur = conn.cursor()
    # Try common table name used by APScheduler SQLAlchemyJobStore
    try:
        cur.execute("SELECT id, next_run_time, job_state FROM apscheduler_jobs WHERE id LIKE 'azan-%' ORDER BY id")
    except Exception as e:
        print(f"Query failed: {e}")
        conn.close()
        return

    rows = cur.fetchall()
    if not rows:
        print("No azan- jobs found in jobstore.")
        conn.close()
        return

    print(f"Found {len(rows)} azan jobs in {db_path}:\n")
    for id_, nrt, state in rows:
        # next_run_time is stored as float unix timestamp or text
        nrt_str = str(nrt)
        try:
            if nrt:
                # try float -> datetime
                nrt_str = datetime.utcfromtimestamp(float(nrt)).isoformat() + 'Z'
        except Exception:
            pass

        un = try_unpickle(state)
        kwargs = extract_kwargs(un)
        file_val = kwargs.get('file') if isinstance(kwargs, dict) else None
        prayer_val = kwargs.get('prayer') if isinstance(kwargs, dict) else None

        print(f"Job ID: {id_}")
        print(f"  next_run_time: {nrt_str}")
        print(f"  file: {file_val}")
        print(f"  prayer: {prayer_val}")
        if isinstance(kwargs, dict):
            # Print any extra kwargs
            extras = {k: v for k, v in kwargs.items() if k not in ('file', 'prayer')}
            if extras:
                print(f"  extra kwargs: {extras}")
        else:
            print(f"  raw job state (unpickle repr): {repr(un)[:200]}")
        print()

    conn.close()

if __name__ == '__main__':
    print_jobs(DB_PATH)
