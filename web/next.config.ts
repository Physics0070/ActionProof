import type { NextConfig } from "next";
import { loadConfig } from "./lib/config";
import { headers } from "./security-headers.mjs";

// Fails the build (and `next dev`) loudly if the env is missing or malformed (CLAUDE.md invariant 7).
const cfg = loadConfig(process.env);

const nextConfig: NextConfig = {
  output: "standalone", // web/Dockerfile runs .next/standalone/server.js
  reactStrictMode: true,
  headers, // strict CSP etc.: security-headers.mjs
  poweredByHeader: false,
  // Same-origin API: the browser calls NEXT_PUBLIC_API_BASE/*, Next forwards to the console backend, so the
  // ap_session / ap_csrf cookies are first-party (SameSite=Strict holds) and no CORS is involved.
  async rewrites() {
    return [{ source: `${cfg.apiBase}/:path*`, destination: `${cfg.consoleOrigin}/api/:path*` }];
  },
};

export default nextConfig;
