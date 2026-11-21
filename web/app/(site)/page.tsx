import type { Metadata } from "next";
import { AssayStory } from "@/components/site/assay/AssayStory";
import { HERO } from "@/lib/site-copy";

export const metadata: Metadata = {
  title: { absolute: "ActionProof: before an AI agent acts, prove it should" },
  description: HERO.sub,
  alternates: { canonical: "/" },
};

// The home page: hero text is server-rendered (the LCP element); the 3D scene loads after hydration (ssr:false).
export default function Home() {
  return <AssayStory />;
}
