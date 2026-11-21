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

function Hero() {
  return (
    <section id="hero" data-chapter="0" className="as-hero" aria-labelledby="hero-title">
      <div className="as-hero-inner">
        <p className="as-kicker">Your AI agent wants to execute an action. Make it prove why.</p>
        <h1 id="hero-title" className="as-display">
          {HERO.title}
        </h1>
        <p className="as-sub">{HERO.sub}</p>
        <p className="cta-row">
          <Link className="button button-primary" href="/console">
            See a real decision
          </Link>
          <a className="quiet-link" href="#beat-problem">
            Follow one request
          </a>
        </p>
      </div>
      <p className="as-motto" aria-hidden="true">
        PROVE BEFORE EXECUTION
      </p>
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

  // The scene is not needed for first paint: mount it when the browser is idle, after load.
  useEffect(() => {
    if (!live) return;
    type Idle = Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (n: number) => void };
    const w = window as Idle;
    let id = 0;
    let idle = 0;
    const go = () => {
      if (w.requestIdleCallback) idle = w.requestIdleCallback(() => setMount(true), { timeout: 1500 });
      else id = window.setTimeout(() => setMount(true), 600);
    };
    if (document.readyState === "complete") go();
    else window.addEventListener("load", go, { once: true });
    return () => {
      window.removeEventListener("load", go);
      window.clearTimeout(id);
      w.cancelIdleCallback?.(idle);
    };
  }, [live]);

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
      <Beats />
      <Aftermath />
    </div>
  );
}
