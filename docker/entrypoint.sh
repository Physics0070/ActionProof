#!/bin/sh
# Builds DATABASE_URL from PG_* + the pg_password secret file (never from a plain env var), optionally applies
# the schema (APPLY_SCHEMA=1), then execs the command. Fails closed: any problem stops the container.
set -eu
if [ -z "${DATABASE_URL:-}" ]; then
  : "${PG_PASSWORD_FILE:?PG_PASSWORD_FILE not set}"
  PW="$(cat "$PG_PASSWORD_FILE")"
  # The password must be URL-safe (hex): see docs/RUNBOOK.md.
  DATABASE_URL="postgresql://${PG_USER:?}:${PW}@${PG_HOST:-postgres}:${PG_PORT_INTERNAL:-5432}/${PG_DB:?}"
  export DATABASE_URL
fi
if [ "${APPLY_SCHEMA:-0}" = "1" ]; then
  python scripts/apply_schema.py
fi
exec "$@"
