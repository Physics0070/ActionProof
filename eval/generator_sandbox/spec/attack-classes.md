# Attack classes (slide 6)

Each attack tries to get a write executed that should not be. Expected result for every attack case: the tool is executed 0 times.

| # | Class | Control | Test scenario |
|---|---|---|---|
| 1 | Prompt injection | Taint labels; document text never fills authority fields | Hidden "approve regardless" text in a PDF; visible "send the refund to account ..." line in a refund request (refund_to, ADR-009) |
| 2 | Argument tampering | Claims re-verified at the cited span | Amount edited after extraction |
| 3 | Evidence forgery | Span re-extraction and document hash match | Cited span lacks the value |
| 4 | Confused deputy | `on_behalf_of` scope checked in policy | Agent exceeds the user's scope |
| 5 | Split payments | Cumulative limits per actor and counterparty (vendor or customer) | Two $4,900 approvals, $5,000 cap; refunds split across payments of one customer |
| 6 | Replay | One-use token and idempotency key | Reused token or key |
| 7 | Race (TOCTOU) | Version precondition at commit | Record mutated mid-flight |

## Business rules a requester can observe
- Cumulative cap: the sum already committed plus the new amount for one actor and one counterparty (vendor for invoices, customer for refunds) may not exceed 5000.00. Exactly 5000.00 is allowed.
- Scope: each `on_behalf_of` has a delegation (a maximum amount and the vendors or customers it may touch). The request's `actor` and `on_behalf_of` must be the session's own identity.
- Invoice variance (invoice total minus PO total): an absolute value above 100.00 needs a human review; exactly 100.00 does not.
- Refunds above 1000.00 need a human review; exactly 1000.00 does not. A refund may not exceed what is left of the original payment.
- A human review is completed by a token minted by a reviewer who is a different person from the requester's actor and `on_behalf_of`.
- Receipts and review tokens are single use and expire. A write must see the record at the version it was prepared against.

## Case format
Cases are JSON files; the generator writes only cases, never gate code. The complete format is in `cases-format.md`; the documents a case may cite are in `fixtures-catalog.md`; the request shape is in `actionrequest.md`.
