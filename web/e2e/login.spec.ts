import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { apiLogin, creds, uiLogin } from "./helpers";

test("a bad credential gets one generic error and no session", async ({ page, request }) => {
  const r = await request.post("/api/auth/login", { data: { login: creds().login, password: "definitely-wrong-password" } });
  expect(r.status()).toBe(401);
  expect((await r.json()).error.code).toBeTruthy();
  const me = await request.get("/api/auth/me");
  expect(me.status()).toBe(401);
  await page.goto("/console/login");
  await page.getByLabel(/login|username/i).fill("nobody-here");
  await page.getByLabel(/password/i).fill("definitely-wrong-password");
  await page.getByRole("button", { name: /sign in|log in|login/i }).click();
  await expect(page).toHaveURL(/\/console\/login/);
  await expect(page.getByRole("alert")).toBeVisible();
});

test("a reviewer logs in and sees the queue", async ({ page, request }) => {
  await uiLogin(page);
  await expect(page).toHaveURL(/\/console(\/?$|\/requests)/);
  const csrf = await apiLogin(request);
  expect(csrf).toBeTruthy();
  const me = await request.get("/api/auth/me");
  expect((await me.json()).roles).toContain("reviewer");
});

test("login page has no axe violations", async ({ page }) => {
  await page.goto("/console/login");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
});
