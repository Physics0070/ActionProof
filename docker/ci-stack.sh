#!/usr/bin/env bash
# CI/local: bring up the production compose file with a throwaway key + password and the demo seed, wait for healthy.
# Writes E2E_REVIEWER_LOGIN / E2E_REVIEWER_PASSWORD to $GITHUB_ENV when set. Requires uv (gen_key) and docker.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p keys
[ -f keys/signing.key ] || uv run python scripts/gen_key.py keys/signing.key
[ -f keys/pg_password ] || python3 -c "import secrets,sys;sys.stdout.write(secrets.token_hex(24))" > keys/pg_password
chmod 0444 keys/signing.key keys/pg_password   # readable by the container uid; CI-only throwaway material
pw="$(python3 -c "import secrets;print(secrets.token_urlsafe(18))")"
echo "::add-mask::$pw"
if [ -n "${GITHUB_ENV:-}" ]; then
  { echo "E2E_REVIEWER_LOGIN=rev-alice"; echo "E2E_REVIEWER_PASSWORD=$pw"; } >> "$GITHUB_ENV"
fi
export DEMO_SEED=1 CONSOLE_PASSWORD_REV_ALICE="$pw"
docker compose -f docker-compose.yml up -d --build --wait api web
