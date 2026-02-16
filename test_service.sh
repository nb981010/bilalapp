#!/bin/bash
echo "=== Service Status ==="
systemctl --user status bilal-server.service --no-pager | head -15

echo ""
echo "=== Port Check ==="
ss -tlnp | grep 5000

echo ""
echo "=== Health Check ==="
curl -sS --max-time 3 http://127.0.0.1:5000/api/health 2>&1 | head -5

echo ""
echo "=== Jobs Check ==="
curl -sS --max-time 3 http://127.0.0.1:5000/api/scheduler/jobs 2>&1 | python3 -m json.tool | head -20
