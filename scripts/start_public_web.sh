#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${POWER_PLAN_PUBLIC_HOST:-0.0.0.0}"
PORT="${POWER_PLAN_PUBLIC_PORT:-8866}"

export POWER_PLAN_LOCAL_AUTH_BYPASS="${POWER_PLAN_LOCAL_AUTH_BYPASS:-0}"

if [[ -x ../venv/bin/python ]]; then
  exec ../venv/bin/python server.py --host "$HOST" --port "$PORT"
elif [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python server.py --host "$HOST" --port "$PORT"
else
  exec python3 server.py --host "$HOST" --port "$PORT"
fi
