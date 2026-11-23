import type { Metadata } from "next";
import { AssayStory } from "@/components/site/assay/AssayStory";
import { apiGet } from "@/lib/api";
import { HERO } from "@/lib/site-copy";
import type { Replay } from "@/lib/site-data";

export const metadata: Metadata = {
  title: { absolute: "ActionProof: before an AI agent acts, prove it should" },
  description: HERO.sub,
  alternates: { canonical: "/" },
};

// Rendered per request so the recorded decision is fetched on the server and is already in the HTML: the page has one
// shape from the first paint (no "loading" state that later grows). A slow or unreachable API falls back to placeholders.
export const dynamic = "force-dynamic";

async function recordedDecision(): Promise<Replay | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 2500);
  try {
    return await apiGet("/api/public/replay/inv-2048", { signal: ctl.signal });
  } catch (e) {
    console.warn("home: recorded decision unavailable, using placeholders:", e instanceof Error ? e.message : e);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// The hero text is server-rendered (the LCP element); the 3D scene loads after hydration (ssr:false).
export default async function Home() {
  return <AssayStory initialReplay={await recordedDecision()} />;
}
