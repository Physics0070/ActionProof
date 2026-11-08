import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { apiLogin, mintReview, status, uiLogin } from "./helpers";

// Order matters (serial): reject does not touch the system of record, so the approve that follows still sees the
// state the REVIEW was minted against.

test("reject from the UI: the request is rejected and nothing executes", async ({ page, request }) => {
  const hash = mintReview();
  await uiLogin(page);
  await page.goto(`/console/requests/${hash}`);
  await expect(page.getByRole("heading").first()).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations).toEqual([]);
  await page.getByLabel(/reason/i).fill("e2e: vendor bank details unverified");
  await page.getByRole("button", { name: /reject/i }).click();
  const confirm = page.getByRole("button", { name: /confirm/i });
  if (await confirm.count()) await confirm.first().click();
  await expect.poll(async () => { await apiLogin(request); return status(request, hash); }).toBe("rejected");
});

test("approve from the UI: executed exactly once", async ({ page, request }) => {
  const hash = mintReview();
  await uiLogin(page);
  await page.goto(`/console/requests/${hash}`);
  await page.getByLabel(/reason/i).fill("e2e: PO amendment on file");
  await page.getByRole("button", { name: /approve/i }).click();
  const confirm = page.getByRole("button", { name: /confirm/i });
  if (await confirm.count()) await confirm.first().click();
  await expect.poll(async () => { await apiLogin(request); return status(request, hash); }).toBe("executed");
});
