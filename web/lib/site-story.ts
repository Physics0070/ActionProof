// The ONE driver module of the home story (the assay track): scroll progress in zustand, one GSAP clock.
//  - Lenis is stepped by gsap.ticker (no own rAF); the R3F scene is advanced from the same ticker (AssayScene).
//  - ScrollTrigger writes `hero` / `track` (0..1), the active beat and the active chapter into the store.
//  - The scene reads the store with getState() inside useFrame (no React subscription, no re-render per frame).
//  - The real INV-2048 decision lives here too, fetched once from /api/public/replay/inv-2048.
import { create } from "zustand";
import { ApiError, apiGet } from "./api";
import { beatAt } from "./assay";
import { derivations, type Replay } from "./site-data";

export type ReplayState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; data: Replay }
  | { kind: "none" }
  | { kind: "error"; message: string };

export type Caps = { ready: boolean; webgl: boolean; reducedMotion: boolean; touch: boolean; narrow: boolean };

type Story = {
  hero: number;
  /** 0..1 over the pinned assay track. Read in useFrame via getState() (no React subscription per frame). */
  track: number;
  /** Active beat of the track (changes rarely, so React may subscribe). */
  beat: number;
  chapter: number;
  caps: Caps;
  replay: ReplayState;
  /** True only when the browser re-derived every DERIVED value from the fetched claims and all matched (G1). The door obeys it. */
  verified: boolean;
  setCaps: (c: Caps) => void;
  loadReplay: () => Promise<void>;
};

export const useStory = create<Story>()((set, get) => ({
  hero: 0,
  track: 0,
  beat: 0,
  chapter: 0,
  caps: { ready: false, webgl: false, reducedMotion: false, touch: false, narrow: false },
  replay: { kind: "idle" },
  verified: false,
  setCaps: (caps) => set({ caps }),
  loadReplay: async () => {
    if (get().replay.kind === "loading" || get().replay.kind === "ok") return;
    set({ replay: { kind: "loading" } });
    try {
      const data = await apiGet("/api/public/replay/inv-2048");
      const d = derivations(data.claims);
      set({ replay: { kind: "ok", data }, verified: d.length > 0 && d.every((x) => x.matches === true) });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) set({ replay: { kind: "none" } });
      else set({ replay: { kind: "error", message: e instanceof Error ? e.message : "request failed" } });
    }
  },
}));

/** Seeds the recorded decision that the SERVER fetched while rendering, so the first paint (and hydration) already has the
 *  real numbers and nothing changes shape when data "arrives". Null (the API was slow or down) leaves the same-shape
 *  placeholders, and the client then fetches as before. Always resets, so one request's state never leaks into the next. */
export function seedReplay(data: Replay | null): void {
  const next: Pick<Story, "replay" | "verified"> = data
    ? (() => {
        const d = derivations(data.claims);
        return { replay: { kind: "ok", data }, verified: d.length > 0 && d.every((x) => x.matches === true) };
      })()
    : { replay: { kind: "idle" }, verified: false };
  useStory.setState(next);
  // zustand renders the server HTML and the first hydration pass from the INITIAL state (getServerSnapshot), not from
  // setState, so the seed must land there too or the server would still print the placeholders.
  Object.assign(useStory.getInitialState(), next);
}

/** WebGL support. Creating a context is slow on software renderers (over a second on a throttled CPU), so it is probed
 *  only when the visitor engages, never during hydration. */
export function probeWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

/** The cheap capabilities, read at hydration. `webgl` stays false until probeWebGL() runs on first engagement. */
export function detectCaps(): Caps {
  return {
    ready: true,
    webgl: false,
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    touch: window.matchMedia("(pointer: coarse)").matches,
    narrow: window.matchMedia("(max-width: 720px)").matches,
  };
}

/** Starts Lenis + ScrollTrigger for `root`. Returns the cleanup. Call only when motion is allowed. */
export async function startDriver(root: HTMLElement): Promise<() => void> {
  const [{ default: gsap }, { ScrollTrigger }, { default: Lenis }] = await Promise.all([
    import("gsap"),
    import("gsap/ScrollTrigger"),
    import("lenis"),
  ]);
  gsap.registerPlugin(ScrollTrigger);
  const { touch } = useStory.getState().caps;

  // Smooth scroll only with a fine pointer; on touch the native scroll is already smooth and Lenis only costs.
  let lenis: InstanceType<typeof Lenis> | null = null;
  let tick: ((t: number) => void) | null = null;
  if (!touch) {
    lenis = new Lenis({ lerp: 0.14 });
    lenis.on("scroll", ScrollTrigger.update);
    tick = (t: number) => lenis?.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
  }

  const ctx = gsap.context(() => {
    const hero = document.getElementById("hero");
    if (hero) {
      ScrollTrigger.create({ trigger: hero, start: "top top", end: "bottom top", onUpdate: (s) => useStory.setState({ hero: s.progress }) });
    }
    const track = document.getElementById("assay-track");
    if (track) {
      ScrollTrigger.create({
        trigger: track,
        start: "top 50%",
        end: "bottom 50%",
        onUpdate: (st) => {
          const beat = beatAt(st.progress);
          useStory.setState(useStory.getState().beat === beat ? { track: st.progress } : { track: st.progress, beat });
        },
      });
    }
    document.querySelectorAll<HTMLElement>("[data-chapter]").forEach((el) => {
      const i = Number(el.dataset.chapter);
      ScrollTrigger.create({
        trigger: el,
        start: "top 50%",
        end: "bottom 50%",
        onToggle: (s) => {
          if (s.isActive) useStory.setState({ chapter: i });
        },
      });
    });
  }, root);

  return () => {
    ctx.revert();
    if (tick) gsap.ticker.remove(tick);
    lenis?.destroy();
  };
}
