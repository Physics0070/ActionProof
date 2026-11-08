import type { Metadata } from "next";
import { RequestView } from "@/components/console/RequestView";

export const metadata: Metadata = { title: "Request" };

export default async function RequestPage({ params }: { params: Promise<{ hash: string }> }) {
  const { hash } = await params;
  return <RequestView hash={hash} />;
}
