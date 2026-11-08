# ActionProof web

Public site (`/`, `/evaluation`) and the review console (`/console`) for ActionProof. Next.js 16 (App Router,
Turbopack), React 19, TypeScript. Design system: `DESIGN.md`.

## Run with the backend
1. Backend (repo root): Postgres + OPA up, `python scripts/demo_seed.py --reset`, `python scripts/seed_console.py`,
   then `python -m actionproof.console` (serves `127.0.0.1:${CONSOLE_PORT}`, default 8766).
2. Web env (from the web section of the root `.env.example`), e.g. in `web/.env.local` (git-ignored):
   ```
   NEXT_PUBLIC_API_BASE=/api
   CONSOLE_API_ORIGIN=http://127.0.0.1:8766
   ```
   Both are required; `next dev` / `next build` stop with `ConfigError: ... <NAME>` if either is missing.
   Git Bash on Windows rewrites `/api` passed on the command line into a Windows path; use `.env.local` or
   `MSYS_NO_PATHCONV=1`.
3. `cd web && npm install && npm run dev` -> http://localhost:5173 (matches the backend's `WEB_ORIGIN`).

The browser only talks to its own origin: `next.config.ts` rewrites `NEXT_PUBLIC_API_BASE/*` to
`CONSOLE_API_ORIGIN/api/*`, so the `ap_session` / `ap_csrf` cookies stay first-party (SameSite=Strict).

## Scripts
| Script | Does |
|---|---|
| `npm run dev` | dev server (Turbopack), port 5173 |
| `npm run build` / `npm start` | production build / serve it |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint (next config) |
| `npm run gen:api` | regenerate `lib/api-types.ts` from `openapi.json` (run after `python scripts/gen_openapi.py`) |
| `npm run contrast` | recompute the WCAG contrast table in `DESIGN.md` |

## API types
Never hand-write a response type. `openapi.json` is generated from the FastAPI app; `lib/api-types.ts` is generated
from it; `lib/api.ts` (`apiGet`, `apiPost`, `pagePngUrl`) is typed against it and sends `X-CSRF-Token` on POSTs.

## Ship: security headers, image, e2e, Lighthouse
**Security headers** live in `security-headers.mjs` (CSP, nosniff, no-referrer, frame-ancestors none, COOP/CORP,
minimal Permissions-Policy; the `/api` proxy path is excluded). The CSP tradeoff (static `'unsafe-inline'` for Next's
inline bootstrap scripts vs. a per-request nonce via `proxy.ts`/`cspWithNonce`, which makes pages dynamic) is stated
at the top of that file. It is wired in `next.config.ts` (together with `output: "standalone"` for `web/Dockerfile`):
```ts
import { headers } from "./security-headers.mjs";
const nextConfig: NextConfig = { output: "standalone", headers, /* ... */ };
```
**Image**: `docker build --build-arg NEXT_PUBLIC_API_BASE=/api --build-arg CONSOLE_API_ORIGIN=http://api:8766 -t actionproof-web web`
(normally via the root `docker-compose.yml`; see `docs/RUNBOOK.md`).

**e2e** (`e2e/*.spec.ts`, `playwright.config.ts`) runs against a running stack (`bash docker/ci-stack.sh` from the
repo root). Add the dev deps once and commit the lockfile, then add the script:
`npm i -D @playwright/test @axe-core/playwright` and `"e2e": "playwright test"`. Env: `E2E_BASE_URL`,
`E2E_REVIEWER_LOGIN`, `E2E_REVIEWER_PASSWORD`, `E2E_MINT_CMD` (prints `{"request_hash": ...}`; compose:
`docker compose -f docker-compose.yml exec -T api python scripts/mint_review.py`). `e2e/` and `playwright.config.ts`
are excluded from `tsconfig.json` so `next build` and `npm run typecheck` do not need Playwright installed.
UI specs select by accessible name (labels "login", "password", "reason", buttons "sign in", "approve", "reject",
"confirm"); keep those names or edit `e2e/helpers.ts`.

**Lighthouse** budgets are in `lighthouserc.json` (mobile LCP < 2.5 s, CLS < 0.05, performance >= 0.85,
accessibility and best-practices >= 0.95); CI runs `npx @lhci/cli autorun --config=web/lighthouserc.json`, no repo dependency.
