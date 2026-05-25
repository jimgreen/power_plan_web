#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export POWER_PLAN_LOCAL_AUTH_BYPASS="${POWER_PLAN_LOCAL_AUTH_BYPASS:-1}"
if [[ -x ../venv/bin/python ]]; then
  exec ../venv/bin/python server.py --host 127.0.0.1 --port 8866
elif [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python server.py --host 127.0.0.1 --port 8866
else
  exec python3 server.py --host 127.0.0.1 --port 8866
fi
