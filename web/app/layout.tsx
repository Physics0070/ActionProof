import type { Metadata, Viewport } from "next";
import { Archivo, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Self-hosted at build by next/font (no runtime request to Google).
const archivo = Archivo({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-archivo", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "ActionProof", template: "%s · ActionProof" },
  description: "Before an AI agent acts, prove it should. A gate that checks every value before an agent's write executes.",
};

export const viewport: Viewport = { themeColor: "#15141f" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} ${plexMono.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
