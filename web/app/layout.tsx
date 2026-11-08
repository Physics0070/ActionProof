import type { Metadata, Viewport } from "next";
import { Archivo, Bricolage_Grotesque, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Self-hosted at build by next/font (no runtime request to Google).
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-bricolage", display: "swap" });
const archivo = Archivo({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-archivo", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "ActionProof", template: "%s · ActionProof" },
  description: "Before an AI agent acts, prove it should. A gate that checks every value before an agent's write executes.",
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
