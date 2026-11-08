# ActionProof web: design system ("Airlock")

Product: a gate in front of an AI agent's writes. **Proof before permission**: no value authorizes a write unless its
derivation re-checks (G1), and no approval can be replayed (G2). Audiences: developers shipping agents, finance and
ops reviewers, security and compliance. Three jobs: say the idea in 3 seconds (hero), show the evidence
(`/evaluation`, every number fetched from `/api/public/eval`), run the review console (`/console`).

Stack: Next.js 16 App Router, React 19, TypeScript, Turbopack. `three` + `@react-three/fiber` for the one scene,
`gsap` (ScrollTrigger) + `lenis` for scroll, `zustand` for the story driver and console state. Plain CSS tokens in
`app/globals.css`; no UI library.

## What changed and why
The first site (navy and amber "Interlock") read as dense: eight chapters of small grey text, tables as the main
content, a small particle sphere, a decision buried at the bottom of the console. The rebuild keeps every claim
exactly as worded in `lib/site-copy.ts` and changes layout, type, colour, motion and order only: 5 chapters instead
of 8, one scroll-driven 3D moment that IS the five steps, big type (display up to 9.5rem, body 18px), one call to
action. `/evaluation` is one headline, a three-number strip, five comparison rows and `<details>`. The console leads
with a plain verdict and a sticky decision bar; ids, hashes and diffs moved into expandable sections.
Kept from the old system because they are about correctness: signals = colour + shape + word, AA contrast,
reduced-motion and no-WebGL fallbacks, 0 hardcoded numbers (invariant 7).

## Three concepts (awwwards Phase 1)
| | A. Airlock (chosen) | B. Customs desk | C. Patch bay |
|---|---|---|---|
| Idea | The gate is a bulkhead door in a corridor; a request packet must re-derive its numbers before the door moves. | Every action is a passport: stamped, refused or sent to a booth. | The audit chain is a switchboard; calls plug in and out. |
| Territory | the product's mechanism (door, latch, one-use token) | the profession's material (stamps, queues) | place and metaphor (telephone exchange) |
| Signature | Scroll INTO the gate: packet, re-derivation at the door, door opens to the decision light, a replayed receipt bounces. | A stamp slams onto a document at scroll. | Cables snap into sockets as sections arrive. |
| Emotion | calm pressure, then release | bureaucratic certainty | tactile order |
| Originality / fit / feasibility / portability (lower better) | 4 / 5 / 4 / 2 | 3 / 3 / 5 / 3 | 4 / 3 / 3 / 3 |
| Anchor | the gate really has one door, one-use receipts, and an audit entry for the bounce | reviewers really approve or reject | the audit log really is hash-linked |

**Chosen: A.** It is the only concept where the signature moment is the product's real behaviour (G1 before the door
moves, G2 on the replay), and it can be driven by data fetched from the gate.

### Concept card
```
Idea:        Nothing an agent writes passes the door until its numbers re-derive on screen.
Metaphor:    an industrial airlock: a corridor, station rings, a bulkhead door, signal light behind it
Signature:   scroll into the gate (home chapter 3): packet -> re-derive $4,800 - $4,300 = $500 -> door opens ->
             a copy of the receipt returns and bounces off the closed door in the DENY colour
Emotion:     pressure that releases; a quiet machine with loud light
Motion verb: latch (a bolt slides, then stops hard; nothing floats or bounces)
Screenshot:  spruce corridor, a hot pink packet at a shut door, the equation large on the left
```

## Palette by role
Colours are CSS custom properties in `app/globals.css`. `.band-carbon` (spruce) re-points the role names for the dark
public site; `.band-mist` and `:root` are the light set (console, problem chapter). Components never branch on theme.

| Role | Token | Light (mint) | Spruce (dark) |
|---|---|---|---|
| ground | `--c-ground` | `#e7f2ec` mint | `#0a2b26` spruce |
| raised surface | `--c-paper` | `#ffffff` | `#11403a` pine |
| ink | `--c-ink` | `#0a2b26` | `#eef8f3` frost |
| muted | `--c-muted` | `#416257` | `#a4c9be` sage |
| line | `--c-line` | `#b7d0c5` | `#2d6157` moss |
| accent ("packet pink") | `--c-accent` | `#ff3d9a`, ink text `#0a2b26` | same |
| ALLOW | `--sig-allow` | `#00604d` (ink) | `#34f0c2` (lamp) |
| REVIEW | `--sig-review` | `#6b4f00` (ink) | `#ffd11a` (lamp) |
| DENY | `--sig-deny` | `#b3260a` (ink) | `#ff7d52` (lamp) |

Why these: spruce is industrial safety-wall green, a colour nobody photographs; pink is the one hue no plant uses, so
the request (the packet, the CTA, the unexplained $500) is unmistakable; the three signals are aqua, sun yellow and
flare orange so they stay apart from the pink and from each other. Not the purple-blue AI gradient, not cream and
terracotta, not acid green on black (the ground is a rich green and ALLOW is an aqua light). Pink is never shaped like
a signal; a CTA is a rectangle with a word.

## Signal system
One colour per decision, never colour alone: `<Signal state>` renders colour + shape + word.
ALLOW = circle, REVIEW = triangle, DENY = square. In 3D the same three light up behind the door (REVIEW, then ALLOW
when the recorded request executed; DENY on the bounce). Every DENY or REVIEW shown carries its rule id and guarantee.
On `/evaluation` the same marks read Yes or Met (circle), Partial or Not measured (triangle), No or Missed (square).

## Type
next/font, self-hosted at build. **Bricolage Grotesque** 700/800 for display and headings, **Archivo** 400/500/600 for
body (18px, 1.55), **IBM Plex Mono** 400/500 for labels, rule ids, hashes.

| Role | Size | Tracking | Leading |
|---|---|---|---|
| display (hero h1) | clamp 52px to 152px (9vw) | -0.045em | 0.9 |
| h2 | clamp 40px to 96px | -0.035em | 0.95 |
| h3 | clamp 24px to 36px | -0.02em | 1 |
| lede | clamp 20px to 28px | 0 | 1.35 |
| body | 18px | 0 | 1.55, max 62ch |
| mono label | 13px | +0.02em | 1.4 |

## Layout and chapters (home)
1. **Start**: server-rendered hero (USP, title, sub, one CTA). The scene shows through on the right.
2. **The problem**: three slips (invoice, purchase order, the pink unexplained slip), then the three gaps. Amounts come from the fetched claims.
3. **The gate**: a 560vh pinned (CSS sticky) stage. Five stations = the five deck steps; each shows its deck line and a readout from the real INV-2048 record. Step 2 re-derives the amount in the browser (BigInt cents) and the door only opens if every DERIVED value matched (`verified` in the store).
4. **Claims**: pink full-bleed chapter, DIRECT / DERIVED / ASSERTED as three cards, then the taint rule.
5. **Proof**: USP line, one CTA ("See a real decision", /console), a quiet link to /evaluation, who benefits, impact, the four limits, the closing line.

A slim chapter rail on the right (labels on hover or focus); the skip link is first in tab order.

## Motion
- Verb: **latch**. One easing family `--ease-latch` cubic-bezier(0.2,0,0,1); snap 120ms, latch 220ms, travel 480ms.
- Buttons: a fill bolt slides in from the left and stops (transform only); press drops 2px; links get a sliding underline bar; cards step 6 to 8px. Every target has hover, focus-visible (3px ring) and active states.
- One driver: `lib/site-story.ts` (zustand `hero`, `gate`, `chapter`, `verified`) plus `lib/gate-timeline.ts` (a pure map from `gate` 0..1 to camera, packet, door, light, bounce). Lenis is stepped by `gsap.ticker`; the R3F loop (`frameloop="never"`) is advanced from the same ticker, only while the hero or the gate is on screen. No own rAF, no scroll listeners.
- Idle: the packet bobs and loops in the hero, rings and the door seam breathe, trail points drift (same clock).
- Procedural only: lines, boxes, one halo shader. No textures or models. The scene mounts 400ms after hydration (dynamic import, ssr:false); the hero text never waits for it.

## Fallbacks (designed on purpose)
- **prefers-reduced-motion**: no Lenis, no scrub, no canvas. All five stations are shown expanded with their readouts next to a still SVG poster of the same story (`StaticGate`). Checked at 1440 and 390.
- **No WebGL or WebGL failure**: identical to reduced motion (the scene boundary flips `caps.webgl`).
- **390px phone**: single column; the gate stage keeps the door in the top half and the active station card at the bottom (only the active station is shown); the 3D uses 1x DPR, a wider lens and a shorter corridor; no horizontal overflow on any page.

## Contrast (WCAG 2.x, computed by `npm run contrast`)
| Pairing | Colours | Ratio | Required | Result |
|---|---|---|---|---|
| ink on mint ground | `#0a2b26` on `#e7f2ec` | 13.21 | 4.5 | pass |
| muted on mint ground | `#416257` on `#e7f2ec` | 5.89 | 4.5 | pass |
| ink on white paper | `#0a2b26` on `#ffffff` | 15.15 | 4.5 | pass |
| muted on white paper | `#416257` on `#ffffff` | 6.75 | 4.5 | pass |
| ALLOW ink word on mint | `#00604d` on `#e7f2ec` | 6.59 | 4.5 | pass |
| REVIEW ink word on mint | `#6b4f00` on `#e7f2ec` | 6.67 | 4.5 | pass |
| DENY ink word on mint | `#b3260a` on `#e7f2ec` | 5.72 | 4.5 | pass |
| ALLOW ink word on white | `#00604d` on `#ffffff` | 7.55 | 4.5 | pass |
| REVIEW ink word on white | `#6b4f00` on `#ffffff` | 7.65 | 4.5 | pass |
| DENY ink word on white | `#b3260a` on `#ffffff` | 6.57 | 4.5 | pass |
| frost text on spruce | `#eef8f3` on `#0a2b26` | 13.96 | 4.5 | pass |
| sage muted on spruce | `#a4c9be` on `#0a2b26` | 8.42 | 4.5 | pass |
| sage muted on pine | `#a4c9be` on `#11403a` | 6.42 | 4.5 | pass |
| frost on pine | `#eef8f3` on `#11403a` | 10.65 | 4.5 | pass |
| pink on spruce (USP line, closing line) | `#ff3d9a` on `#0a2b26` | 4.61 | 4.5 | pass |
| spruce ink on pink (CTA, claims chapter, $500 slip) | `#0a2b26` on `#ff3d9a` | 4.61 | 4.5 | pass |
| frost on spruce card (claims cards on pink) | `#eef8f3` on `#0a2b26` | 13.96 | 4.5 | pass |
| ALLOW lamp word on spruce | `#34f0c2` on `#0a2b26` | 10.38 | 4.5 | pass |
| REVIEW lamp word on spruce | `#ffd11a` on `#0a2b26` | 10.38 | 4.5 | pass |
| DENY lamp word on spruce | `#ff7d52` on `#0a2b26` | 5.99 | 4.5 | pass |
| ALLOW lamp word on pine | `#34f0c2` on `#11403a` | 7.91 | 4.5 | pass |
| REVIEW lamp word on pine | `#ffd11a` on `#11403a` | 7.91 | 4.5 | pass |
| DENY lamp word on pine | `#ff7d52` on `#11403a` | 4.57 | 4.5 | pass |
| spruce word on ALLOW lamp plate | `#0a2b26` on `#34f0c2` | 10.38 | 4.5 | pass |
| spruce word on REVIEW lamp plate | `#0a2b26` on `#ffd11a` | 10.38 | 4.5 | pass |
| spruce word on DENY lamp plate | `#0a2b26` on `#ff7d52` | 5.99 | 4.5 | pass |
| pink focus ring on spruce (non-text) | `#ff3d9a` on `#0a2b26` | 4.61 | 3 | pass |
| ink focus ring on mint (non-text) | `#0a2b26` on `#e7f2ec` | 13.21 | 3 | pass |
| spruce focus ring on pink (non-text) | `#0a2b26` on `#ff3d9a` | 4.61 | 3 | pass |
| moss hairline on spruce (decorative) | `#2d6157` on `#0a2b26` | 2.13 | 1 | pass |

Hairlines (moss on spruce 2.13) are decorative; every control also has a border or a word.

## Console (presentation only; every function and guard kept)
- **Queue**: a short list of cards. Plain headline per request ("Approve invoice for $4,800.00", "Refund $250.00 to a customer card"; the queue payload has no invoice id, so the id appears on the request page), a signal chip, who asked and how long ago, the first policy reason in plain words, one primary action. Filters sit behind a "Filter" disclosure. Arrow keys still move between the actions.
- **Request**: leads with a plain 3-line verdict (why it paused, recomputed from the claims: "the invoice is $500.00 above the purchase order"; how many cited values re-verified; what Approve and Reject do), then the 2 or 3 values that matter next to the highlighted source page. A sticky decision bar holds the typed reason, Approve or Reject, a confirm step and the real outcome (no optimistic UI). The label line is unchanged: "requested by X for Y · approved by Z (different person)". Evidence (every claim, ASSERTED "not evidence", methods), Policy reasons and Technical details (hash, diff, before, card) are native `<details>`.
- **Audit**: one large "Verify chain" button and one result sentence; entries below.
- Auth, CSRF, role gating, the 8 to 500 character reason, the confirm step, double-submit lock and the aria-live outcome are untouched.

## Data rule
CLAUDE.md invariant 7: every number on screen is fetched (`lib/api.ts`, types generated from `web/openapi.json`).
The site embeds no eval result, latency or amount in source; the home story replays `GET /api/public/replay/inv-2048`
and `/evaluation` reads `GET /api/public/eval`, both with honest empty and error states.
