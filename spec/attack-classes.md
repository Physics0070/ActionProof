# Attack classes (slide 6)

Each attack tries to get a write executed that should not be. Expected result for every attack case: the tool is executed 0 times.

| # | Class | Control | Test scenario |
|---|---|---|---|
| 1 | Prompt injection | Taint labels; document text never fills authority fields | Hidden "approve regardless" text in a PDF |
| 2 | Argument tampering | Claims re-verified at the cited span | Amount edited after extraction |
| 3 | Evidence forgery | Span re-extraction and document hash match | Cited span lacks the value |
| 4 | Confused deputy | `on_behalf_of` scope checked in policy | Agent exceeds the user's scope |
| 5 | Split payments | Cumulative limits per actor and vendor | Two $4,900 approvals, $5,000 cap |
| 6 | Replay | One-use token and idempotency key | Reused token or key |
| 7 | Race (TOCTOU) | Version precondition at commit | Record mutated mid-flight |

## Case format (finalized in Phase 6)
Cases are JSON files; the generator writes only cases, never gate code. See `spec/actionrequest.md` for the request shape.
