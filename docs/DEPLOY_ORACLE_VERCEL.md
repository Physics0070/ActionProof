# Deploy: Oracle Always Free VM (+ optional Vercel frontend)

Goal: free, always on, no sleeping, no recurring cost. **Status: written and syntax-checked, never run on Oracle.** The Docker
images in this repo have not been built on this machine either (no Docker daemon was running), so the first deploy is also the
first real build. Read "What is untested" before you rely on it.

## Why this shape
The gate is a Python service with Postgres features it cannot do without (`SERIALIZABLE`, `LOCK TABLE`, triggers, `numeric`,
`jsonb`), an OPA sidecar and a Tesseract binary. That needs a container host, not serverless. Turso (SQLite) cannot run it. Neon
could host the database but its free compute sleeps after 5 minutes and caps at 100 CU-hours a month, so a database on the same VM
is simpler and faster. Vercel is a good home for the Next.js app only.

```
visitor -> Vercel (Next.js, free)  --/api rewrite-->  https://<host> (Caddy, TLS)  -> api -> postgres
                                                                                      \-> opa
visitor -> https://<host>           (MODE=full: Caddy -> web -> api)
```

## 1. Oracle side (once)
1. Create an Oracle Cloud account (a card is required for verification). Choose your home region carefully: Always Free compute
   can only be created there.
2. Create a VM: shape **VM.Standard.A1.Flex** (Arm), 2 OCPU and 12 GB is plenty (4 OCPU / 24 GB is the Always Free maximum), image
   **Ubuntu 24.04**, boot volume 50 GB, add your SSH public key. If you get "out of host capacity", retry later or pick another
   availability domain.
3. Networking: give the instance a **reserved public IP**, and in the VCN's security list add **ingress** TCP 80, TCP 443 and
   UDP 443 from `0.0.0.0/0` (22 is already open; restrict it to your IP if you can).
4. Host name: with no domain, use `<ip-with-dashes>.sslip.io` (for `129.80.1.2` that is `129-80-1-2.sslip.io`). It resolves to the
   IP and Let's Encrypt will issue for it. A free DuckDNS name works too.
5. Stay inside the free limits: one A1 instance up to 4 OCPU / 24 GB, up to 200 GB of block storage in total, **no load
   balancer, no NAT gateway, no extra paid services**. Set a budget alert of 1 USD in the console as a tripwire.

### Idle reclamation (read this)
Oracle states that idle Always Free instances may be reclaimed: 95th-percentile CPU and network both under 20% over 7 days. A quiet
demo VM can meet that. Reports say upgrading the account to **Pay As You Go** (still free inside the Always Free limits) stops
reclamation; **this was not verified here**, check Oracle's current terms before relying on it. Do not "fix" it with fake load.
Keep backups (section 5) so a reclaimed VM is an inconvenience, not a loss.

## 2. Deploy the stack
On the VM:
```bash
git clone https://github.com/Physics0070/ActionProof.git && cd ActionProof
# Web on Vercel (recommended): the VM serves only /api/*
SITE_ADDRESS=129-80-1-2.sslip.io MODE=api WEB_ORIGIN=https://<your-project>.vercel.app bash deploy/oracle/bootstrap.sh
# or everything on the VM
SITE_ADDRESS=129-80-1-2.sslip.io MODE=full bash deploy/oracle/bootstrap.sh
```
The script installs Docker, opens the host firewall for 80/443, generates the Ed25519 signing key (prints only the public key),
the Postgres password and four console passwords (never printed: read `keys/console-logins.txt`), builds the images, starts the
stack and seeds the demo data and the hero review **once**. Secrets live only in `keys/` and `deploy/oracle/.env` (both
git-ignored, mode 0600/0444). Re-running it keeps them.

Details worth knowing:
* `WEB_ORIGIN` must equal the browser origin exactly (the Vercel URL, or `https://<host>` in full mode): the API's CORS and CSRF
  checks use it. `CONSOLE_COOKIE_SECURE=true` is set because TLS ends at Caddy.
* Everyone reaches the API from Caddy's (or Vercel's) address, and the public rate limiter is keyed by that address, so the limit is
  shared by all visitors. `RATE_LIMIT_PER_MINUTE` is therefore 600 in `deploy/oracle/.env`.
* `OPA_TIMEOUT_SECONDS=1` (default is 0.2). OPA stays warm on this VM; a timeout still fails closed (AP-POL-FAIL), it never allows.
* The signing key file is mode 0444 so the non-root container user can read it. That is acceptable on a single-tenant VM; to keep
  0400, `chown` it to `APP_UID`/`APP_GID` (docs/RUNBOOK.md).

## 3. Vercel side (MODE=api)
Import the repo in Vercel, then:
* **Root Directory:** `web`  - **Framework:** Next.js (detected)  - **Build command:** default (`next build --turbopack`).
* **Environment variables (Production, and Preview if you use it):**
  `NEXT_PUBLIC_API_BASE=/api`
  `CONSOLE_API_ORIGIN=https://129-80-1-2.sslip.io` (the VM, no path, no trailing slash)
  `NEXT_PUBLIC_SITE_URL=https://<your-project>.vercel.app`
  `NEXT_PUBLIC_REPO_URL=https://github.com/Physics0070/ActionProof`
  These are read at build time (`next.config.ts` rewrites `/api/*` to the VM, so cookies stay first-party). Changing the VM address
  means a redeploy.
* The Hobby plan is for non-commercial use. A custom domain can be added later; then update `WEB_ORIGIN` on the VM and re-run
  `bootstrap.sh` (it refreshes the three values) or edit `deploy/oracle/.env` and `docker compose ... up -d api`.
* Each deployment gets its own preview URL; only the production URL is accepted by the API (`WEB_ORIGIN`).

## 4. Check list (after every deploy)
```bash
curl -fsS https://<host>/api/health                       # {"ok":true}
curl -fsS https://<host>/api/public/eval | head -c 200    # the evaluation payload
curl -fsS https://<host>/api/public/replay/inv-2048 | head -c 200
curl -sS -o /dev/null -w "%{http_code}\n" https://<host>/  # api mode: 404 (only /api/* is exposed); full mode: 200
docker compose -f docker-compose.yml -f deploy/oracle/compose.caddy.yml --env-file deploy/oracle/.env ps   # all healthy, init exited 0
```
Then in the browser: the home page loads the story with real numbers; sign in at `/console/login` with a login from
`keys/console-logins.txt`; open the pending INV-2048 review as `rev-alice`, approve it (this really runs the write once), and
check `/console/audit`. A review can be approved only once; restarting the stack never re-parks or resets it.

## 5. Operate
* **Update:** `bash deploy/oracle/update.sh` (backup, `git pull --ff-only`, rebuild, restart). **Rollback:** `git checkout <commit>` and run it again.
* **Backup:** `bash deploy/oracle/backup.sh`; schedule it with cron (see the script header) and **copy dumps off the VM**.
  Restore and the post-restore audit check: docs/RUNBOOK.md section 3.
* **Logs:** `docker compose ... logs -f api caddy`.
* **Resetting the demo** (wipes the audit chain, on purpose only): run `DEMO_SEED=1 docker compose ... up init` then set
  `SEED_ON_BOOT=1`, restart `api`, and set it back to 0. A normal restart never resets anything.
* **Key rotation, anchoring, reconciliation:** docs/RUNBOOK.md, docs/DECISIONS.md (ADR-020, ADR-021, ADR-024).
* **Remote anchor (ADR-030):** not part of this stack. An anchor on the same VM is not an independent trust domain;
  run `python -m actionproof.anchor_publisher run` against an append-only service in another account (its own
  `ANCHOR_REMOTE_TOKEN`, https), and `... check` from a separate monitoring host. Untested against any real provider.

## What is untested
* The images (`Dockerfile.api`, `web/Dockerfile`) were never built here, and nothing ran on Arm. Base images are multi-arch
  (python:3.12-slim, node:22-alpine, postgres:16, OPA, caddy, uv); Tesseract comes from apt on Debian.
* `bootstrap.sh`, `backup.sh`, `update.sh`: `bash -n` passed and `docker compose config` resolves the layered files with the
  expected values; none of it was executed. Caddy's config was not validated with `caddy validate`.
* Let's Encrypt via sslip.io (shared rate limits can apply to that domain), Oracle's iptables behaviour on your image, the
  Vercel rewrite to the VM under real traffic, and Oracle's reclamation rules.
* Free tiers change. Re-read Oracle's Always Free page and Vercel's Hobby terms before depending on them.
