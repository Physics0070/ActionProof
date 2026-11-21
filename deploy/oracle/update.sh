#!/usr/bin/env bash
# Update the running stack to the latest main: back up first, pull, rebuild, restart, show the state.
# Rollback: `git checkout <previous commit>` then run this again (the schema only ever adds; see docs/RUNBOOK.md).
set -euo pipefail
cd "$(dirname "$0")/../.."
bash deploy/oracle/backup.sh
git pull --ff-only
DC=(docker compose -f docker-compose.yml -f deploy/oracle/compose.caddy.yml --env-file deploy/oracle/.env)
"${DC[@]}" config -q
if grep -q '^CADDYFILE=Caddyfile.full' deploy/oracle/.env; then SERVICES=(postgres opa init api web caddy); else SERVICES=(postgres opa init api caddy); fi
"${DC[@]}" up -d --build "${SERVICES[@]}"
"${DC[@]}" ps
