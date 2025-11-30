#!/usr/bin/env python3
"""Smoke test for cloud-first, SoCo-fallback decision logic.

This script performs lightweight HTTP checks against the cloud and local microservices
to determine which control path the backend would choose for playback without
invoking actual Sonos playback.
"""
import requests
import os

CLOUD_URL = os.environ.get('SONOS_CLOUD_URL', 'http://127.0.0.1:6000')
LOCAL_URL = os.environ.get('SOCO_LOCAL_URL', 'http://127.0.0.1:5001')

def try_cloud():
    try:
        r = requests.get(f"{CLOUD_URL}/cloud/discover", timeout=3)
        print(f"cloud/discover -> status={r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"cloud returned {len(data) if isinstance(data, list) else 'non-list'} devices")
            if isinstance(data, list) and len(data) > 0:
                return True, data
        return False, None
    except Exception as e:
        print(f"cloud discover error: {e}")
        return False, None

def try_local():
    try:
        r = requests.get(f"{LOCAL_URL}/local/discover", timeout=3)
        print(f"local/discover -> status={r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"local returned {len(data) if isinstance(data, list) else 'non-list'} devices")
            if isinstance(data, list) and len(data) > 0:
                return True, data
        return False, None
    except Exception as e:
        print(f"local discover error: {e}")
        return False, None

def main():
    print(f"Testing cloud-first against {CLOUD_URL} then fallback to {LOCAL_URL}")
    cloud_ok, cloud_data = try_cloud()
    if cloud_ok:
        print("Decision: USE CLOUD (first preference)")
        return
    print("Cloud not usable; trying local SoCo fallback...")
    local_ok, local_data = try_local()
    if local_ok:
        print("Decision: USE LOCAL SoCo (fallback)")
        return
    print("Decision: NO DEVICES FOUND on cloud or local. Both paths failed.")

if __name__ == '__main__':
    main()
