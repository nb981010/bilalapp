#!/usr/bin/env python3
"""
Frontend health check script for bilal-frontend.service
Checks:
1. Port 3000 is listening
2. Frontend /health endpoint responds
3. Backend proxy works (via /api/health)
"""

import sys
import subprocess
import urllib.request
import urllib.error
import json

def check_port_listening(port=3000):
    """Check if port is listening using ss command"""
    try:
        result = subprocess.run(
            ['ss', '-tlnp'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return False, f"ss command failed with code {result.returncode}"
        
        # Check if port appears in output
        if f':{port}' in result.stdout:
            return True, f"Port {port} is listening"
        else:
            return False, f"Port {port} is NOT listening"
    except Exception as e:
        return False, f"Error checking port: {e}"

def check_http_health(url, timeout=5):
    """Check HTTP endpoint health"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = response.read().decode('utf-8')
            
            if status == 200:
                try:
                    data = json.loads(body)
                    return True, f"OK: {data}"
                except json.JSONDecodeError:
                    return True, f"OK: {body[:100]}"
            else:
                return False, f"HTTP {status}: {body[:100]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"URL Error: {e.reason}"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    print("=== Frontend Health Check ===\n")
    
    all_healthy = True
    
    # Check 1: Port listening
    print("1. Checking port 3000...")
    port_ok, port_msg = check_port_listening(3000)
    print(f"   {port_msg}")
    if not port_ok:
        all_healthy = False
    
    # Check 2: Frontend health endpoint
    print("\n2. Checking frontend /health endpoint...")
    frontend_ok, frontend_msg = check_http_health('http://127.0.0.1:3000/health')
    print(f"   {frontend_msg}")
    if not frontend_ok:
        all_healthy = False
    
    # Check 3: Backend proxy (via /api/health)
    print("\n3. Checking backend proxy (/api/health)...")
    proxy_ok, proxy_msg = check_http_health('http://127.0.0.1:3000/api/health')
    print(f"   {proxy_msg}")
    if not proxy_ok:
        all_healthy = False
    
    # Summary
    print("\n" + "="*40)
    if all_healthy:
        print("✓ All health checks PASSED")
        return 0
    else:
        print("✗ Some health checks FAILED")
        return 1

if __name__ == '__main__':
    sys.exit(main())
