#!/usr/bin/env python3
"""
Health check script for Bilal Azan Server.
Can be run from cron or manually to verify scheduler is healthy.
"""
import requests
import sys
import json

def check_health():
    """Check the health endpoint and return status."""
    try:
        response = requests.get('http://localhost:5000/api/health', timeout=5)
        data = response.json()
        
        print(f"Status: {data.get('status')}")
        print(f"Timestamp: {data.get('timestamp')}")
        
        scheduler = data.get('scheduler', {})
        print(f"\nScheduler:")
        print(f"  Healthy: {scheduler.get('healthy')}")
        print(f"  Message: {scheduler.get('message')}")
        
        if 'last_heartbeat' in scheduler:
            print(f"  Last Heartbeat: {scheduler['last_heartbeat']}")
            print(f"  Heartbeat Age: {scheduler.get('heartbeat_age_seconds', 'N/A')}s")
        
        if 'total_jobs' in scheduler:
            print(f"  Total Jobs: {scheduler['total_jobs']}")
            print(f"  Azan Jobs: {scheduler['azan_jobs']}")
        
        # Exit with error code if unhealthy
        if data.get('status') != 'healthy':
            print("\n⚠️  System is UNHEALTHY!")
            return 1
        
        print("\n✓ System is healthy")
        return 0
        
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to server (is it running?)")
        return 2
    except Exception as e:
        print(f"ERROR: {e}")
        return 2

if __name__ == '__main__':
    sys.exit(check_health())
