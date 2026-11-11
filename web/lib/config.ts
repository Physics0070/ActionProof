// Validated web config (README.md invariant 7: nothing hardcoded, config from validated env).
// `loadConfig` runs in next.config.ts, so a missing/invalid variable stops `next build` / `next dev` with the
// variable NAME (never its value).

export type WebConfig = {
  /** Same-origin path prefix the browser calls; rewritten to the console backend. e.g. "/api" */
  apiBase: string;
  /** Console backend origin, server-side only (rewrite target, server-rendered fetches). e.g. "http://127.0.0.1:8766" */
  consoleOrigin: string;
  /** Public origin of this site, for canonical and og:image URLs. Optional; validated when present. */
  siteUrl: string | null;
  /** Public repository URL shown in the footer. Optional; validated when present. */
  repoUrl: string | null;
};

type Env = Record<string, string | undefined>;

export class ConfigError extends Error {}

function isHttpUrl(v: string, originOnly: boolean): boolean {
  try {
    const u = new URL(v);
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    return originOnly ? u.pathname === "/" && !u.search && !v.endsWith("/") : true;
  } catch {
    return false;
  }
}

export function loadConfig(env: Env): WebConfig {
  const problems: string[] = [];
  const apiBase = env.NEXT_PUBLIC_API_BASE ?? "";
  if (!/^\/[a-z0-9-]+$/.test(apiBase)) problems.push("NEXT_PUBLIC_API_BASE (same-origin path like /api)");
  const consoleOrigin = env.CONSOLE_API_ORIGIN ?? "";
  let ok = false;
  try {
    const u = new URL(consoleOrigin);
    ok = (u.protocol === "http:" || u.protocol === "https:") && u.pathname === "/" && !u.search && !consoleOrigin.endsWith("/");
  } catch {
    ok = false;
  }
  if (!ok) problems.push("CONSOLE_API_ORIGIN (http(s) origin, no path, no trailing slash)");
  const siteUrl = env.NEXT_PUBLIC_SITE_URL || null;
  if (siteUrl && !isHttpUrl(siteUrl, true)) problems.push("NEXT_PUBLIC_SITE_URL (http(s) origin, no path, no trailing slash)");
  const repoUrl = env.NEXT_PUBLIC_REPO_URL || null;
  if (repoUrl && !isHttpUrl(repoUrl, false)) problems.push("NEXT_PUBLIC_REPO_URL (https URL)");
  if (problems.length) throw new ConfigError(`ConfigError: missing or invalid ${problems.join(", ")}`);
  return { apiBase, consoleOrigin, siteUrl, repoUrl };
}

/** Browser-side base. Next inlines NEXT_PUBLIC_* only for literal `process.env.NAME` reads. */
export const API_BASE: string = process.env.NEXT_PUBLIC_API_BASE ?? "";
export const SITE_URL: string | null = process.env.NEXT_PUBLIC_SITE_URL || null;
export const REPO_URL: string | null = process.env.NEXT_PUBLIC_REPO_URL || null;
