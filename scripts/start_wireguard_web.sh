#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${POWER_PLAN_WG_PORT:-8866}"
HOST="${POWER_PLAN_WG_HOST:-}"

if [[ -z "$HOST" ]]; then
  for candidate in 10.88.0.3 10.7.0.3 10.15.0.3; do
    if ip -4 addr show | grep -q " ${candidate}/"; then
      HOST="$candidate"
      break
    fi
  done
fi

if [[ -z "$HOST" ]]; then
  echo "No known WireGuard IP was found. Set POWER_PLAN_WG_HOST first." >&2
  exit 1
fi

if ! ip -4 addr show | grep -q " ${HOST}/"; then
  echo "WireGuard IP ${HOST} is not present on this machine." >&2
  exit 1
fi

export POWER_PLAN_LOCAL_AUTH_BYPASS="${POWER_PLAN_LOCAL_AUTH_BYPASS:-0}"

if [[ -x ../venv/bin/python ]]; then
  exec ../venv/bin/python server.py --host "$HOST" --port "$PORT"
elif [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python server.py --host "$HOST" --port "$PORT"
else
  exec python3 server.py --host "$HOST" --port "$PORT"
fi
