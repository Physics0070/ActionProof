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
