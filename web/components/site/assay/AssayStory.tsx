"use client";
// Home page shell. Live (WebGL + motion allowed): Lenis + ScrollTrigger from lib/site-story.ts drive the 3D scene,
// which sits fixed behind the scrolling beats. Otherwise (reduced motion, no WebGL, WebGL failure) the same six beats
// render on a plain ground: the story is complete without the scene.
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BEATS } from "@/lib/assay";
import { HERO } from "@/lib/site-copy";
import { detectCaps, probeWebGL, seedReplay, startDriver, useStory } from "@/lib/site-story";
import { Signal } from "@/components/ui/Signal";
import { moneyStr, type Replay } from "@/lib/site-data";

const AssayScene = dynamic(() => import("./AssayScene"), { ssr: false });

function Rail() {
  const beat = useStory((s) => s.beat);
  const chapter = useStory((s) => s.chapter);
  return (
    <nav className="rail" aria-label="Story">
      <ul>
        {BEATS.map((b, i) => (
          <li key={b.id}>
            <a href={`#beat-${b.id}`} aria-label={`Go to ${i + 1} of ${BEATS.length}: ${b.label}`} aria-current={chapter === 1 && beat === i ? "step" : undefined} data-on={chapter === 1 && beat === i}>
              <span className="rail-dot" aria-hidden="true" />
              <span className="rail-label">{b.label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function HeroGate() {
  const replay = useStory((s) => s.replay);
  if (replay.kind === "idle" || replay.kind === "loading") {
    // A placeholder with the SAME structure and row count as the filled card, so the hero keeps its height when the
    // recorded decision arrives (no layout jump). The six rows match the recorded INV-2048 request.
    return (
      <aside className="gate-card" aria-label="A recorded decision" aria-busy="true">
        <p className="gate-head">
          <span>Agent asks</span>
          <code>…</code>
        </p>
        <ol className="gate-claims" aria-hidden="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <li key={i} data-ok="na" className="gate-skel">
              <span className="gate-name">…</span>
              <span className="gate-kind">…</span>
              <span className="gate-val">…</span>
              <span className="gate-check">…</span>
            </li>
          ))}
        </ol>
        <div className="gate-verdict">
          <span className="gate-ghost" aria-hidden="true" />
          <p>Fetching the recorded decision from the gate.</p>
        </div>
        <p className="gate-foot">Signed receipt. It works once and is bound to this exact request.</p>
      </aside>
    );
  }
  if (replay.kind !== "ok") {
    return (
      <aside className="gate-card" aria-label="A recorded decision">
        <p className="gate-note">{replay.kind === "error" ? "The recorded decision could not be loaded." : "No decision has been recorded yet. Nothing is simulated here."}</p>
      </aside>
    );
  }
  const d = replay.data;
  const dec = d.decision === "ALLOW" || d.decision === "REVIEW" || d.decision === "DENY" ? d.decision : null;
  return (
    <aside className="gate-card" aria-label="A recorded decision">
      <p className="gate-head">
        <span>Agent asks</span>
        <code>{d.tool}</code>
      </p>
      <ol className="gate-claims">
        {d.claims.map((c) => (
          <li key={c.name} data-ok={c.claim === "ASSERTED" ? "na" : c.verification ? String(c.verification.ok) : "na"}>
            <span className="gate-name">{c.name}</span>
            <span className="gate-kind" data-kind={c.claim}>
              {c.claim}
            </span>
            <span className="gate-val">{moneyStr(c.value) ?? c.value}</span>
            <span className="gate-check">{c.claim === "ASSERTED" ? "cannot authorize" : c.verification ? (c.verification.ok ? "re-checked" : "failed") : "not evidence"}</span>
          </li>
        ))}
      </ol>
      <div className="gate-verdict">
        {dec ? <Signal state={dec} solid /> : null}
        <p>{d.reasons[0]?.msg ?? ""}</p>
      </div>
      <p className="gate-foot">Signed receipt. It works once and is bound to this exact request.</p>
    </aside>
  );
}

function Hero() {
  return (
    <section id="hero" data-chapter="0" className="as-hero" aria-labelledby="hero-title">
      <div className="as-hero-inner">
        <p className="as-kicker">Safety gate for AI agents</p>
        <h1 id="hero-title" className="as-display">
          {HERO.title}
        </h1>
        <p className="as-sub">
          Agents can be fooled by a document. ActionProof re-checks every number an agent relies on against the source, and only then lets a write run, once.
        </p>
        <p className="cta-row">
          <Link className="button button-primary" href="/console">
            See a real decision
          </Link>
          <a className="quiet-link" href="#beat-problem">
            Follow one request
          </a>
        </p>
      </div>
      <HeroGate />
    </section>
  );
}

// `children` are the server-rendered beats and closing section (no hydration cost); this shell adds the scene and rail.
export function AssayStory({ initialReplay, children }: { initialReplay: Replay | null; children: ReactNode }) {
  // Seed the store ONCE, before the first render reads it (server and client agree, so hydration matches).
  useState(() => {
    seedReplay(initialReplay);
    return null;
  });
  const rootRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(false);
  const caps = useStory((s) => s.caps);
  const live = caps.ready && caps.webgl && !caps.reducedMotion;
  const [mount, setMount] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    useStory.getState().setCaps(detectCaps());
    void useStory.getState().loadReplay();
  }, []);

  // The WebGL scene is the most expensive thing on the page and is not needed for first paint. On the first sign of
  // engagement (pointer, key, touch, scroll) WebGL is probed (creating a context is slow on software renderers, so never
  // during hydration) and, if present, the scene mounts and FADES IN behind the copy, with the rail and scroll driver.
  // It is fixed and off layout, so when it arrives nothing on the page moves. No engagement: the static story is complete.
  const motionOk = caps.ready && !caps.reducedMotion;
  useEffect(() => {
    if (!motionOk) return;
    const events = ["pointerdown", "pointermove", "keydown", "touchstart", "wheel", "scroll"] as const;
    const go = () => {
      events.forEach((e) => window.removeEventListener(e, go));
      if (!probeWebGL()) return;
      useStory.getState().setCaps({ ...useStory.getState().caps, webgl: true });
      setMount(true);
    };
    events.forEach((e) => window.addEventListener(e, go, { passive: true }));
    return () => events.forEach((e) => window.removeEventListener(e, go));
  }, [motionOk]);

  // Smooth scroll + scroll triggers only drive the fixed scene and the rail; they never change the document's height
  // (no pinning), so starting them cannot move the page.
  useEffect(() => {
    if (!live || !rootRef.current) return;
    let stop: (() => void) | undefined;
    let cancelled = false;
    void startDriver(rootRef.current).then((fn) => {
      if (cancelled) fn();
      else stop = fn;
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [live]);

  // Render the scene only while the hero or the track is on screen (the ticker bridge reads this ref every frame).
  useEffect(() => {
    if (!live) return;
    const els = ["hero", "assay-track"].map((id) => document.getElementById(id)).filter((e): e is HTMLElement => !!e);
    const seen = new Set<Element>();
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) (e.isIntersecting ? seen.add(e.target) : seen.delete(e.target));
      activeRef.current = seen.size > 0;
    });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, [live]);

  useEffect(() => {
    const on = () => setReady(true);
    window.addEventListener("assay-ready", on);
    return () => window.removeEventListener("assay-ready", on);
  }, []);

  return (
    <div ref={rootRef} className="assay-story assay" data-live={live}>
      {live ? (
        <div className="canvas-wrap" data-ready={ready} aria-hidden="true">
          {mount ? <AssayScene active={activeRef} light={caps.narrow || caps.touch} /> : null}
        </div>
      ) : null}
      {live ? <Rail /> : null}
      <Hero />
      {children}
    </div>
  );
}
