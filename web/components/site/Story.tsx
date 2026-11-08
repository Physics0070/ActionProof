"use client";
// The home story: four chapters over one fixed 3D stage inside carbon bands.
// Live (WebGL + motion allowed): sticky canvas behind the chapters, Lenis + ScrollTrigger from lib/site-story.ts.
// Otherwise (reduced motion, no WebGL, WebGL failure): the same chapters, static, with the SVG signal diagram.
import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { Signal } from "@/components/ui/Signal";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { CLAIMS, GAPS, OUTCOMES, STEPS, TAINT, USP_BODY } from "@/lib/site-copy";
import { cents, money } from "@/lib/site-data";
import { detectCaps, startDriver, useStory } from "@/lib/site-story";
import { ReplayProof } from "./ReplayProof";
import { StaticSignals } from "./StaticSignals";

const StoryScene = dynamic(() => import("./StoryScene"), { ssr: false });

/** The slide-2 example, filled from the real recorded request (no number is typed in source). */
function GapExample() {
  const replay = useStory((s) => s.replay);
  let line = "invoice, purchase order and an unexplained difference";
  if (replay.kind === "ok") {
    const by = new Map(replay.data.claims.map((c) => [c.name, c.value]));
    const inv = cents(by.get("invoice.total") ?? by.get("amount"));
    const gap = cents(by.get("variance"));
    const poRaw = cents(by.get("po.total"));
    const po = poRaw ?? (inv !== null && gap !== null ? inv - gap : null);
    if (inv !== null && gap !== null && po !== null) line = `Invoice ${money(inv)}, Purchase order ${money(po)}, Unexplained ${money(gap)}`;
  }
  return (
    <div className="card example">
      <h3 className="t-h3">Approve INV-2048</h3>
      <p>{line}.</p>
      <p className="t-muted">A filter that reads the agent&apos;s reply sees nothing wrong, so the write could execute.</p>
      {replay.kind === "none" ? <MonoLabel muted>No recorded decision yet, so the amounts are not shown.</MonoLabel> : null}
    </div>
  );
}

function Legend() {
  const chapter = useStory((s) => s.chapter);
  const step = useStory((s) => s.step);
  const replay = useStory((s) => s.replay);
  const decided = chapter === 3 && step >= 2 && replay.kind === "ok" ? replay.data.decision : "";
  return (
    <ul className="stage-legend" aria-hidden="true">
      {(["ALLOW", "REVIEW", "DENY"] as const).map((d) => (
        <li key={d} data-lit={decided === d}>
          <Signal state={d} />
        </li>
      ))}
    </ul>
  );
}

export function Story() {
  const rootRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef(false);
  const caps = useStory((s) => s.caps);
  const step = useStory((s) => s.step);
  const chapter = useStory((s) => s.chapter);
  const live = caps.ready && caps.webgl && !caps.reducedMotion;

  useEffect(() => {
    useStory.getState().setCaps(detectCaps());
    void useStory.getState().loadReplay();
  }, []);

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

  // Render the scene only while the stage is on screen (the ticker bridge checks this ref every frame).
  useEffect(() => {
    const el = stageRef.current;
    if (!live || !el) return;
    const io = new IntersectionObserver(([e]) => {
      activeRef.current = e?.isIntersecting ?? false;
    });
    io.observe(el);
    return () => io.disconnect();
  }, [live]);

  const stepsOn = live && chapter === 1 ? step : -1;

  return (
    <div ref={rootRef} className="story band-carbon" data-live={live}>
      {live ? (
        <div ref={stageRef} className="story-stage">
          <StoryScene active={activeRef} light={caps.narrow || caps.touch} />
          <Legend />
        </div>
      ) : (
        <div className="container static-wrap">
          <StaticSignals />
        </div>
      )}

      <div className="story-chapters container">
        <section className="chapter" data-chapter data-steps="3" aria-labelledby="ch-gaps">
          <div className="card chapter-panel">
            <h2 id="ch-gaps" className="t-h2">
              Three gaps between a tool call and a safe write
            </h2>
            <ul className="plain-list gaps">
              {GAPS.map((g) => (
                <li key={g.id}>
                  <MonoLabel muted>{g.gap}</MonoLabel>
                  <h3 className="t-h3">{g.head}</h3>
                  <p>{g.body}</p>
                </li>
              ))}
            </ul>
            <GapExample />
          </div>
        </section>

        <section className="chapter" data-chapter data-steps="5" aria-labelledby="ch-steps">
          <div className="card chapter-panel">
            <h2 id="ch-steps" className="t-h2">
              Five steps between the agent and the tool
            </h2>
            <ol className="plain-list steps">
              {STEPS.map((s, i) => (
                <li key={s.head} data-on={stepsOn < 0 || stepsOn === i} aria-current={stepsOn === i ? "step" : undefined}>
                  <h3 className="t-h3">{s.head}</h3>
                  <p>{s.body}</p>
                </li>
              ))}
            </ol>
            <p>{OUTCOMES}</p>
            <ul className="signal-row" aria-label="Outcomes">
              {(["ALLOW", "REVIEW", "DENY"] as const).map((d) => (
                <li key={d}>
                  <Signal state={d} />
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="chapter" data-chapter data-steps="3" aria-labelledby="ch-claims">
          <div className="card chapter-panel">
            <h2 id="ch-claims" className="t-h2">
              Three kinds of claim
            </h2>
            <dl className="claims">
              {CLAIMS.map((c) => (
                <div key={c.kind}>
                  <dt>
                    <MonoLabel>{c.kind}</MonoLabel>
                  </dt>
                  <dd>{c.body}</dd>
                </div>
              ))}
            </dl>
            <p className="taint">
              <MonoLabel>Taint rule</MonoLabel> {TAINT}
            </p>
          </div>
        </section>

        <section className="chapter chapter-proof" data-chapter data-steps="4" aria-labelledby="ch-proof">
          <div className="card chapter-panel proof-panel">
            <h2 id="ch-proof" className="t-h2">
              Proof before permission
            </h2>
            <p className="t-lede">{USP_BODY}</p>
            <p className="t-muted">This is a real recorded decision for INV-2048, loaded from the gate. Nothing below is scripted.</p>
            <ReplayProof live={live} />
          </div>
        </section>
      </div>
    </div>
  );
}
