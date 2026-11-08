// The ONE driver module of the home story: scroll progress in zustand, one GSAP clock.
//  - Lenis is stepped by gsap.ticker (no own rAF); the R3F scene is advanced from the same ticker (GateScene).
//  - ScrollTrigger writes `hero` / `gate` (0..1) and the active chapter into the store.
//  - The scene reads the store with getState() inside useFrame (no React subscription, no re-render per frame).
//  - The real INV-2048 decision lives here too, fetched once from /api/public/replay/inv-2048.
import { create } from "zustand";
import { ApiError, apiGet } from "./api";
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
  /** 0..1 over the pinned gate sequence. Read in useFrame via getState(). */
  gate: number;
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
  gate: 0,
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

export function detectCaps(): Caps {
  let webgl = false;
  try {
    const c = document.createElement("canvas");
    webgl = !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    webgl = false;
  }
  return {
    ready: true,
    webgl,
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
    const gate = document.getElementById("gate");
    if (gate) {
      ScrollTrigger.create({ trigger: gate, start: "top top", end: "bottom bottom", onUpdate: (s) => useStory.setState({ gate: s.progress }) });
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
