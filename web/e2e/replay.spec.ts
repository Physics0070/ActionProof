import { expect, test } from "@playwright/test";
import { apiLogin, decide, mintReview, status } from "./helpers";

// G2 through the real HTTP surface: an approval is single-use. Deciding the same request again (a replayed
// approval, or approve-after-reject) must never execute twice and must never flip the recorded outcome.

test("replayed approval is denied: one execution, status unchanged", async ({ request }) => {
  const hash = mintReview();
  const csrf = await apiLogin(request);
  const first = await decide(request, csrf, hash, "approve");
  expect(first.status(), await first.text()).toBe(200);
  expect((await first.json()).outcome).toBe("EXECUTED");

  const replay = await decide(request, csrf, hash, "approve");
  const body = await replay.json();
  const refused = replay.status() >= 400 || body.outcome !== "EXECUTED";
  expect(refused, `replay must not execute again: ${JSON.stringify(body)}`).toBe(true);
  expect(await status(request, hash)).toBe("executed");
});

test("a decided request cannot be flipped: reject after approve is refused", async ({ request }) => {
  const hash = mintReview();
  const csrf = await apiLogin(request);
  expect((await decide(request, csrf, hash, "reject")).status()).toBe(200);
  const flip = await decide(request, csrf, hash, "approve");
  const body = await flip.json();
  expect(flip.status() >= 400 || body.outcome !== "EXECUTED").toBe(true);
  expect(await status(request, hash)).toBe("rejected");
});

test("a state-changing request without the CSRF token is refused", async ({ request }) => {
  const hash = mintReview();
  await apiLogin(request);
  const r = await request.post(`/api/requests/${hash}/decision`, { data: { decision: "approve", reason: "no csrf header sent" } });
  expect(r.status()).toBeGreaterThanOrEqual(400);
  expect(await status(request, hash)).toBe("pending");
});
