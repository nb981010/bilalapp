#!/usr/bin/env python3
"""
Parse `logs/sys.log` and `logs/played_markers.json` to build a per-prayer
status table for a given date.

Usage: python3 tools/daily_status.py 2025-12-05
"""
import sys
import re
from datetime import datetime
import json

LOG = 'logs/sys.log'
MARKERS = 'logs/played_markers.json'

def parse_log_for_date(date_str):
    # date_str example: '2025-12-05'
    start_re = re.compile(r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - .*play_from_job invoked: file=(?P<file>[^ ]+) prayer=(?P<prayer>[^ ]+)')
    play_re = re.compile(r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - .*Playing URL .*?/audio/(?P<file>[^ ]+)')
    finish_re = re.compile(r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) - .*Playback finished')

    events = []
    with open(LOG, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if not line.startswith(date_str):
                continue
            m = start_re.match(line)
            if m:
                ts = m.group('ts')
                prayer = m.group('prayer')
                file = m.group('file')
                events.append(('start', prayer.lower(), ts, file))
                continue

            m2 = play_re.match(line)
            if m2:
                ts = m2.group('ts')
                file = m2.group('file')
                # playing line doesn't include prayer; mark as play event
                events.append(('playing', None, ts, file))
                continue

            m3 = finish_re.match(line)
            if m3:
                ts = m3.group('ts')
                events.append(('finish', None, ts, None))

    return events


def load_markers(date_str):
    try:
        with open(MARKERS, 'r', encoding='utf-8') as f:
            markers = json.load(f)
    except Exception:
        return {}

    res = {}
    for m in markers:
        if m.get('date') == date_str:
            res[m.get('prayer')] = m
    return res


def iso_from_log_ts(log_ts):
    # convert '2025-12-05 05:28:00,012' -> '2025-12-05 05:28:00.012'
    s = log_ts.replace(',', '.')
    try:
        dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S.%f')
        return dt.isoformat(sep=' ')
    except Exception:
        return s


def duration_str(start_iso, end_iso):
    try:
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso)
        delta = e - s
        total = int(delta.total_seconds())
        mm = total // 60
        ss = total % 60
        ms = delta.microseconds // 1000
        return f"{mm:02d}:{ss:02d}.{ms:03d}"
    except Exception:
        return ''


def build_table_for_date(date_str):
    # canonical prayer order
    prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
    events = parse_log_for_date(date_str)
    markers = load_markers(date_str)

    # We'll map prayer -> start_ts and end_ts by scanning events in order
    result = {p: {'start': None, 'end': None, 'file': None, 'status': 'Missing'} for p in prayers}

    # Keep a pointer to the last seen prayer start if playing/finish come without prayer
    last_prayer = None
    for ev in events:
        kind, prayer, ts, file = ev
        if kind == 'start' and prayer in result:
            # record first start for that prayer
            if result[prayer]['start'] is None:
                result[prayer]['start'] = iso_from_log_ts(ts)
                result[prayer]['file'] = file
                last_prayer = prayer
        elif kind == 'playing':
            # ignore, but could help deduce file if start missing
            if last_prayer and not result[last_prayer]['file']:
                result[last_prayer]['file'] = file
        elif kind == 'finish':
            # assign finish to last_prayer if available, else try to assign to prayers with start but no end
            if last_prayer:
                result[last_prayer]['end'] = iso_from_log_ts(ts)
                result[last_prayer]['status'] = 'Success'
                last_prayer = None
            else:
                # find most recent prayer with start but no end
                for p in reversed(prayers):
                    if result[p]['start'] and not result[p]['end']:
                        result[p]['end'] = iso_from_log_ts(ts)
                        result[p]['status'] = 'Success'
                        break

    # Cross-check with played markers: if marker exists mark Success and set file/start if missing
    for p, info in result.items():
        m = markers.get(p)
        if m:
            info['status'] = 'Success'
            if not info['file']:
                info['file'] = m.get('file')
            if not info['start'] and m.get('ts'):
                # marker ts is ISO Z; convert to space-separated local-ish representation
                try:
                    dt = datetime.fromisoformat(m.get('ts').replace('Z', '+00:00'))
                    info['start'] = dt.isoformat(sep=' ')
                except Exception:
                    info['start'] = m.get('ts')

        # compute duration if possible
        if info['start'] and info['end']:
            info['duration'] = duration_str(info['start'], info['end'])
        else:
            info['duration'] = ''

    return result


def print_table(date_str, table):
    print('Date Prayer Start (log) End (log) Duration Status')
    for p in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
        info = table[p]
        start = info['start'] or ''
        end = info['end'] or ''
        dur = info.get('duration', '')
        status = info.get('status', 'Missing')
        print(f"{date_str} {p.capitalize()} {start} {end} {dur} {status}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: daily_status.py YYYY-MM-DD')
        sys.exit(2)
    date = sys.argv[1]
    table = build_table_for_date(date)
    print_table(date, table)
