import { execSync } from "node:child_process";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Env is mandatory: a missing value fails the run loudly (invariant 7, nothing hardcoded). */
export function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`e2e: ${name} is not set (see playwright.config.ts)`);
  return v;
}

export const creds = () => ({ login: env("E2E_REVIEWER_LOGIN"), password: env("E2E_REVIEWER_PASSWORD") });

/** Park a fresh hero REVIEW through the real gate (scripts/mint_review.py) and return its request hash. */
export function mintReview(): string {
  const out = execSync(env("E2E_MINT_CMD"), { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  const hash = JSON.parse(out.trim().split("\n").pop() ?? "").request_hash as string;
  expect(hash).toMatch(/^[0-9a-f]{64}$/);
  return hash;
}

/** API login (no UI): returns the CSRF token the console issues; cookies stay in the request context. */
export async function apiLogin(request: APIRequestContext, login = creds().login, password = creds().password) {
  const r = await request.post("/api/auth/login", { data: { login, password } });
  expect(r.status(), await r.text()).toBe(200);
  return (await r.json()).csrf_token as string;
}

export function decide(request: APIRequestContext, csrf: string, hash: string, decision: "approve" | "reject") {
  return request.post(`/api/requests/${hash}/decision`, {
    headers: { "X-CSRF-Token": csrf },
    data: { decision, reason: "e2e: reviewed against the PO amendment" },
  });
}

export async function status(request: APIRequestContext, hash: string) {
  const r = await request.get(`/api/requests/${hash}`);
  expect(r.status()).toBe(200);
  return (await r.json()).status as string;
}

/** UI login. Selectors are by accessible name so they survive restyling; adjust the names if the copy changes. */
export async function uiLogin(page: Page, login = creds().login, password = creds().password) {
  await page.goto("/console/login");
  await page.getByLabel(/login|username/i).fill(login);
  await page.getByLabel(/password/i).fill(password);
  await page.getByRole("button", { name: /sign in|log in|login/i }).click();
}
