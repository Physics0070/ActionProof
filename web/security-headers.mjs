// Strict security headers for the Next.js app (S8: CSP/headers). Wire into next.config.ts:
//   import { headers } from "./security-headers.mjs";   ...   const nextConfig: NextConfig = { headers, ... }
// (plus `output: "standalone"` for web/Dockerfile). The API (`NEXT_PUBLIC_API_BASE`, rewritten to the console) is
// excluded: the console sets its own, stricter headers (default-src 'none', no-store) and must not be overridden.
//
// CSP tradeoff, stated exactly (Next + WebGL):
//  - script-src: Next App Router emits inline bootstrap <script> tags (flight data). A static `headers()` cannot carry
//    a per-request nonce, so this file uses `script-src 'self' 'unsafe-inline'` (+ 'unsafe-eval' in dev only, for
//    Turbopack HMR). Mitigations that stay in force: no HTML from user/API data is ever rendered (React escapes; the
//    app has no dangerouslySetInnerHTML on dynamic data), object-src 'none', base-uri 'none', form-action 'self',
//    connect-src 'self', frame-ancestors 'none'. So an injected inline script still could not load a remote script
//    or exfiltrate off-origin.
//  - Upgrade path with NO 'unsafe-inline': `cspWithNonce(nonce)` below. Set it from a Next 16 `proxy.ts`
//    (a fresh nonce per request, forwarded in the `x-nonce` request header and the CSP response header). Cost: every
//    page becomes dynamically rendered (no static optimisation/CDN caching), which hurts the Lighthouse LCP budget.
//  - style-src 'unsafe-inline': React `style=` attributes and GSAP/Lenis write inline styles at runtime.
//  - WebGL (three.js / react-three-fiber): needs no script relaxations (no 'unsafe-eval', no 'wasm-unsafe-eval').
//    It needs `worker-src 'self' blob:` (drei/three loaders spawn blob workers), `img-src 'self' data: blob:`
//    (textures, canvas snapshots) and `connect-src 'self'` (fetch of same-origin assets/API only).
//  - COEP is NOT set (require-corp would break nothing here today but is a footgun for cross-origin fonts/images);
//    COOP same-origin + CORP same-origin are set.

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "/api";
const isDev = process.env.NODE_ENV !== "production";

/** @param {{ nonce?: string }} [opts] with a nonce: no 'unsafe-inline' for scripts. */
export function buildCsp({ nonce } = {}) {
  const script = nonce
    ? `'self' 'nonce-${nonce}' 'strict-dynamic'`
    : "'self' 'unsafe-inline'";
  return [
    "default-src 'self'",
    `script-src ${script}${isDev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "media-src 'self'",
    "object-src 'none'",
    "manifest-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join("; ");
}

/** For a future proxy.ts: the same policy with a per-request nonce instead of 'unsafe-inline' for scripts. */
export const cspWithNonce = (nonce) => buildCsp({ nonce });

export const securityHeaders = [
  { key: "Content-Security-Policy", value: buildCsp() },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" }, // legacy twin of frame-ancestors
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), interest-cohort=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  // Ignored by browsers on plain http (localhost compose); effective behind TLS. No includeSubDomains/preload on purpose.
  { key: "Strict-Transport-Security", value: "max-age=63072000" },
];

/** next.config `headers`: every path except the proxied API. */
export async function headers() {
  const api = apiBase.replace(/^\//, "");
  return [{ source: `/((?!${api}/).*)`, headers: securityHeaders }];
}
