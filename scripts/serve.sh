#!/usr/bin/env bash
# KathaPulse AI — supervised preview server.
#
# A cloud runner restart (or an unhandled crash) otherwise leaves the preview
# iframe showing "refused to connect". This wrapper restarts uvicorn within a
# second and logs every exit, so the panel recovers on its own.
#
# Usage:
#   ./scripts/serve.sh                 # foreground
#   nohup setsid ./scripts/serve.sh >/dev/null 2>&1 < /dev/null &   # detached
#
# PORT defaults to 3004 (the chat's preview port) and HOST to 0.0.0.0, which is
# required for the preview proxy to reach the process.

set -u

export PORT="${PORT:-3004}"
export HOST="${HOST:-0.0.0.0}"
LOG="${KATHA_LOG:-/tmp/kathapulse.log}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/uvicorn"

cd "$ROOT" || exit 1

if [ ! -x "$PY" ]; then
  echo "[serve] $PY not found — run: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

echo "[serve] starting on $HOST:$PORT (log: $LOG)"
while true; do
  "$PY" app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    >>"$LOG" 2>&1
  status=$?
  echo "[serve] uvicorn exited with status $status — restarting in 1s" >>"$LOG"
  sleep 1
done
