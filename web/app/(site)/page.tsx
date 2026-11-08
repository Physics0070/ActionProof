import type { Metadata } from "next";
import Link from "next/link";
import { Story } from "@/components/site/Story";
import { HERO } from "@/lib/site-copy";

export const metadata: Metadata = {
  title: { absolute: "ActionProof: before an AI agent acts, prove it should" },
  description: HERO.sub,
  alternates: { canonical: "/" },
};

// Chapter 1. Server-rendered text is the LCP element; the 3D scene (in <Story>) loads after hydration, ssr:false.
export default function Home() {
  return (
    <>
      <section id="hero" data-chapter="0" className="hero" aria-labelledby="hero-title">
        <div className="container hero-inner">
          <p className="hero-usp">{HERO.usp}</p>
          <h1 id="hero-title" className="t-display hero-title">
            {HERO.title}
          </h1>
          <p className="t-lede hero-sub">{HERO.sub}</p>
          <p className="cta-row">
            <Link className="button button-primary" href="/console">
              See a real decision
            </Link>
            <a className="quiet-link" href="#problem">
              Scroll into the gate
            </a>
          </p>
        </div>
      </section>
      <Story />
    </>
  );
}
