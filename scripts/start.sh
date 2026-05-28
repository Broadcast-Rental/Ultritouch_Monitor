#!/bin/sh
set -e
cd /app

export PYTHONUNBUFFERED=1
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

NODE_PID=""
cleanup() {
  if [ -n "$NODE_PID" ]; then
    kill "$NODE_PID" 2>/dev/null || true
    wait "$NODE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ ! -f /app/config.yaml ]; then
  cp /app/config.example.yaml /app/config.yaml
fi

API_PORT=$(python -c "import yaml; c=yaml.safe_load(open('/app/config.yaml')); print(int(c.get('api',{}).get('port',8080)))")
API_HOST=$(python -c "import yaml; c=yaml.safe_load(open('/app/config.yaml')); print(c.get('api',{}).get('host','0.0.0.0'))")

# network_mode: host — port conflicts are on the Docker host, not inside the container namespace
if command -v ss >/dev/null 2>&1; then
  if ss -tln 2>/dev/null | grep -qE ":${API_PORT}([[:space:]]|$)"; then
    echo "[start] FATAL: port ${API_PORT} is already in use on this host."
    echo "[start] With network_mode:host only one instance can run. In Portainer: stop duplicate stacks,"
    echo "[start] or on the server: docker ps && docker stop <other-container>"
    echo "[start] Or set a different api.port in config.yaml (e.g. 8088) and redeploy."
    exit 1
  fi
fi

echo "[start] Ultritouch Fiber Monitor (LOG_LEVEL=$LOG_LEVEL, port=$API_PORT)"
node /app/ember/poller.mjs &
NODE_PID=$!
exec python -m uvicorn src.api.main:app --host "$API_HOST" --port "$API_PORT" --log-level info
