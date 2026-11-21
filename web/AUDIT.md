# Frontend audit (stage 1) and status

Scope of this audit, so the findings are not over-read: the previous home page was inspected in the browser at one
small viewport and from source; `/evaluation` and `/console/login` were screenshotted at 1440 in the final run; the
authenticated console screens (`/console`, `/console/requests/[hash]`, `/console/audit`) were inspected from source and
NOT yet screenshotted with live data. The backend contract (`lib/api-types.ts`, generated from OpenAPI) was not touched.

## Routes
| Route | What it is | Backend data | Status |
|---|---|---|---|
| `/` | story: problem, evidence, policy, strike, audit, reveal | `GET /api/public/replay/inv-2048` | redesigned (Assay) |
| `/evaluation` | headline, three-number strip, comparison bars, details | `GET /api/public/eval` | restyled (palette, type) |
| `/console/login` | sign in | `POST /api/auth/login` | redesigned (two columns, no decoration) |
| `/console` | review queue | `GET /api/queue` | restyled (palette, type) |
| `/console/requests/[hash]` | the review workspace and decision bar | request detail, decision POST | redesigned: provenance per value, "exactly what you are approving", history |
| `/console/audit` | audit verification and entries | `GET /api/audit`, `GET /api/audit/verify` | redesigned: linked chain strip, entry detail, verification state |
| `*` | designed 404 | none | restyled (palette, type) |

## Findings on the previous home page (fixed by the redesign)
1. Dense: five chapters of small text and tables carried the story; the scene was one corridor and a door.
2. The 3D scene drew an invented corridor; only the packet's chips came from the recorded decision.
3. Hero text and scene competed: the headline sat over the busiest part of the picture.
4. Fallback (reduced motion, no WebGL) was a column of small SVG posters with no designed composition.

## Findings that remain (open)
1. **No dashboard route.** The brief asks for a live security dashboard with execution feed, incidents and connector/worker
   health. The backend has no endpoints for most of those, so they cannot be built honestly without new backend work.
2. **Audit explorer limits.** It shows the entries the API returns and the server's verification result. Per-entry
   checkpoints and the anchored/unanchored range (`audit verify --anchor`) are not exposed by any API route.
3. **No "request more evidence".** The decision API is approve or reject only.
4. **`/evaluation`** keeps its composition; the baseline bars differ from ActionProof by length and label, not by colour.
5. **Reviewer comments** are not part of the request detail the API returns, so the history lists none.
6. **Tests:** no JS unit runner is installed; `e2e/*.spec.ts` need `@playwright/test` and a running stack and were not run.
   The checks below were scripted outside the repo with `playwright-core` against the production build.

Fixed in this pass: the two visual systems (one token set now), the cramped login with its decorative frames, the sticky
decision bar's primary button turning dark-on-dark under the new tokens, 5 px of horizontal overflow at 360 px caused by the
header after the font change, and a CLS of 0.29 on a slow phone caused by the hero changing height between modes.

## Verified for the new home page (production build, local backend with the real seeded decision)
| Check | Result |
|---|---|
| `npm run lint`, `npm run typecheck`, `npm run build` | pass |
| Console errors and warnings at 1440, 1280, 1024, 768, 390, 360 (live) | none |
| Horizontal overflow at the same widths | none |
| Reduced motion and no-WebGL at 1440 and 390 | no canvas, complete story, no errors |
| CLS (desktop; phone profile with 4x CPU) | 0; 0 |
| First-load JS before the scene / after | 148 KB / 459 KB |
| Route math (`lib/assay.ts`): monotonic, packet at each station at each beat centre | pass (scripted check) |

Not verified: real-GPU frame rate (only software WebGL was available), Safari/Firefox, screen-reader pass, keyboard
traversal beyond tab order inspection, Lighthouse, and any touch-device behaviour on hardware.

## Verified for the console (production build, local backend, real gate)
| Check | Result |
|---|---|
| Sign in as `rev-alice` (dev-only password, local database) | pass |
| Open the pending INV-2048 review, type a reason, Approve, Confirm approve | the page shows EXECUTED; the history then lists the approval with its time; audit entries mint, commit, review appear in the chain strip |
| Overflow at 1440 and 390 on login, queue, request, audit | none |
| `npm run lint`, `typecheck`, `contrast` (28 pairings), `build` | pass |
Not verified: Reject flow in the browser, the REVIEW token expiry path, keyboard traversal of the chain strip beyond a
code read, screen readers, other browsers.
