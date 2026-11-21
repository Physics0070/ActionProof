# ActionProof web: design system ("Assay")

Product: a gate in front of an AI agent's writes. **Prove before execution.** No value authorizes a write unless its
derivation re-checks (G1), and no approval can be replayed (G2). Audiences: developers shipping agents, finance and ops
reviewers, security and compliance. Three jobs: say the idea in three seconds (hero), show the mechanism with the real
decision (the scroll story), run the review console (`/console`).

Stack: Next.js 16 App Router, React 19, TypeScript, Turbopack. `three` + `@react-three/fiber` for the one scene,
`gsap` (ScrollTrigger) + `lenis` for scroll, `zustand` for the story driver. No new dependency was added for this
direction (all of the above were already in `package.json`). Plain CSS tokens; no UI library.

**Status.** The whole site is on this direction. The palette, type and signals live in `app/globals.css` (tokens), so
`/evaluation`, `/console/*` and the 404 inherit them; the home page adds its scene and layout in `app/(site)/assay.css`.
Screens with their own composition: home, login, the review workspace (provenance on each value, an "exactly what you are
approving" panel, a history), and the audit explorer (the log as a linked chain). The queue and `/evaluation` changed
palette and type only. Contrast of every token pairing: `npm run contrast` (28 pairings pass).

## Three concepts (awwwards, phase 1)
| | A. Assay (chosen) | B. Survey line | C. Cipher wall |
|---|---|---|---|
| Idea | An assay office: nothing is hallmarked until it has been tested. A request is a point of light that must survive each test before the die strikes its receipt. | A surveyor's route: stakes, tolerances and closing errors; each station is a measurement. | A wall of hex that resolves into a verified value. |
| Territory | the profession's material (assay, hallmark, strike) | place and craft (surveying) | a formal system (cryptography as texture) |
| Signature | The die drops on the packet and strikes a hallmark; a replayed receipt bounces off the closed latch. | A theodolite sweep reads each value into place. | Noise collapses into the verified number. |
| Emotion | calm pressure, then a hard, quiet certainty | patient precision | hypnotic, abstract |
| Originality / fit / feasibility / portability (lower better) | 4 / 5 / 4 / 2 | 3 / 4 / 4 / 3 | 3 / 2 / 5 / 5 |
| Anchor | the gate really has one receipt, one latch, one audit entry per bounce | the route is real: request to commit | cryptography is real but decorative here |

**Chosen: A.** It is the only concept whose signature moment is the product's real behaviour (G2: a spent receipt is
refused, recorded at an audit entry), and the scene can be driven by the recorded decision.

### Concept card
```
Idea:        A request is a point of light on a long route; it only advances as each proof clears.
Metaphor:    an assay office: test, then strike the hallmark; nothing is trusted before it is tested
Signature:   the strike (beat 4): a die drops, the hallmark is stamped, the latch closes behind the packet, and a
             ghost copy of the receipt, when the gate really recorded a replay, bounces off it in vermilion
Emotion:     dust and uncertainty at the start; a hard, quiet certainty at the strike
Motion verb: strike (fast attack, dead stop, a small ring of light; nothing floats or bounces by itself)
Screenshot:  bone-white wireframe packet inside three amber rings, the REVIEW decision in plain type beside it
```

## Real versus decorative (read this before changing the scene)
Everything on the home page that looks like a statement is either fetched or labelled.
* **Fetched, from `GET /api/public/replay/inv-2048`:** the three amounts, the claims and their kinds and checks, the
  decision and its rule ids, the status and reviewer, the replay bounce (rule, audit entry number), the audit range and
  the request hash. The 3D scene is built from the same object (`components/site/assay/scene/model.ts`): one node per
  claim, the ring colour is the decision, the chain length is the audit range, the vermilion block is the entry that
  recorded the bounce, the hallmark pattern is drawn from the request hash.
* **Never invented:** with no recorded decision the scene shows a neutral illustration and every beat says so; there is no
  ghost, no verdict colour and no audit range in its place.
* **Decorative (and only that):** the dust cloud, the route ticks, the idle motion, the camera path.
* **Not shown because it is not live:** nothing on the page streams events. A denial produced right now would appear in
  the scene the next time the page loads the decision; there is no live event feed on the public site.

## Palette by role (`app/(site)/assay.css`, scoped to `.assay`)
| Role | Token | Value |
|---|---|---|
| ground | `--as-ground` | `#07090a` obsidian |
| ink | `--as-bone` | `#ece9e1` bone |
| muted | `--as-steel` | `#8d9da6` cold steel |
| line | `--as-line` | `#2a3236` graphite |
| refused | `--as-deny` | `#ff4a24` vermilion |
| needs a person | `--as-review` | `#ffb020` amber |
| allowed | `--as-allow` | `#b8ffe0` pale mint |
White-hot (`#fff`) is the proven state of the packet. Colour is never the only signal: every decision carries its word and
shape (`components/ui/Signal`). The scene reads these tokens from the page, so the CSS is the single source.

## Type
* Display: **Anybody** (Google, variable `wdth` axis, via `next/font`): hero set at width 60% in capitals, beat titles at
  62%, the outlined motto at 150%. One file gives both the extra-condensed and the extra-expanded setting.
* Body: **Hanken Grotesk** 400/500/600. Data and labels: **IBM Plex Mono** (already loaded).
* Fluid scale with `clamp()`; display tracking set per size; body 16 to 19 px at 1.5 to 1.6.
* The hero's motto box has a fixed height so the web font swapping in cannot move the hero (measured CLS 0).

## Composition
```
hero            beat (x6, equal height)               after
+--------------+--------------+          +--------------+--------------+        three columns of hairline lists
| KICKER       |              |          | 01/06 LABEL  |   [scene]    |        (who benefits, impact, limits)
| HUGE H1      |   [packet]   |          | Title        |              |
| sub  [CTA]   |              |          | copy + facts |              |
| outlined motto              |          +--------------+--------------+
+--------------+--------------+
```
The scene sits fixed behind everything; copy scrolls over it on the dark left; the picture is shifted right with
`camera.setViewOffset` on wide screens. On phones the copy takes the lower part over a scrim and the scene stays above.

## Motion
* One clock: the GSAP ticker advances Lenis, ScrollTrigger and the R3F loop (and only while the story is on screen).
* One driver: `lib/site-story.ts` writes `track` (0..1), `beat`, `chapter`; `lib/assay.ts` (pure) maps scroll to the
  packet's place on the route, with a dwell at every station. Beats are equal-height sections, so beat `i` is centred at
  `(i + 0.5) / 6`.
* The strike easing is a cubic fall to a dead stop; everything else is smoothstep. Copy enters with a CSS scroll-driven
  animation where supported (progressive enhancement; the copy is visible without it).
* Idle: dust drifts, rings turn, the packet breathes (all on the clock, off screen they stop).

## Performance, fallbacks, accessibility (measured on the production build, 2026-11-21)
* The scene is `next/dynamic` with `ssr:false`, mounted after load at idle; first-load JS before the scene is 148 KB,
  459 KB once the scene has loaded. Phones get fewer particles (900 vs 2600), `dpr` 1 and a wider field of view.
* Real browser (Chromium, software WebGL, so frame times are pessimistic): CLS 0 on desktop and on a 4x CPU phone
  profile; LCP is the hero text. Repeat the measurement on real hardware before quoting numbers.
* Reduced motion, no WebGL, or a WebGL failure: no canvas, no smooth scroll; the same six beats on a plain ground, each
  with a static drawing of its station (`Glyphs.tsx`). Verified at 1440 and 390 with zero console errors.
* Keyboard: skip link, the rail is a real list of anchors with `aria-current`, focus styles come from the shared global tokens (`--c-focus`; not re-audited on this page).
  The canvas is `aria-hidden`; nothing is conveyed by the scene alone.

## What is not done yet
* No live dashboard route, and no "request more evidence" action: the backend has neither (no metrics, execution states or
  connector/worker health; the decision API is approve or reject). They are not drawn.
* The audit explorer shows the chain of the entries the API returns (newest page) and the server's own verification
  result. It does not show per-entry checkpoints or the anchored/unanchored range: no API route exposes them.
* `/evaluation` and the queue are restyled, not recomposed. The evaluation bars separate arms by length and label only.
* The in-browser checks were scripted outside the repo; the repo has no JS test runner and its Playwright specs are unrun.
