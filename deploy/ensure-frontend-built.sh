#!/bin/bash
# Pre-start script: ensure frontend is built before starting the service

set -e

WORKDIR="/home/nbc/bilalapp"
DIST_DIR="$WORKDIR/dist"
DIST_INDEX="$DIST_DIR/index.html"

cd "$WORKDIR"

# Check if dist/index.html exists
if [ ! -f "$DIST_INDEX" ]; then
    echo "[ensure-frontend-built] dist/index.html not found, building frontend..."
    npm run build
    if [ $? -ne 0 ]; then
        echo "[ensure-frontend-built] ERROR: npm run build failed"
        exit 1
    fi
    echo "[ensure-frontend-built] Build completed successfully"
else
    echo "[ensure-frontend-built] dist/index.html exists, skipping build"
fi

exit 0
