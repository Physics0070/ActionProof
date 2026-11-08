import type { Metadata, Viewport } from "next";
import { Archivo, Bricolage_Grotesque, IBM_Plex_Mono } from "next/font/google";
import { SITE_URL } from "@/lib/config";
import "./globals.css";

// Self-hosted at build by next/font (no runtime request to Google).
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-bricolage", display: "swap" });
const archivo = Archivo({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-archivo", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap", preload: false });

const DESCRIPTION = "Before an AI agent acts, prove it should. A gate that checks every value before an agent's write executes.";

export const metadata: Metadata = {
  metadataBase: SITE_URL ? new URL(SITE_URL) : undefined,
  title: { default: "ActionProof", template: "%s · ActionProof" },
  description: DESCRIPTION,
  alternates: { canonical: "./" },
  openGraph: {
    type: "website",
    siteName: "ActionProof",
    title: "ActionProof: before an AI agent acts, prove it should",
    description: DESCRIPTION,
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "ActionProof: Before an AI agent acts, prove it should." }],
  },
  twitter: { card: "summary_large_image", title: "ActionProof: before an AI agent acts, prove it should", description: DESCRIPTION, images: ["/og.png"] },
};

export const viewport: Viewport = { themeColor: "#0a2b26" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${bricolage.variable} ${archivo.variable} ${plexMono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
