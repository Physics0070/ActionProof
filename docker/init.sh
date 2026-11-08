#!/bin/sh
# One-shot: schema, then (only when DEMO_SEED=1) demo data. DEMO_SEED=1 WIPES all tables incl. the audit chain.
set -eu
python scripts/apply_schema.py
if [ "${DEMO_SEED:-0}" = "1" ]; then
  python scripts/demo_seed.py --reset
  python scripts/seed_console.py
else
  echo "init: schema applied; DEMO_SEED!=1 so no demo data and no console users were touched"
fi
