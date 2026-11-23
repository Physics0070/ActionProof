"use client";
// Home page shell. Live (WebGL + motion allowed): Lenis + ScrollTrigger from lib/site-story.ts drive the 3D scene,
// which sits fixed behind the scrolling beats. Otherwise (reduced motion, no WebGL, WebGL failure) the same six beats
// render on a plain ground: the story is complete without the scene.
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { BEATS } from "@/lib/assay";
import { BENEFITS, HERO, IMPACT, LIMITS } from "@/lib/site-copy";
import { detectCaps, startDriver, useStory } from "@/lib/site-story";
import { Signal } from "@/components/ui/Signal";
import { moneyStr } from "@/lib/site-data";
import { Beats } from "./Beats";

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
  if (replay.kind !== "ok") {
    return (
      <aside className="gate-card" aria-label="A recorded decision">
        <p className="gate-note">{replay.kind === "error" ? "The recorded decision could not be loaded." : replay.kind === "none" ? "No decision has been recorded yet. Nothing is simulated here." : "Fetching the recorded decision from the gate."}</p>
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

function Aftermath() {
  return (
    <section className="as-after" aria-labelledby="after-h">
      <h2 id="after-h" className="as-after-title">
        Who it is for, and what it does not claim
      </h2>
      <div className="as-cols">
        <div>
          <h3>Who benefits</h3>
          <ul className="rows">
            {BENEFITS.map((b) => (
              <li key={b.who}>
                <strong>{b.who}</strong>
                <span>{b.body}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Expected impact</h3>
          <ul className="rows rows-one">
            {IMPACT.map((i) => (
              <li key={i}>
                <span>{i}</span>
              </li>
            ))}
          </ul>
        </div>
        <div id="limits">
          <h3>What ActionProof does not claim</h3>
          <ul className="rows">
            {LIMITS.map((l) => (
              <li key={l.head}>
                <strong>{l.head}</strong>
                <span>{l.body}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function AssayStory() {
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

  // The scene is not needed for first paint, and WebGL start-up is the most expensive thing on the page: mount it on the
  // first sign of engagement (pointer, key, touch, scroll) or after 8 s, whichever comes first. The static fallback is
  // what is visible until then.
  useEffect(() => {
    if (!live) return;
    const events = ["pointerdown", "pointermove", "keydown", "touchstart", "wheel", "scroll"] as const;
    const go = () => setMount(true);
    const timer = window.setTimeout(go, 8000);
    events.forEach((e) => window.addEventListener(e, go, { once: true, passive: true }));
    return () => {
      window.clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, go));
    };
  }, [live]);

  useEffect(() => {
    if (!live || !mount || !rootRef.current) return;
    let stop: (() => void) | undefined;
    let cancelled = false;
    // The smooth-scroll/ScrollTrigger driver (and the 3D scene) start on the first sign of engagement, or after 8 s:
    // their start-up is the heaviest main-thread work on the page and is not needed for first paint.
    void startDriver(rootRef.current).then((fn) => {
      if (cancelled) fn();
      else stop = fn;
    });
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [live, mount]);

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
      <Beats />
      <Aftermath />
    </div>
  );
}
