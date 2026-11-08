# ActionProof web: design system

Product: a gate in front of an AI agent's writes. **Proof before permission**: no value authorizes a write unless its
derivation re-checks (G1), and no approval can be replayed (G2). Audiences: developers shipping agents, finance and
ops reviewers, security and compliance (deck slide 9). The site has three jobs: say the idea in 3 seconds (hero,
S1.2), show the evidence (`/evaluation`, every number fetched from `/api/public/eval`), and run the review
console (`/console`, S7.8, S9.2, S9.6).

Stack: Next.js 16 App Router + React 19 + TypeScript, Turbopack; `three` / `@react-three/fiber` / `drei` for the one
3D scene, `gsap` (ScrollTrigger) + `lenis` for scroll, `zustand` for console state. Plain CSS tokens in
`app/globals.css`; no UI library.

## Three concepts (design-manual / awwwards Phase 1)

| | A. Interlock (chosen) | B. Chain of custody | C. Night shift |
|---|---|---|---|
| Idea | The gate is a machine interlock: a request cannot pass until every value latches against its source. | The audit hash chain is the page spine; every section is an entry stamped onto a ledger. | A full-dark control room; decisions scroll by as traces on an oscilloscope. |
| Territory | the product's own mechanism (interlock, latch, signal lamp) | the profession's material (evidence, ledgers, stamps) | place (an ops floor at night) |
| Signature | Hero: a slowly rotating sphere of request particles drifts into a gate plane; each one lights ALLOW / REVIEW / DENY as it crosses. | Scroll stamps each section onto the chain; the hash of the previous entry prints into the next. | A sweep line crosses a live trace; spikes are DENYs. |
| Emotion (3 s) | calm machine, loud lights | bureaucratic certainty | vigilance |
| Motion verb | latch | stamp | sweep |
| Anchor | the gate really returns exactly one of three decisions with a rule id | the audit chain really is hash-linked with signed checkpoints | reviewers really watch a queue |
| Originality / fit / feasibility / portability (1-5; portability lower is better) | 4 / 5 / 4 / 2 | 4 / 3 / 4 / 2 | 2 / 3 / 5 / 4 |

**Chosen: A, Interlock.** It is the only concept where the signature moment is the product's actual output (three
decisions, each with a reason), and it keeps the deck's look: ink, amber, mono labels like the slide-1 intercept card.
B is kept as a secondary device: the audit section of the console uses ledger rows. C was cut: dark-only reads as
the generic "AI terminal" default.

### Concept card
```
Idea:        Nothing an agent writes passes until it latches against its source.
Metaphor:    an industrial interlock on an instrument chassis, with signal lamps
Signature:   hero particle sphere -> gate plane; particles take a lamp colour only when decided (7.2, R3F scene)
Emotion:     a quiet machine with loud lights
Motion verb: latch (short travel, then a hard stop; nothing floats, nothing bounces)
Screenshot:  carbon band, display headline left, the sphere right with one red square-lit particle held at the plane
```

## What came from each reference, and what changed
Notes and sources: `web/reference/README.md`.

| Reference | Taken | Changed |
|---|---|---|
| Industrial catalogue (Refero style aecf9dda) | 0px radius, no shadows, no gradients; 1px hairlines as structure; mist `#f6f8f7` canvas with near-black bands; colour rationed to states; left alignment | band is the deck's ink `#15141f` (not `#0f0e12`); weight-100 body rejected for readability (17px / 400); one warning colour became a 3-signal system with shapes and words; 4px spacing base |
| Cinematic hero (Refero style 21cfe0c1) | rotating particle sphere as the hero; display type at weight 500, -0.04em, line-height under 1; one kinetic size | teal palette and both gradients rejected; radii rejected (0px); centered stack rejected (left-aligned on the grid); particles carry data (each is a request, colour = its decision); no uppercase tracked eyebrows |

Clichés deliberately avoided: the purple-blue AI gradient, and the rounded SaaS card kit with soft shadows. Also not
used: uppercase eyebrows above every heading, decorative 01/02/03 (the only numbered list is the real five-beat
demo sequence).

## Palette by role
All values are CSS custom properties in `app/globals.css`. `.band-carbon` re-points the same role names, so
components never branch on theme.

| Role | Token | Mist (default) | Carbon band |
|---|---|---|---|
| ground | `--c-ground` | `#f6f8f7` mist | `#15141f` ink (deck) |
| raised surface | `--c-paper` | `#ffffff` | `#211f2d` |
| text | `--c-ink` | `#15141f` | `#f6f8f7` |
| muted text | `--c-muted` | `#55535f` | `#a9a7b4` |
| hairline | `--c-line` | `#c9ccd0` | `#3a3846` |
| primary action fill | `--c-accent` | `#f5a524` amber (deck), ink text | same |
| focus ring | `--c-focus` | `#15141f` | `#f5a524` |
| ALLOW | `--sig-allow` | `#0b6b35` (ink) | `#3ddc84` (lamp) |
| REVIEW | `--sig-review` | `#7f4d00` (ink) | `#f5a524` (lamp) |
| DENY | `--sig-deny` | `#b3261e` (ink) | `#ff5a4a` (lamp) |

Amber is both the deck accent and the REVIEW lamp on purpose: REVIEW is the hero beat (INV-2048 pauses for a human).
The primary CTA is amber because the next action on the site is always "look at the evidence"; a CTA is never shaped
like a signal (no circle/triangle/square), so it cannot be misread as a decision.

## Signal system
One colour per decision, and **never colour alone**: `<Signal state>` always renders colour + shape + word.

| Decision | Shape | Word | Meaning | In 3D (7.2) | In the console (7.3) |
|---|---|---|---|---|---|
| ALLOW | circle | ALLOW | executed once | emissive `#3ddc84` | `--sig-allow` mark + word |
| REVIEW | triangle | REVIEW | paused for a different person | emissive `#f5a524` | `--sig-review` mark + word |
| DENY | square | DENY | blocked, with rule id and G1/G2 | emissive `#ff5a4a` | `--sig-deny` mark + word |

Lamp colours are only for light on carbon (or as a solid plate with ink text: `<Signal solid>`); ink colours are for
marks and words on mist. Every DENY/REVIEW shown carries its rule id and guarantee (CLAUDE.md working rules), passed
as `label`.

## Contrast (WCAG 2.x, computed)
`npm run contrast` (`scripts/contrast.mjs`) recomputes these and exits 1 on any failure. Output, 2026-11-07:

| Pairing | Colours | Ratio | Required | Result |
|---|---|---|---|---|
| ink on mist | `#15141f` on `#f6f8f7` | 17.09 | 4.5 | pass |
| muted on mist | `#55535f` on `#f6f8f7` | 7.06 | 4.5 | pass |
| ink on paper | `#15141f` on `#ffffff` | 18.23 | 4.5 | pass |
| carbon text on carbon | `#f6f8f7` on `#15141f` | 17.09 | 4.5 | pass |
| carbon muted on carbon | `#a9a7b4` on `#15141f` | 7.70 | 4.5 | pass |
| carbon muted on carbon raised | `#a9a7b4` on `#211f2d` | 6.83 | 4.5 | pass |
| amber on carbon | `#f5a524` on `#15141f` | 8.93 | 4.5 | pass |
| ink on amber (CTA) | `#15141f` on `#f5a524` | 8.93 | 4.5 | pass |
| ALLOW ink on mist | `#0b6b35` on `#f6f8f7` | 6.21 | 4.5 | pass |
| REVIEW ink on mist | `#7f4d00` on `#f6f8f7` | 6.64 | 4.5 | pass |
| DENY ink on mist | `#b3261e` on `#f6f8f7` | 6.13 | 4.5 | pass |
| ALLOW lamp on carbon | `#3ddc84` on `#15141f` | 10.22 | 4.5 | pass |
| REVIEW lamp on carbon | `#f5a524` on `#15141f` | 8.93 | 4.5 | pass |
| DENY lamp on carbon | `#ff5a4a` on `#15141f` | 5.92 | 4.5 | pass |
| ink on ALLOW / REVIEW / DENY lamp plate | `#15141f` on lamps | 10.22 / 8.93 / 5.92 | 4.5 | pass |

Hairlines (`#c9ccd0` on mist, 1.51) are decorative structure, not the only boundary of any control: every control
also has a 1px ink border or a text label. DENY vs ALLOW lamps differ by only 1.73 between themselves, which is why
the shape and the word are mandatory.

## Type
Two families via `next/font/google` (self-hosted at build, no runtime request): **Archivo** (400, 500) for display and
body, **IBM Plex Mono** (400, 500) for labels, rule ids, hashes, amounts in cards. Tabular numerals on.

| Role | Token | Size | Weight | Tracking | Leading |
|---|---|---|---|---|---|
| kinetic marker (one per page max) | `--fs-kinetic` | 80 -> 280px fluid | 500 | -0.04em | 0.85 |
| display (hero h1) | `--fs-display` | 52 -> 152px fluid | 500 | -0.04em | 0.92 |
| h2 | `--fs-h2` | 36 -> 64px | 500 | -0.03em | 1.05 |
| h3 | `--fs-h3` | 24 -> 32px | 500 | -0.015em | 1.05 |
| lede | `--fs-lede` | 19 -> 24px | 400 | 0 | 1.4 |
| body | `--fs-body` | 17px | 400 | 0 | 1.55, max 68ch |
| small | `--fs-small` | 14px | 400 | 0 | 1.5 |
| mono label | `--fs-mono` | 13px | 400/500 | +0.02em | 1.4, sentence case |

## Grid and spacing
- 12 columns, 24px gutter, max 1320px, margins `clamp(16px, 4vw, 64px)`; under 720px: 4 columns, 16px gutter, 16px
  side margin.
- Spacing scale (4px base): 4, 8, 12, 16, 24, 32, 48, 64, 96, 144 (`--s-1`..`--s-10`). Band padding 96px (64px mobile).
- Alignment: everything left-aligned to the grid; display type hangs on column 1; no centered paragraphs.
- Section rhythm alternates mist and carbon bands with a hard cut, never a gradient.

## Shape and surface
0px radius everywhere (enforced globally in CSS). 1px hairlines. No shadows, no gradients, no glass. Elevation is
only the jump from mist to carbon, or paper inside a hairline frame (`<Card>`).

## Motion
- Verb: **latch**. Short travel, then a hard stop. One easing family: `--ease-latch` `cubic-bezier(0.2, 0, 0, 1)`
  (release: `cubic-bezier(0.4, 0, 1, 1)`). Durations: snap 120ms (hover colour), latch 240ms (state change), travel
  480ms (reveal), scene 900ms (hero intro). Stagger 40ms.
- Hover on primary targets: ink fill floods the button (a treatment, not a colour swap on text). Press: 1px drop.
- Idle state: the hero sphere rotates slowly while nothing happens (one clock, GSAP ticker; paused off screen).
- Animate transform / opacity / clip-path / shader uniforms only. One ticker; no own `requestAnimationFrame` loops.
- `prefers-reduced-motion: reduce`: no smooth scroll (Lenis off), no 3D animation (static poster frame), no scrub;
  all content visible.

## Components (only what 7.2 / 7.3 need)
| Component | File | Notes |
|---|---|---|
| `<Signal state solid? label?>` | `components/ui/Signal.tsx` | colour + shape + word; `label` carries rule id + G1/G2 |
| `<Hairline strong?>` | `components/ui/Hairline.tsx` | 1px rule, `--c-line` or ink |
| `<MonoLabel as? muted?>` | `components/ui/MonoLabel.tsx` | instrument label; real information only |
| `<Band tone="mist" or "carbon">` | `components/ui/Band.tsx` | full-bleed section; carbon re-points all tokens |
| `<Card as?>` | `components/ui/Card.tsx` | paper + hairline frame |
| `.button`, `.button-primary` | `app/globals.css` | 44px min target, ink flood on hover |

21st-ui primitives: **none used**. The five primitives above are each a few lines over the tokens; importing a
registry component would add markup and styles to restyle and gives nothing 7.2/7.3 need yet. The two-primitive
allowance stays unspent (revisit for the console's combobox filter in 7.3 if a native `<select>` is not enough).

## Mobile
4-column grid, display type scales down to 52px, the hero sphere moves under the headline at reduced particle count,
nav stays one row of three links (44px targets), console tables become stacked rows.

## Data rule
CLAUDE.md invariant 7: every number on screen is fetched from the backend (`lib/api.ts`, types generated from
`web/openapi.json` by `npm run gen:api`). The site never embeds an eval result, a latency or an amount in source.

## References
- `web/reference/industrial-catalogue.md`: https://styles.refero.design/style/aecf9dda-5cba-4dc7-9e73-59b65d895cdf
- `web/reference/cinematic-hero.md`: https://styles.refero.design/style/21cfe0c1-778d-4613-9f47-a5718eb929b3
- The CodeQuest 2026 deck (ink `#15141f`, amber `#f5a524`, slide-1 intercept card mono labels).

## Console
Built in task 7.3 (S7.8, S9.2, S9.6, S4.5). Routes: `/console` (queue), `/console/login`, `/console/requests/[hash]`,
`/console/audit`. Code: `app/(console)/console/**`, `components/console/**`, `lib/console-{auth,async,format,now}`.
No WebGL; the same tokens, 0px radius, hairlines and `<Signal>` marks as the site (carbon nav band, mist content).

- **Auth**: `AuthProvider` bootstraps from `GET /api/auth/me`; 401 sends the user to the login page. The session cookie is
  httpOnly and never read by JS; the CSRF token is read from the `ap_csrf` cookie and sent as `X-CSRF-Token` by `apiPost`
  on every POST. Bad credentials show one generic message; the form is `method="post"` so a pre-hydration submit cannot
  put the password in the URL. Navigation is role-aware (Queue/Audit only for reviewer/admin); roles that cannot read or
  decide get an explicit permission-denied state. The server remains the authority (403s are shown, not pre-empted).
- **Queue**: filters (status, tool, actor) and the opaque cursor live in the URL; arrow keys / Home / End move between
  rows, Enter opens. Under 720px the table stacks into labelled rows.
- **Request**: label line `requested by <actor> for <on_behalf_of> · approved by <reviewer> (different person)` built
  from API fields (the "approved by" tail only after a decision by a reviewer). Each argument shows claim badge
  (DIRECT/DERIVED/ASSERTED), source (doc, page, bbox or pointer / derivation), verification (method, rule id + G1/G2).
  ASSERTED and tainted values are struck-through grey and labelled "not evidence". Source pages are `<img>` of the
  server PNG; the overlay rectangles are positioned in percent (`bbox * zoom / natural size`), so they follow any rendered
  size or resize with no JS. Hover or focus on a claim row highlights its rectangle and vice versa.
- **Decision**: reason (min 8, max 500, client and server) then an explicit confirm step; double-submit is disabled;
  no optimistic UI, the outcome (EXECUTED / REJECTED / DENY with rule id + guarantee) is rendered from the response in an
  `aria-live` region and the request is then refetched.
- **Audit**: recent entries plus "Verify chain", which shows exactly `entries`/`checkpoints` or the `error` string from
  `GET /api/audit/verify`; a transport failure is shown as an error, never as a result.

Deviations: (1) `PAGE_ZOOM = 2` and the reason limits 8/500 are mirrored constants in `lib/console-format.ts` (the API
does not publish the page size in points or the limits in a field the UI can read); (2) the PNG the server returns
already has its own red rectangles drawn, the UI adds interactive overlays on top; (3) relative ages use the browser
clock against the API's `created_at`; (4) the tool filter options are the enum from the generated query type.

## Site (public pages, task 7.2)
Built: `/` (hero, four-chapter 3D scroll story, who benefits, expected impact, "What ActionProof does not claim",
closing line) and `/evaluation`. Files: `app/(site)/**`, `components/site/**`, `lib/site-{story,data,copy}.ts`.

- **One driver**: `lib/site-story.ts`. A zustand store holds `progress`, `chapter`, `step`, the capability flags and the
  fetched INV-2048 replay. Lenis is stepped by `gsap.ticker`; ScrollTrigger writes the store; the R3F `<Canvas
  frameloop="never">` is advanced from the same ticker (`TickerBridge`) and reads the store with `getState()` in
  `useFrame` (no React subscription). Rendering pauses off screen and in hidden tabs.
- **Scene** (`StoryScene.tsx`, `next/dynamic` ssr:false): procedural points sphere (2600, 900 on mobile) drifting into a
  gate bar; three lamps = circle / triangle / square, lit from token colours. The lamp for the recorded decision lights
  and the gate bolt travels only at step 3 (after the G1 re-derivation); the DENY lamp lights only if the payload holds a
  G2 reason. The DOM legend carries the words.
- **Signature**: chapter 4 sticky panel (`ReplayProof.tsx`) shows claims, the G1 re-derivation (operands resolved from the
  record's own claims, recomputed with BigInt cents), the decision with rule ids, and the G2 bounce. All from
  `GET /api/public/replay/inv-2048`. States: loading, error with retry, 404 -> "No recorded decision yet". The slide-2
  example amounts are filled from the same record.
- **Fallbacks**: `prefers-reduced-motion`, no WebGL, or a scene crash -> static chapters + `StaticSignals` SVG, no Lenis, no
  scrub; every proof step is open. Touch: Lenis off, fewer particles, dpr 1. Skip link is the root layout's.
- **/evaluation** (`EvalView.tsx`): all content from `GET /api/public/eval`; `available:false` -> "Evaluation not run yet".
  The CaMeL-style row is labelled "typical design, not measured". Generated set empty -> "absent: the independent
  generator was blocked". Targets, met/missed, commit and run time come from the payload.

Deviations: (1) the OpenAPI type of `results` is a free dict, so `lib/site-data.ts` declares its assumed shape (eval/run.py) once
and validates the top level at runtime; (2) hero text is server-rendered but the story starts after it (the canvas is not
behind the hero); (3) no screenshots, e2e or Lighthouse were run (build/typecheck/lint only); (4) the deck's `$` amounts
are not in source: they are formatted from the fetched claims; (5) `npm run lint` at the web root fails on the
untracked `security-headers.d.mts` (not mine); my paths lint clean.
