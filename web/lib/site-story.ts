// The ONE driver module of the home story: one progress value in zustand, one GSAP clock.
//  - Lenis is driven by gsap.ticker (no own rAF); the R3F scene is advanced from the same ticker (StoryScene).
//  - ScrollTrigger writes `progress` (0..1 over the story) and the active chapter/step into the store.
//  - The scene reads the store with getState() inside useFrame (no React subscription, no re-render per frame).
//  - The real INV-2048 decision lives here too, fetched once from /api/public/replay/inv-2048.
import { create } from "zustand";
import { ApiError, apiGet } from "./api";
import type { Replay } from "./site-data";

export type ReplayState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ok"; data: Replay }
  | { kind: "none" }
  | { kind: "error"; message: string };

export type Caps = { ready: boolean; webgl: boolean; reducedMotion: boolean; touch: boolean; narrow: boolean };

type Story = {
  /** 0..1 over the whole story band. Read in useFrame via getState(). */
  progress: number;
  /** 0..1 inside the active chapter. */
  chapterP: number;
  chapter: number;
  step: number;
  caps: Caps;
  replay: ReplayState;
  setCaps: (c: Caps) => void;
  loadReplay: () => Promise<void>;
};

export const useStory = create<Story>()((set, get) => ({
  progress: 0,
  chapterP: 0,
  chapter: 0,
  step: 0,
  caps: { ready: false, webgl: false, reducedMotion: false, touch: false, narrow: false },
  replay: { kind: "idle" },
  setCaps: (caps) => set({ caps }),
  loadReplay: async () => {
    if (get().replay.kind === "loading" || get().replay.kind === "ok") return;
    set({ replay: { kind: "loading" } });
    try {
      const data = await apiGet("/api/public/replay/inv-2048");
      set({ replay: { kind: "ok", data } });
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

/** Starts Lenis + ScrollTrigger for `root`. Returns the cleanup. Call only when the story is live (motion allowed). */
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
    lenis = new Lenis({ lerp: 0.12 });
    lenis.on("scroll", ScrollTrigger.update);
    tick = (t: number) => lenis?.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
  }

  const ctx = gsap.context(() => {
    ScrollTrigger.create({
      trigger: root,
      start: "top bottom",
      end: "bottom top",
      onUpdate: (s) => useStory.setState({ progress: s.progress }),
    });
    root.querySelectorAll<HTMLElement>("[data-chapter]").forEach((el, i) => {
      const steps = Number(el.dataset.steps ?? 1);
      ScrollTrigger.create({
        trigger: el,
        start: "top 55%",
        end: "bottom 55%",
        onToggle: (s) => {
          if (s.isActive) useStory.setState({ chapter: i });
        },
        onUpdate: (s) => {
          if (useStory.getState().chapter !== i) return;
          const step = Math.min(steps - 1, Math.floor(s.progress * steps));
          useStory.setState({ chapterP: s.progress, step });
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
