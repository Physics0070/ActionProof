// Thin typed client over the console backend. Types come only from lib/api-types.ts, generated from
// web/openapi.json by `npm run gen:api` (README.md invariant 7). Never hand-write a response type here.
import type { components, paths } from "./api-types";
import { API_BASE } from "./config";

export type Schemas = components["schemas"];

type Json<R> = R extends { content: { "application/json": infer T } } ? T : never;
type Ok<Op> = Op extends { responses: { 200: infer R } } ? Json<R> : never;
type PathParams<Op> = Op extends { parameters: { path: infer P } } ? (P extends Record<string, unknown> ? P : never) : never;
type QueryParams<Op> = Op extends { parameters: { query?: infer Q } } ? Q : never;
type Body<Op> = Op extends { requestBody: { content: { "application/json": infer B } } } ? B : never;

type GetPath = { [P in keyof paths]: paths[P] extends { get: object } ? P : never }[keyof paths];
type PostPath = { [P in keyof paths]: paths[P] extends { post: object } ? P : never }[keyof paths];
type GetOp<P extends GetPath> = paths[P]["get"];
type PostOp<P extends PostPath> = paths[P]["post"];

type Opts<Op> = {
  path?: PathParams<Op>;
  query?: QueryParams<Op>;
  signal?: AbortSignal;
};

/** Any non-2xx: the backend's `{"error": {code, message}}` body, or `internal` if it sent something else. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function base(): string {
  // Browser: same-origin prefix (rewritten by next.config). Server: the backend origin directly.
  if (typeof window !== "undefined") return API_BASE;
  const origin = process.env.CONSOLE_API_ORIGIN;
  if (!origin) throw new ApiError(0, "config", "ConfigError: missing CONSOLE_API_ORIGIN");
  return `${origin}/api`;
}

/** Build the request URL from an OpenAPI path key ("/api/requests/{request_hash}") and its params. */
export function apiUrl(template: string, path?: Record<string, unknown>, query?: Record<string, unknown>): string {
  const filled = template
    .replace(/^\/api/, "")
    .replace(/\{([^}]+)\}/g, (_, k: string) => {
      const v = path?.[k];
      if (v === undefined || v === null) throw new ApiError(0, "client", `missing path param ${k}`);
      return encodeURIComponent(String(v));
    });
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const q = qs.toString();
  return `${base()}${filled}${q ? `?${q}` : ""}`;
}

async function parse<T>(res: Response): Promise<T> {
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(res.status, err?.code ?? "internal", err?.message ?? `HTTP ${res.status}`);
  }
  return data as T;
}

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const m = document.cookie.match(/(?:^|;\s*)ap_csrf=([^;]+)/);
  return m?.[1] ? decodeURIComponent(m[1]) : undefined;
}

export async function apiGet<P extends GetPath>(p: P, opts: Opts<GetOp<P>> = {}): Promise<Ok<GetOp<P>>> {
  const res = await fetch(apiUrl(p, opts.path, opts.query as Record<string, unknown> | undefined), {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: opts.signal,
  });
  return parse(res);
}

export async function apiPost<P extends PostPath>(
  p: P,
  body: Body<PostOp<P>> | undefined,
  opts: Opts<PostOp<P>> = {},
): Promise<Ok<PostOp<P>>> {
  const headers: Record<string, string> = { Accept: "application/json", "Content-Type": "application/json" };
  const csrf = csrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(apiUrl(p, opts.path, opts.query as Record<string, unknown> | undefined), {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: opts.signal,
  });
  return parse(res);
}

/** URL for the cited-box page PNG (an <img src>, so no JSON parsing). */
export function pagePngUrl(requestHash: string, page: number, doc: string): string {
  return apiUrl("/api/requests/{request_hash}/page/{n}.png", { request_hash: requestHash, n: page }, { doc });
}
