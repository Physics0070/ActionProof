#!/usr/bin/env bash
# ActionProof demo: plays every beat in order against the real gate (docs/DEMO.md). Works in Git Bash and Linux.
#   bash demo.sh                 run the demo (exit 0 only if every beat produced its expected outcome)
#   DEMO_PAUSE=1 bash demo.sh    wait for Enter between beats while recording
# Services: DATABASE_URL / OPA_URL if reachable, else it starts the local dev Postgres (scripts/dev_pg.py) and OPA
# (OPA_BIN). Runs in its own database (DEMO_DB, default actionproof_demo); shared data is never touched.
set -euo pipefail
cd "$(dirname "$0")"

# Config comes from the environment; .env.example only supplies dev defaults for names that are not set.
if [ -f .env.example ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*|*[!A-Za-z0-9_]*) continue ;; esac
    v="${v//[[:cntrl:]]/}"
    if [ -z "${!k+x}" ]; then export "$k=${v%%#*}"; fi
  done < .env.example
fi

if [ -x .venv/Scripts/python.exe ]; then PY=(.venv/Scripts/python.exe)
elif [ -x .venv/bin/python ]; then PY=(.venv/bin/python)
elif python -m uv --version >/dev/null 2>&1; then PY=(python -m uv run python)
elif command -v python3 >/dev/null 2>&1; then PY=(python3)
else PY=(python); fi

exec "${PY[@]}" scripts/demo.py "$@"
