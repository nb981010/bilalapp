#!/usr/bin/env python3
"""Summarize today's prayer scheduling/playback status from logs/sys.log

Outputs: prayer -> status (SUCCESS / FAILED / WAITING / SKIPPED) with short evidence lines.
"""
import re
from datetime import date
import sys

LOG_PATH = 'logs/sys.log'
PRAYERS = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

def load_lines_for_day(day_iso):
    pattern = day_iso
    lines = []
    with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        for ln in f:
            if pattern in ln:
                lines.append(ln.rstrip('\n'))
    return lines

def find_scheduling(lines, day_iso):
    sched = {}
    rx = re.compile(r"Scheduling (\w+) Azan at ([0-9T:+-]+)")
    for l in lines:
        m = rx.search(l)
        if m:
            p = m.group(1).lower()
            t = m.group(2)
            if p in PRAYERS:
                sched[p] = sched.get(p, []) + [(t, l)]
    return sched

def find_removed(lines, day_iso):
    removed = set()
    rx = re.compile(r"Removed job azan-" + re.escape(day_iso) + r"-(\w+)")
    for l in lines:
        m = rx.search(l)
        if m:
            removed.add(m.group(1).lower())
    return removed

def evidence_for(prayer, lines, day_iso):
    ev = []
    # Received Play Request
    for l in lines:
        if re.search(r"Received Play Request: .*azan", l, re.I) and day_iso in l:
            ev.append(l)
        if re.search(r"Scheduled play POST failed for azan", l, re.I) and day_iso in l:
            ev.append(l)
        if re.search(r"No speakers found|No speakers found for Azan playback", l, re.I) and day_iso in l:
            ev.append(l)
        if re.search(r"HTTP Error 500|timed out|INTERNAL SERVER ERROR", l, re.I) and day_iso in l:
            ev.append(l)
    # also include any "Skipping past prayer <prayer>" lines
    for l in lines:
        if f"Skipping past prayer {prayer}" in l or f"Skipping past prayer {prayer}".upper() in l:
            ev.append(l)
    return ev

def main():
    day_iso = date.today().isoformat() if len(sys.argv) == 1 else sys.argv[1]
    try:
        lines = load_lines_for_day(day_iso)
    except FileNotFoundError:
        print(f"Log file not found: {LOG_PATH}")
        sys.exit(2)

    sched = find_scheduling(lines, day_iso)
    removed = find_removed(lines, day_iso)

    results = {}
    for p in PRAYERS:
        # Determine scheduled time if any
        scheduled = sched.get(p)
        if p in removed:
            # remove marker exists -> job fired. Check for playback errors
            ev = evidence_for(p, lines, day_iso)
            failed_markers = [e for e in ev if re.search(r"Scheduled play POST failed|HTTP Error|timed out|No speakers found|INTERNAL SERVER ERROR", e, re.I)]
            success_markers = [e for e in ev if re.search(r"Received Play Request: .*azan", e, re.I) and not failed_markers]
            if failed_markers:
                results[p] = ("FAILED", failed_markers[:3])
            elif success_markers:
                results[p] = ("SUCCESS", success_markers[:3])
            else:
                # removed but no explicit evidence -> mark as FAILED but show removed line
                results[p] = ("FAILED", [f"Job fired but no playback evidence for {p} on {day_iso}"])
        else:
            # not removed
            # check skip lines
            skip_lines = [l for l in lines if f"Skipping past prayer {p}" in l or f"Skipping past prayer {p}".upper() in l]
            if skip_lines:
                results[p] = ("SKIPPED", skip_lines[:3])
            elif scheduled:
                # scheduled and not fired -> waiting
                results[p] = ("WAITING", [scheduled[0][1]])
            else:
                results[p] = ("UNKNOWN", ["No schedule entry found"])

    # Print summary
    print(f"Prayer status for {day_iso}:\n")
    for p in PRAYERS:
        status, ev = results.get(p, ("UNKNOWN", []))
        print(f"- {p.title()}: {status}")
        for e in ev:
            print(f"    > {e}")
    print('\nNotes:')
    print('- SUCCESS: job fired and play request observed without error markers')
    print('- FAILED: job fired but play request had errors or no playback evidence')
    print('- WAITING: scheduled for later today and not yet fired')
    print('- SKIPPED: scheduler considered the prayer time in the past and skipped it')

if __name__ == "__main__":
    main()
