#!/bin/bash
# Combined health check for backend and frontend services

set +e  # Don't exit on error, we want to check everything

echo "=========================================="
echo "  Bilal Services Status Check"
echo "=========================================="
echo ""

# Check backend service
echo "--- Backend Service (bilal-server.service) ---"
systemctl --user is-active --quiet bilal-server.service
if [ $? -eq 0 ]; then
    echo "✓ Service: RUNNING"
else
    echo "✗ Service: NOT RUNNING"
fi

# Check backend port
ss -tlnp | grep -q ':5000'
if [ $? -eq 0 ]; then
    echo "✓ Port 5000: LISTENING"
else
    echo "✗ Port 5000: NOT LISTENING"
fi

# Backend health endpoint
curl -s -f http://127.0.0.1:5000/api/health > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Health endpoint: OK"
else
    echo "✗ Health endpoint: FAILED"
fi

echo ""
echo "--- Frontend Service (bilal-frontend.service) ---"

# Check frontend service
systemctl --user is-active --quiet bilal-frontend.service
if [ $? -eq 0 ]; then
    echo "✓ Service: RUNNING"
else
    echo "✗ Service: NOT RUNNING"
fi

# Check frontend port
ss -tlnp | grep -q ':3000'
if [ $? -eq 0 ]; then
    echo "✓ Port 3000: LISTENING"
else
    echo "✗ Port 3000: NOT LISTENING"
fi

# Frontend health endpoint
curl -s -f http://127.0.0.1:3000/health > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Health endpoint: OK"
else
    echo "✗ Health endpoint: FAILED"
fi

# Frontend proxy to backend
curl -s -f http://127.0.0.1:3000/api/health > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Backend proxy: OK"
else
    echo "✗ Backend proxy: FAILED"
fi

echo ""
echo "=========================================="
echo ""

# Show service status summary
echo "Service Status:"
systemctl --user status bilal-server.service bilal-frontend.service --no-pager -l | head -50

exit 0
