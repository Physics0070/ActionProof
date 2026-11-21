#!/usr/bin/env bash
# Logical backup of the whole database (records, commits, the audit chain and its checkpoints) to backups/.
# Keeps the 14 newest. Cron (daily 03:15):   15 3 * * * cd /home/ubuntu/ActionProof && bash deploy/oracle/backup.sh
# Restore: docs/RUNBOOK.md section 3, then `python -m actionproof.audit verify` (the chain must verify after a restore).
# Copy the dump off the VM (a free object store, or your own machine): a backup on the same disk is not a backup.
set -euo pipefail
cd "$(dirname "$0")/../.."
DC=(docker compose -f docker-compose.yml -f deploy/oracle/compose.caddy.yml --env-file deploy/oracle/.env)
mkdir -p backups
out="backups/actionproof-$(date -u +%Y%m%dT%H%M%SZ).dump"
"${DC[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$out.part"
mv "$out.part" "$out"
chmod 0600 "$out"
ls -1t backups/actionproof-*.dump | tail -n +15 | xargs -r rm --
echo "wrote $out ($(du -h "$out" | cut -f1))"
