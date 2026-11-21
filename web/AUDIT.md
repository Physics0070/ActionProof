# Frontend audit (stage 1) and status

Scope of this audit, so the findings are not over-read: the previous home page was inspected in the browser at one
small viewport and from source; `/evaluation` and `/console/login` were screenshotted at 1440 in the final run; the
authenticated console screens (`/console`, `/console/requests/[hash]`, `/console/audit`) were inspected from source and
NOT yet screenshotted with live data. The backend contract (`lib/api-types.ts`, generated from OpenAPI) was not touched.

## Routes
| Route | What it is | Backend data | Look today | Status |
|---|---|---|---|---|
| `/` | story: problem, evidence, policy, strike, audit, reveal | `GET /api/public/replay/inv-2048` | Assay (new) | redesigned |
| `/evaluation` | one headline, a three-number strip, comparison bars, details | `GET /api/public/eval` | Airlock (spruce, pink) | not yet |
| `/console/login` | sign in | `POST /api/auth/login` | Airlock | not yet |
| `/console` | review queue | `GET /api/queue` | Airlock, light | not yet |
| `/console/requests/[hash]` | the review workspace and decision bar | request detail, decision POST | Airlock, light | not yet |
| `/console/audit` | audit verification and entries | `GET /api/audit/*` | Airlock, light | not yet |
| `*` | designed 404 | none | Airlock | not yet |

## Findings on the previous home page (fixed by the redesign)
1. Dense: five chapters of small text and tables carried the story; the scene was one corridor and a door.
2. The 3D scene drew an invented corridor; only the packet's chips came from the recorded decision.
3. Hero text and scene competed: the headline sat over the busiest part of the picture.
4. Fallback (reduced motion, no WebGL) was a column of small SVG posters with no designed composition.

## Findings that remain (open)
1. **Two visual systems.** The home page is obsidian and bone; `/evaluation` and the console are spruce and pink. Moving
   between them reads as a different product. (Cross-route.)
2. **`/console/login`:** the heading touches the top edge of its card (no padding above the h1); the decorative concentric
   frames pass behind the form and add noise to the one screen that must be calm.
3. **`/evaluation`:** content is strong (real numbers from the backend) but is typeset in the old system; the comparison
   bars use one accent for "ActionProof" and a near-identical sage for every baseline, so the difference between arms is
   carried by length only.
4. **Console (from source, unverified visually):** queue, review workspace and audit view use the light `band-mist`
   tokens; `AuditView.tsx` shows verification and entries but not the hash-chain relationships, checkpoint rows or the
   anchored/unanchored range that now exist in the backend (`audit verify --anchor`); that range is not exposed by any
   API route today, so it cannot be shown without a backend change.
5. **No dashboard route exists.** The brief asks for a live security dashboard with execution feed, incidents and
   connector/worker health. The backend has no endpoints for most of those (no metrics, no execution states, no
   connectors), so they cannot be built honestly without new backend work. The review queue is the closest real thing.
6. **Tests:** no JS unit test runner is installed (`package.json` has none); `e2e/*.spec.ts` need `@playwright/test`, which
   is not a dependency, and a running stack. They were not run. The checks in "Verified" below were scripted outside the
   repo with `playwright-core` against the production build.

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
