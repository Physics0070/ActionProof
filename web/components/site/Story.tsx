"use client";
// Chapters 2 to 5 of the home page, plus the fixed 3D stage that shows behind the hero and the gate sequence.
// Live (WebGL + motion allowed): Lenis + ScrollTrigger from lib/site-story.ts drive the scene.
// Otherwise (reduced motion, no WebGL, WebGL failure): the same chapters, static, with the SVG poster of the same story.
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal, type Decision } from "@/components/ui/Signal";
import { BENEFITS, CLAIMS, CLOSING, GAPS, IMPACT, LIMITS, OUTCOMES, STEPS, TAINT, USP_BODY } from "@/lib/site-copy";
import { OPERATORS, derivations, invoiceFacts, money, moneyStr, utc, type Replay } from "@/lib/site-data";
import { detectCaps, startDriver, useStory } from "@/lib/site-story";
import { StaticGate } from "./StaticGate";

const GateScene = dynamic(() => import("./GateScene"), { ssr: false });
const DECISIONS: readonly string[] = ["ALLOW", "REVIEW", "DENY"];
const asDecision = (s: string): Decision | null => (DECISIONS.includes(s) ? (s as Decision) : null);

export const CHAPTERS = ["Start", "The problem", "The gate", "Claims", "Proof"] as const;
const IDS = ["hero", "problem", "gate", "claims", "proof"] as const;

function Rail() {
  const chapter = useStory((s) => s.chapter);
  return (
    <nav className="rail" aria-label="Chapters">
      <ul>
        {CHAPTERS.map((c, i) => (
          <li key={c}>
            <a href={`#${IDS[i]}`} aria-label={`Go to chapter ${i + 1}: ${c}`} aria-current={chapter === i ? "step" : undefined} data-on={chapter === i}>
              <span className="rail-dot" aria-hidden="true" />
              <span className="rail-label">{c}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Pending({ what }: { what: string }) {
  const replay = useStory((s) => s.replay);
  if (replay.kind === "none") return <p className="t-muted">No recorded decision yet, so {what} is not shown. Nothing is simulated in its place.</p>;
  if (replay.kind === "error") return <p role="alert">The recorded decision could not be loaded ({replay.message}).</p>;
  return <p className="t-muted">Fetching the recorded INV-2048 decision from the gate...</p>;
}

/** Which step answers which gap (deck slide 2 to slide 3): evidence -> Verify, policy -> Authorize, execution -> Receipt and commit. */
const GAP_STEP: Record<string, number> = { evidence: 1, policy: 2, execution: 3 };

function Problem() {
  const replay = useStory((s) => s.replay);
  const gapsRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const el = gapsRef.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    el.dataset.stage = "armed";
    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) {
          el.dataset.stage = "in";
          io.disconnect();
        }
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const f = replay.kind === "ok" ? invoiceFacts(replay.data.claims) : null;
  return (
    <section id="problem" data-chapter="1" className="ch ch-problem band-mist" aria-labelledby="problem-h">
      <div className="container">
        <h2 id="problem-h" className="t-h2 ch-title">
          Approve INV-2048?
        </h2>
        <div className="slips">
          <div className="slip">
            <MonoLabel>Invoice</MonoLabel>
            <p className="slip-n" aria-label={f ? money(f.inv) : "amount loading"}>{f ? money(f.inv) : "..."}</p>
          </div>
          <div className="slip">
            <MonoLabel>Purchase order</MonoLabel>
            <p className="slip-n">{f ? money(f.po) : "..."}</p>
          </div>
          <div className="slip slip-gap">
            <MonoLabel>Unexplained</MonoLabel>
            <p className="slip-n">{f ? money(f.gap) : "..."}</p>
          </div>
        </div>
        <p className="t-lede ch-lede">A filter that reads the agent&apos;s reply sees nothing wrong, so the write could execute.</p>
        {replay.kind === "none" || replay.kind === "error" ? <Pending what="the amounts" /> : null}
        <ul className="gaps" ref={gapsRef}>
          {GAPS.map((g) => {
            const st = GAP_STEP[g.id] ?? 0;
            return (
              <li key={g.id}>
                <MonoLabel muted>{g.gap}</MonoLabel>
                <h3 className="t-h3">{g.head}</h3>
                <p>{g.body}</p>
                <a className="gap-link" href="#gate">
                  <span className="gap-n" aria-hidden="true">
                    {st + 1}
                  </span>
                  <span>
                    Answered at step {st + 1}: {STEPS[st]?.head}
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

function Readout({ i, data }: { i: number; data: Replay }) {
  const ders = derivations(data.claims);
  const dec = asDecision(data.decision);
  const fin = asDecision(data.status === "executed" ? "ALLOW" : data.status === "rejected" ? "DENY" : data.decision);
  const bounce = data.replay_attempts[0];
  if (i === 0)
    return (
      <p className="readout mono-label">
        {data.tool} · {data.label} · {data.claims.length} claims · request {data.request_hash.slice(0, 12)}
      </p>
    );
  if (i === 1)
    return (
      <div className="readout">
        {ders.length === 0 ? <p className="t-muted">This request has no DERIVED value to re-check.</p> : null}
        {ders.map((d) => (
          <div key={d.claim.name}>
            <p className="derive">
              {d.operands.map((o, k) => (
                <span key={o.name}>
                  {k > 0 ? ` ${OPERATORS[d.fn] ?? d.fn} ` : ""}
                  {moneyStr(o.value) ?? "?"}
                </span>
              ))}
              {d.recomputed ? <strong> = {d.recomputed}</strong> : null}
            </p>
            <p className="mono-label">
              {d.claim.name} claimed {moneyStr(d.claim.value) ?? d.claim.value}. {d.matches === null ? "Not recomputed here." : d.matches ? "Recomputed here: it matches." : "Recomputed here: it does not match."}
              {d.claim.verification ? ` Gate check ${d.claim.verification.ok ? "passed" : "failed"}${d.claim.verification.method ? ` (${d.claim.verification.method})` : ""}.` : ""}
            </p>
          </div>
        ))}
        <p className="mono-label">The door stays shut until this matches.</p>
      </div>
    );
  if (i === 2)
    return (
      <div className="readout">
        {dec ? <Signal state={dec} solid /> : <MonoLabel>{data.decision}</MonoLabel>}
        {data.reasons.map((r, k) => (
          <p key={k} className="mono-label">
            {r.rule} / {r.guarantee}: {r.msg}
          </p>
        ))}
      </div>
    );
  if (i === 3)
    return (
      <div className="readout">
        {fin ? <Signal state={fin} solid label={data.status} /> : <MonoLabel>{data.status}</MonoLabel>}
        <p className="mono-label">
          {data.reviewer ? `reviewer ${data.reviewer}` : "no reviewer yet"}
          {utc(data.decided_at) ? ` · decided ${utc(data.decided_at)}` : ""}
        </p>
      </div>
    );
  return (
    <div className="readout">
      {bounce ? (
        <>
          <Signal state="DENY" solid label="replayed receipt" />
          {bounce.reasons.map((r, k) => (
            <p key={k} className="mono-label">
              {r.rule} / {r.guarantee}: {r.msg} (audit entry {bounce.seq})
            </p>
          ))}
        </>
      ) : (
        <p className="t-muted">No replay attempt is recorded against this request yet, so there is no bounce to show.</p>
      )}
      {data.audit.first_seq !== null ? <p className="mono-label">audit entries {data.audit.first_seq} to {data.audit.last_seq}</p> : null}
    </div>
  );
}

function Gate({ live }: { live: boolean }) {
  const replay = useStory((s) => s.replay);
  const active = useStory((s) => (live ? Math.min(4, Math.floor(s.gate * 5)) : -1));
  const data = replay.kind === "ok" ? replay.data : null;
  const dec = data ? asDecision(data.decision) : null;
  const fin = data ? asDecision(data.status === "executed" ? "ALLOW" : data.status === "rejected" ? "DENY" : data.decision) : null;
  const chain = data && data.audit.first_seq !== null && data.audit.last_seq !== null ? data.audit.last_seq - data.audit.first_seq + 1 : 0;
  const denyIndex = data && data.audit.first_seq !== null && data.replay_attempts[0] ? data.replay_attempts[0].seq - data.audit.first_seq : -1;
  return (
    <section id="gate" data-chapter="2" className="gate band-carbon-clear" data-live={live} aria-labelledby="gate-h">
      <div className="gate-stage">
        <div className="container gate-inner">
          <div className="gate-copy">
            <h2 id="gate-h" className="t-h3 gate-title">
              Five steps between the agent and the tool
            </h2>
            <ol className="stations">
              {STEPS.map((s, i) => (
                <li key={s.head} data-active={!live || active === i} data-done={live && active > i} aria-current={live && active === i ? "step" : undefined}>
                  <div className="st-copy">
                    <div className="st-head">
                      <span className="st-n" aria-hidden="true">{i + 1}</span>
                      <h3>{s.head}</h3>
                    </div>
                    <div className="st-body">
                      <p>{s.body}</p>
                      {data ? <Readout i={i} data={data} /> : i === 1 || i === 4 ? <Pending what="this step" /> : null}
                    </div>
                  </div>
                  {!live ? <StaticGate step={i} decision={dec ?? "REVIEW"} final={fin ?? "REVIEW"} chain={chain} denyIndex={denyIndex} /> : null}
                </li>
              ))}
            </ol>
          </div>
          <div className="gate-foot">
            <p className="mono-label">{OUTCOMES}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function Claims() {
  return (
    <section id="claims" data-chapter="3" className="ch ch-claims" aria-labelledby="claims-h">
      <div className="container">
        <h2 id="claims-h" className="t-h2 ch-title">
          Three kinds of claim
        </h2>
        <dl className="claim-cards">
          {CLAIMS.map((c) => (
            <div key={c.kind} className="claim-card" data-kind={c.kind}>
              <dt className="claim-kind">{c.kind}</dt>
              <dd>{c.body}</dd>
            </div>
          ))}
        </dl>
        <p className="taint t-lede">
          <strong>Taint rule.</strong> {TAINT}
        </p>
      </div>
    </section>
  );
}

function Proof() {
  return (
    <section id="proof" data-chapter="4" className="ch ch-proof band-carbon" aria-labelledby="proof-h">
      <div className="container">
        <h2 id="proof-h" className="t-display proof-usp">
          Proof before permission.
        </h2>
        <p className="t-lede proof-body">{USP_BODY}</p>

        <div className="proof-block">
          <h3 className="t-h3">Who benefits</h3>
          <ul className="rows">
            {BENEFITS.map((b) => (
              <li key={b.who}>
                <strong>{b.who}</strong>
                <span>{b.body}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="proof-block">
          <h3 className="t-h3">Expected impact</h3>
          <ul className="rows rows-one">
            {IMPACT.map((i) => (
              <li key={i}>
                <span className="t-lede">{i}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="proof-block" id="limits">
          <h3 className="t-h3">What ActionProof does not claim</h3>
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

function Closing() {
  return (
    <section className="ch ch-closing" aria-labelledby="closing-h">
      <div className="container">
        <h2 id="closing-h" className="t-h2 closing">
          {CLOSING}
        </h2>
        <p className="cta-row">
          <Link className="button button-primary" href="/console">
            See a real decision
          </Link>
          <Link className="quiet-link" href="/evaluation">
            How it is measured
          </Link>
        </p>
      </div>
    </section>
  );
}

export function Story() {
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

  // The scene is not needed for first paint: mount it when the browser is idle.
  useEffect(() => {
    if (!live) return;
    // After load, when the browser is idle: the server-rendered h1 has painted by then.
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

  // Render the scene only while the hero or the gate is on screen (the ticker bridge reads this ref every frame).
  useEffect(() => {
    if (!live) return;
    const els = ["hero", "gate"].map((id) => document.getElementById(id)).filter((e): e is HTMLElement => !!e);
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
    window.addEventListener("gate-ready", on);
    return () => window.removeEventListener("gate-ready", on);
  }, []);

  return (
    <div ref={rootRef} className="story" data-live={live}>
      {live ? (
        <div className="canvas-wrap" data-ready={ready} aria-hidden="true">
          {mount ? <GateScene active={activeRef} light={caps.narrow || caps.touch} /> : null}
        </div>
      ) : null}
      {live ? <Rail /> : null}
      <Problem />
      <Gate live={live} />
      <Claims />
      <Proof />
      <Closing />
    </div>
  );
}
