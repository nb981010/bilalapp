#!/usr/bin/env python3
import os, json, sqlite3, subprocess
from datetime import datetime, date
from zoneinfo import ZoneInfo

def get_prayer_times(target_date_str):
    script = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'compute_prayer_times.mjs')
    script = os.path.abspath(script)
    if not os.path.exists(script):
        return None
    try:
        p = subprocess.run(['node', script, target_date_str], capture_output=True, text=True, env=os.environ, timeout=15)
        if p.returncode != 0:
            print('Node helper failed:', p.stderr)
            return None
        return json.loads(p.stdout)
    except Exception as e:
        print('Failed to run node helper:', e)
        return None

DB = os.environ.get('BILAL_DB_PATH', 'bilal_jobs.sqlite')
TZ = os.environ.get('PRAYER_TZ', 'Asia/Dubai')
TOL = int(os.environ.get('PRAYER_PLAY_TOL_MIN', '5'))

def read_play_history(limit=200):
    try:
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute('SELECT file, ts FROM play_history ORDER BY id DESC LIMIT ?', (limit,))
        rows = c.fetchall()
        conn.close()
        rows.reverse()
        return [{'file': r[0], 'ts': r[1]} for r in rows]
    except Exception as e:
        print('Failed to read DB:', e)
        return []


def iso_to_dt(s):
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(TZ))
        return dt
    except Exception:
        return None


def main():
    today = date.today()
    target = today.isoformat()
    print('Checking azan play status for', target, 'TZ=', TZ, 'TOL(min)=', TOL)
    times = get_prayer_times(target)
    if not times:
        print('Could not get prayer times')
        return
    play_history = read_play_history(200)
    # convert play history timestamps
    for e in play_history:
        e['dt'] = iso_to_dt(e['ts'])
    prayers = ['fajr','dhuhr','asr','maghrib','isha']
    tz = ZoneInfo(TZ)
    for p in prayers:
        tstr = times.get(p)
        if not tstr:
            print(p, '- no time')
            continue
        hour,minute = map(int,tstr.split(':'))
        sched = datetime(today.year,today.month,today.day,hour,minute,tzinfo=tz)
        # find play within tolerance
        played = None
        for entry in play_history:
            if not entry.get('dt'):
                continue
            delta = abs((entry['dt'] - sched).total_seconds())
            if delta <= TOL*60 and (('azan' in (entry['file'] or '').lower()) or (p=='fajr' and 'fajr' in (entry['file'] or '').lower())):
                played = entry
                break
        if played:
            dt = played['dt'].astimezone(tz)
            diff = (dt - sched).total_seconds()/60.0
            print(f"{p}: PLAYED on time at {dt.isoformat()} (delta {diff:+.2f} min) file={played['file']}")
        else:
            # show nearest play
            nearest = None
            ndiff = None
            for entry in play_history:
                if not entry.get('dt'): continue
                if (('azan' in (entry['file'] or '').lower()) or (p=='fajr' and 'fajr' in (entry['file'] or '').lower())):
                    d = (entry['dt'] - sched).total_seconds()
                    ad = abs(d)
                    if ndiff is None or ad < ndiff:
                        ndiff = ad; nearest = entry
            if nearest:
                ndt = nearest['dt'].astimezone(tz)
                print(f"{p}: NOT on time. Nearest play at {ndt.isoformat()} (delta {ndiff/60.0:+.2f} min) file={nearest['file']}")
            else:
                print(f"{p}: No recorded play entries found")

if __name__ == '__main__':
    main()
