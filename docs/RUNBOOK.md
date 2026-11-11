# Runbook

**USP: Proof before permission.** G1: no value authorizes a write unless its derivation re-checks. G2: no approval can be replayed.
Status: authored, not exercised end to end (the Docker engine was unavailable when this was written; see README.md (honest limits)).

## Limits (deck slide 10, verbatim)
- Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven.
- Semantic fraud: A fake invoice that looks internally consistent is out of scope.
- The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening.
- Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision.

## 1. Run

### Full stack (Docker)
```bash
python -m uv sync
python scripts/gen_key.py keys/signing.key                       # first run only; refuses to overwrite; prints the PUBLIC key
python -c "import secrets,sys;sys.stdout.write(secrets.token_hex(24))" > keys/pg_password   # hex = URL-safe
cp .env.example .env   # then edit; real values only in .env or the shell (git-ignored)
docker compose -f docker-compose.yml config -q                   # validate
DEMO_SEED=1 docker compose -f docker-compose.yml up -d --build   # DEMO_SEED=1 WIPES all tables incl. the audit chain
docker compose -f docker-compose.yml ps                          # api, web, postgres, opa healthy; init exited 0
```
- Published: web `127.0.0.1:5173`, api `127.0.0.1:8766` (change with `WEB_BIND`/`API_BIND`). Postgres and OPA sit on an
  `internal` network and are not reachable from the host. The auto-loaded `docker-compose.override.yml` is DEV ONLY (it
  publishes postgres 5433 and opa 8181 and uses the dev password); `-f docker-compose.yml` ignores it.
- Console logins: with `DEMO_SEED=1`, `init` runs `seed_console.py`; generated passwords are printed once in
  `docker compose logs init` (or pass `CONSOLE_PASSWORD_REV_ALICE` etc.).
- Secrets are compose `secrets:` files mounted at `/run/secrets/*`; the signing key is mounted only into `api`.
  On Linux set `APP_UID/APP_GID` to the key file's owner (or `chmod 0444 keys/signing.key`) so uid 10001 can read it.
- MCP server (same image): `docker compose -f docker-compose.yml run --rm -i -T -e ACTIONPROOF_ACTOR=agent-7 -e ACTIONPROOF_ON_BEHALF_OF=user-123 api python -m actionproof.server --stdio`
- Web is built with `CONSOLE_API_ORIGIN=http://api:8766` baked into its rewrite table; changing it means rebuilding `web`.

### Local, no Docker
```bash
python scripts/dev_pg.py start                      # Postgres 16 on :5433 (binaries in C:/Users/Soham/tools/pgsql)
C:/Users/Soham/tools/opa/opa.exe run --server --addr 127.0.0.1:8181 --watch policy &
python scripts/gen_key.py keys/dev-signing.key
python scripts/demo_seed.py --reset && python scripts/seed_console.py
python -m actionproof.console                       # CONSOLE_BIND_HOST:CONSOLE_PORT, default 127.0.0.1:8766 (compose sets 0.0.0.0 in the container)
cd web && npm install && npm run dev                # http://localhost:5173
```

### Evaluation (slow, needs a judge key)
`python -m uv run python -m eval.run` runs the five arms over the attack and benign sets and writes
`eval/results.json` (about 25 minutes). The LLM-judge arm needs `GROQ_API_KEY` and `JUDGE_MODEL` in the shell or a
git-ignored `.env` (without them that arm is recorded `not_run`). `python -m uv run python -m eval.run --report` renders
`docs/EVAL.md` from the results without running anything. The console serves `eval/results.json` at
`/api/public/eval` (compose mounts `./eval` read-only). In CI this is `.github/workflows/eval.yml`, manual or nightly
only (secret `GROQ_API_KEY`, variable `JUDGE_MODEL`).

## 2. Key rotation
Receipts and checkpoints carry a `kid`. The audit verifier (`python -m actionproof.audit verify`) verifies each checkpoint with the public key of its `kid`: put one `<kid>.pub` per key ever used in a directory and set `AUDIT_PUBLIC_KEYS_DIR` to it (an unknown `kid` is `FAILED`). `AUDIT_PUBLIC_KEY_PATH` (one key, any `kid`) still works for a never-rotated chain.
Rotate at a quiet point so nothing is verified with the wrong key:
1. Drain: no `pending` reviews (decide or let them expire: unexpired receipts signed by the old key fail after the swap).
2. Verify the chain with the OLD public key and save the output line (`audit: OK (N entries, M checkpoints)`). This is
   the record that everything up to seq N was intact under `k1`.
3. Keep the old PUBLIC key forever (`keys/pub/k1.pub`, base64 from `Signer.public_key_b64()`); archive the old seed offline, then delete it from the host.
4. `python scripts/gen_key.py keys/signing.key.new`; record its public key as `keys/pub/k2.pub`.
5. Replace the compose secret file, set `SIGNING_KID=k2`, `docker compose -f docker-compose.yml up -d api`.
6. Make one decision so a `k2` checkpoint exists, then verify the full chain: `AUDIT_PUBLIC_KEYS_DIR=keys/pub python -m actionproof.audit verify` (k1 and k2 checkpoints each against their own key).
**Remaining limit:** a leaked OLD key lets an attacker forge checkpoints that verify under its `kid`; retire it from the directory only after archiving the verified output line (step 2).

## 3. Backup and restore (Postgres, including the audit chain)
The audit chain (`audit_log`, `audit_checkpoints`) lives in the same database, so one dump covers it.
```bash
docker compose -f docker-compose.yml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > actionproof-$(date +%F).dump
# restore into an EMPTY database (stop api first):
docker compose -f docker-compose.yml stop api web
docker compose -f docker-compose.yml exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' < actionproof-2026-01-01.dump
docker compose -f docker-compose.yml up -d api web
```
After every restore run the audit verify (section 4); a restore from a truncated dump is detected only if a checkpoint
beyond the truncation point exists elsewhere, so store the latest `audit: OK (N entries, M checkpoints)` line off-box
after each backup. Back up the signing key separately and offline; never inside the database dump.

## 4. Audit verify
```bash
docker compose -f docker-compose.yml run --rm api python -m actionproof.audit verify --public-key "<base64 public key>"
# local: python -m uv run python -m actionproof.audit verify    (AUDIT_PUBLIC_KEY_PATH=keys/dev-signing.pub)
```
It needs only the database and the PUBLIC key. Exit 0 prints `audit: OK (N entries, M checkpoints)`. Exit 1 prints
`audit: FAILED at seq S: <reason>`; the reasons mean:
| Reason | Meaning |
|---|---|
| entry missing or out of order | a row was deleted or inserted (gap in seq) |
| prev_hash does not link | an entry was removed or reordered |
| entry_hash does not recompute | a row was edited after it was written |
| checkpoint refers to a missing entry (log truncated) | the tail was cut off; a signed checkpoint remembers it |
| checkpoint head_hash does not match | history before the checkpoint was rewritten |
| checkpoint signature invalid | wrong public key (check the rotation boundary) or forged checkpoint |
| cannot read the audit log | database unreachable or tables missing: not verified counts as failed |

## 5. Incident playbooks
Principle: every failure here is DENY; nothing is "temporarily allowed".

**Suspected signing-key exposure** (G1+G2). 1) `docker compose -f docker-compose.yml stop api` (no new receipts). 2) Run
audit verify with the current public key and save the output. 3) Rotate (section 2) with a NEW key on a clean host;
the old key is compromised, so treat any receipt signed by it as untrusted: let them expire (`RECEIPT_TTL_SECONDS`,
`REVIEW_RECEIPT_TTL_SECONDS`) and re-prepare. 4) Review audit entries since the suspected exposure for commits nobody
decided in the console. 5) Find how it left (the key is mounted only into `api`; the agent has no tool that reads it, invariant 6).

**Audit verify fails.** Stop writes (`stop api`). Take a `pg_dump` of the current state as evidence first. Read the
failing seq and reason (table above). Compare with the last good line and the last backup; restore only after the
evidence copy exists. Do not "repair" rows by hand: that is the tampering the chain exists to expose.

**Quarantine release.** A commit whose upstream tool call was burned/rolled back quarantines its record (ADR-014). A
human first checks the tool's real outcome, then calls `Gate.release_quarantine(record_id, reviewer)` (admin side; it
writes a `release_quarantine` audit entry in the same transaction, and returns whether a row was released):
There is no CLI wrapper yet: in `docker compose ... run --rm api python`, build the gate with `actionproof.server.build_app(load_settings(), load_server_settings(need_principal=False)).gate` and call `release_quarantine`. Never release without confirming the upstream outcome.

**Stuck pending reviews.** Check `GET /api/queue?status=pending` (console) or `SELECT request_hash, created_at FROM pending_reviews WHERE status='pending'`.
Reviews expire with their receipt and token (`REVIEW_TOKEN_TTL_SECONDS`); an expired one cannot be approved, the agent
must re-prepare. If the console shows `pending` for an already EXECUTED commit, `review.reconcile` (run on each queue
read) repairs it. Do not edit `pending_reviews` by hand.

**OPA down = everything DENY, by design.** The gate calls OPA with `OPA_TIMEOUT_SECONDS`; timeout or error = DENY
`AP-POL-FAIL` (G1). Symptom: all prepares denied with that rule. Check `docker compose -f docker-compose.yml ps opa` and
`logs opa`; the healthcheck is `GET /health`. Fix OPA, not the gate. Never raise the timeout to mask a slow policy.

**Console lockout / login abuse.** Lockout is per (login, client IP), in memory, 5 failures / 300 s; restart `api`
clears it. Behind the Next proxy every client shares the proxy's IP, so a lockout there is global per login.

## 6. CI
`.github/workflows/ci.yml`: the first job is named exactly `USP: proof before permission` (`pytest tests/usp tests/redteam`
against Postgres 16 + OPA + tesseract); every other job `needs` it. Python "lint" is `python -m compileall -q src`; adding
ruff (or any new dev dependency) needs the owner's approval first. e2e and Lighthouse run against the production
compose file (`docker/ci-stack.sh`: throwaway key and password). Playwright and axe are installed with `--no-save` in CI
until `@playwright/test` and `@axe-core/playwright` are added to `web/package.json` (see `web/README.md`).
