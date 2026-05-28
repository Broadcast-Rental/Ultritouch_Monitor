#!/bin/sh
set -e
cd /app

export PYTHONUNBUFFERED=1
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

if [ ! -f /app/config.yaml ]; then
  cp /app/config.example.yaml /app/config.yaml
fi

echo "[start] Ultritouch Fiber Monitor (LOG_LEVEL=$LOG_LEVEL)"
node /app/ember/poller.mjs &
exec python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8080 --log-level info
