# Deploy on Render (free tier)

Live: https://actionproof-bw-web.onrender.com (web), https://actionproof-bw-api.onrender.com (API), https://actionproof-bw-opa.onrender.com (policy engine).

`render.yaml` is the Blueprint: one free Postgres (`actionproof-bw-db`) and three Docker web services (`-opa`, `-api`, `-web`). Render generates the
signing key and the four console passwords (`generateValue`); nothing secret is in git.

## What you need to know
- **Console logins:** Render dashboard -> `actionproof-bw-api` -> Environment -> `CONSOLE_PASSWORD_REV_ALICE`, `_REV_BOB`, `_SUB_USER123`,
  `_ADMIN_OPS` (logins: `rev-alice`, `rev-bob`, `sub-user123`, `admin-ops`). Only `rev-alice` and `rev-bob` can approve; `admin-ops` cannot.
- **Cold start:** free services sleep after about 15 minutes idle; the first request takes 30-60 s. The gate fails closed if OPA does not answer
  within `OPA_TIMEOUT_SECONDS` (3), which is why `SEED_ON_BOOT` can fail to park the demo review when OPA is asleep: wake OPA (open its `/health`),
  then redeploy the API; the seed is idempotent.
- **Public OPA:** the image (`Dockerfile.opa`) runs with `--authorization=basic` and `docker/opa/authz.rego`, which allows only the decision query,
  `/health`, and two read-only GETs (the loaded policy text and the OPA version, used for the policy revision).
- **Free database expires after 30 days** (Render). Back it up or recreate it; the demo data is re-seeded on boot.
- **Auto-deploy:** the Blueprint has auto-sync on; each push to `main` rebuilds the three services.
- **Limits:** one instance each, 512 MB; the signing key lives only in the API container (written from the generated secret at start, then removed from the environment).
