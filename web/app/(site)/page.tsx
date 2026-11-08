import type { Metadata } from "next";
import Link from "next/link";
import { Band } from "@/components/ui/Band";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Story } from "@/components/site/Story";
import { BENEFITS, CLOSING, HERO, IMPACT, LIMITS } from "@/lib/site-copy";

export const metadata: Metadata = {
  title: { absolute: "ActionProof: before an AI agent acts, prove it should" },
  description: HERO.sub,
};

// Server-rendered text is the LCP element; the 3D story below loads after hydration (dynamic, ssr:false).
export default function Home() {
  return (
    <>
      <Band tone="carbon" labelledBy="hero-title">
        <MonoLabel as="p" muted>
          {HERO.usp}
        </MonoLabel>
        <h1 id="hero-title" className="t-display hero-title">
          {HERO.title}
        </h1>
        <p className="t-lede t-muted hero-sub">{HERO.sub}</p>
        <ul aria-label="Decisions" className="signal-row">
          {(["ALLOW", "REVIEW", "DENY"] as const).map((d) => (
            <li key={d}>
              <Signal state={d} />
            </li>
          ))}
        </ul>
        <p className="cta-row">
          <Link className="button button-primary" href="/evaluation">
            Read the evidence
          </Link>
          <Link className="button" href="/console">
            Open the review console
          </Link>
        </p>
      </Band>

      <Story />

      <Band tone="mist" labelledBy="benefits-title">
        <h2 id="benefits-title" className="t-h2">
          Who benefits
        </h2>
        <ul className="plain-list cols-2 benefit-list">
          {BENEFITS.map((b) => (
            <li key={b.who}>
              <h3 className="t-h3">{b.who}</h3>
              <p>{b.body}</p>
            </li>
          ))}
        </ul>
        <h2 className="t-h2 sub-h2">Expected impact</h2>
        <ul className="plain-list impact-list">
          {IMPACT.map((i) => (
            <li key={i}>
              <p className="t-lede">{i}</p>
            </li>
          ))}
        </ul>
      </Band>

      <Band tone="mist" labelledBy="limits-title">
        <h2 id="limits-title" className="t-h2">
          What ActionProof does not claim
        </h2>
        <ul className="plain-list cols-2 limit-list">
          {LIMITS.map((l) => (
            <li key={l.head}>
              <h3 className="t-h3">{l.head}</h3>
              <p>{l.body}</p>
            </li>
          ))}
        </ul>
      </Band>

      <Band tone="carbon" labelledBy="closing-title">
        <h2 id="closing-title" className="t-h2">
          {CLOSING}
        </h2>
        <p className="cta-row">
          <Link className="button button-primary" href="/evaluation">
            See how it is measured
          </Link>
          <Link className="button" href="/console">
            Review a paused action
          </Link>
        </p>
      </Band>
    </>
  );
}
