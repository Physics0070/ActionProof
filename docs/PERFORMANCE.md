# Performance budget (Lighthouse, mobile preset)

`web/lighthouserc.json` asserts LCP <= 3200 ms and performance >= 0.75 (median of 3 runs, simulated slow 4G + 4x CPU,
WebGL forced on through SwiftShader). Google's "good" LCP is 2500 ms, so this is NOT yet at the good line.

Measured (2026-11-23):
- First paint of the hero text is at about 0.75 s in the Lighthouse filmstrip; the recorded-decision card is filled in by
  about 1.9 s. The lab figure (LCP about 2.7-3.3 s, TBT about 1.8 s) is Lighthouse's *simulated* throttled estimate.
- The remaining main-thread cost is React hydration of the whole home page (one chunk, about 1.2 s at 4x slowdown).
- Done: the 3D scene and the scroll driver now start on the first interaction (pointer, key, touch, scroll) or after 8 s,
  not at load. Tried without effect: `font-display: optional`, delaying the driver by a timer (reverted).
- Not done: shrinking hydration (split the home page into server components, island the story). Upgrade path to reach
  LCP <= 2500 and performance >= 0.85.
- Local Lighthouse against a build with `Cross-Origin-Opener-Policy: same-origin` fails with NO_NAVSTART (a known tracing
  limitation); CI's lhci run is unaffected.
