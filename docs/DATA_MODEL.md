# Data model

Source: `src/actionproof/schema.sql` (idempotent, applied by `db.apply_schema` and `scripts/dev_pg.py start`).
PostgreSQL 16 (ADR-001). The commit runs in one SERIALIZABLE transaction; the constraints below are what make
G2 a database fact rather than an app-code promise.

Money is `numeric(18,2)` everywhere and crosses the Python boundary only as `Decimal`/`str`: `db.connect()` registers
a dumper that raises `TypeError` for any Python `float` parameter, and a jsonb serializer that refuses floats
(invariant 4, guarded by `tests/test_db.py`).

## records — system of record (mock ERP)
| Column | Type | Constraint |
|---|---|---|
| record_id | text | PRIMARY KEY (e.g. `invoice:INV-2048`, `po:PO-2048`, `payment:PAY-7731`) |
| kind | text | NOT NULL (`invoice`, `po`, `payment`, `vendor`) |
| data | jsonb | NOT NULL; amounts inside are 2 dp strings |
| version | bigint | NOT NULL, CHECK `>= 0` |

Enforces: `version` is bound into the receipt and re-read `FOR UPDATE` at commit; mismatch = **AP-STALE-07 (G2)**.
`data` supplies `vendor_id` and SoR totals for G1 verification (never the agent's claims).

Payment records (ADR-009, refund connector): `data = {customer_id, amount, method_id, status: "captured",
refunded?}`. `customer_id` is the refund's AP-CUM-03 counterparty, `method_id` the only value `refund_to` may take,
`amount` minus the refunds committed against the payment (`commits.record_id`) is the refundable balance. A refund
adds to `refunded` and bumps the version (mock tool). Seeded by `db.seed_refunds` (`db.PAYMENTS`: PAY-7731
CUST-311 450.00 pm_card_4242, PAY-8101 CUST-420 1500.00, PAY-8102 CUST-512 300.00); the demo's fully refunded
PAY-7001..7004 by `scripts/demo_seed.py`.

## delegations — on-behalf-of scope
| Column | Type | Constraint |
|---|---|---|
| on_behalf_of | text | PRIMARY KEY |
| max_amount | numeric(18,2) | NOT NULL, CHECK `>= 0` |
| vendors | text[] | NOT NULL (invoice counterparties) |
| customers | text[] | NOT NULL DEFAULT `'{}'` (refund counterparties, ADR-009; `ALTER ... IF NOT EXISTS` on older DBs) |

Enforces: policy `scope` input; amount above `max_amount`, or vendor (invoice) / customer (refund) not listed =
**AP-SCOPE-02 (G1)**. `db.seed_refunds` sets user-123's `customers` to the customers of `db.PAYMENTS`.

## commits — one row per executed write
| Column | Type | Constraint |
|---|---|---|
| id | bigserial | PRIMARY KEY |
| nonce | text | UNIQUE NOT NULL |
| idempotency_key | text | UNIQUE NOT NULL |
| request_hash | text | NOT NULL |
| actor, on_behalf_of, vendor_id, record_id | text | NOT NULL |
| amount | numeric(18,2) | NOT NULL, CHECK `>= 0` |
| created_at | bigint | NOT NULL, CHECK `>= 0` (UTC epoch seconds) |

Index `commits_actor_vendor (actor, vendor_id)`; index `commits_record (record_id)`.
`vendor_id` holds the **counterparty id** from the system-of-record record (ADR-015): the invoice vendor for
`payments.approve_invoice`, the payment customer for `payments.refund_payment`; `record_id` (`invoice:` /
`payment:`) tells which tool wrote the row.
Enforces: UNIQUE `nonce` / `idempotency_key` = a receipt or key can commit once; a duplicate insert raises
`UniqueViolation` → **AP-REP-05 (G2)**. `SUM(amount)` by actor+counterparty inside the commit tx = **AP-CUM-03 (G1,
ADR-006)**. `SUM(amount)` by `record_id` (other rows) inside the commit tx = the refunds already committed against a
payment, so `amount <= payment.amount − that sum` (**AP-VER-01, G1**, ADR-009).

## review_tokens — human-minted, one-use approvals for REVIEW decisions
| Column | Type | Constraint |
|---|---|---|
| token | text | PRIMARY KEY |
| request_hash | text | NOT NULL (token binds to exactly one request) |
| submitter | text | NOT NULL (`req.actor` of the receipt's request) |
| minted_by | text | NOT NULL (reviewer login = console session subject, ADR-008) |
| minted_by_person | text | NOT NULL (`people.person_id` of `minted_by` at mint; added by `ALTER ... IF NOT EXISTS` on older DBs) |
| minted_at | bigint | nullable |
| exp | bigint | NOT NULL |
| used_at, used_nonce | bigint, text | NULL until consumed; CHECK both NULL or both set |

Enforces: consumed atomically by `UPDATE ... WHERE token AND request_hash AND used_at IS NULL AND exp > now RETURNING`;
a second use or a token for another request returns no row → **AP-REV-10 / AP-REP-05 (G2)**.
`# ponytail: tokens stored as-is for the prototype; upgrade path is storing sha256(token).`

## people — directory for reviewer separation (ADR-008)
| Column | Type | Constraint |
|---|---|---|
| login | text | PRIMARY KEY (console logins, on_behalf_of ids and agent ids share one namespace) |
| person_id | text | NOT NULL (two logins of one human share it; an agent maps to its operator) |
| roles | text[] | NOT NULL (`reviewer` may mint; `admin` may not; `team` = not a single person) |

Enforces **AP-SEP-12 (G2)**: the reviewer login needs `reviewer`, and its person must differ from the persons of
`Principal.actor` and `Principal.on_behalf_of`; a missing row or a `team` submitter fails closed. Read at mint and
again inside the commit tx `FOR SHARE` (a concurrent edit waits, or aborts the tx before the tool). Seeded by
`db.seed_hero` (`db.PEOPLE`): `rev-alice`/`p-alice`, `rev-bob`/`p-bob` (reviewer), `sub-user123`/`p-user123`,
`admin-ops`/`p-ops` (admin), `user-123` and `agent-7` → `p-user123`. Test-only `rev-user123` (`p-user123`, reviewer)
is inserted by `tests/redteam/test_rt_sep.py`, never seeded. Included in `db.reset` (tests).
`# ponytail: admin edits to people are not yet audit entries (no admin edit path exists; the console backend adds one); team expansion is a non-goal.`

## quarantine — records with an unknown outcome (ADR-014)
| Column | Type | Constraint |
|---|---|---|
| record_id | text | PRIMARY KEY (one block per record) |
| nonce | text | NOT NULL (the burned receipt's nonce) |
| created_at | bigint | NOT NULL, CHECK `>= 0` (UTC epoch seconds) |

Written by the gate's burn path when a commit reached the tool and then rolled back. While a row exists, `prepare`
DENYs the record and `commit` re-checks it inside the tx: **AP-REP-05 (G2)** "unknown outcome from a previous
attempt; reconcile". Removed only by `Gate.release_quarantine(record_id, reviewer)` (admin reconcile path).
Included in `db.reset` (tests).

## audit_log — hash-chained decision log (deck S3.6 / S9.3, `audit.py`)
| Column | Type | Constraint |
|---|---|---|
| seq | bigint | PRIMARY KEY, CHECK `>= 1`; assigned `head + 1` under the audit lock (gap-free; no sequence, which is not transactional) |
| ts | bigint | NOT NULL, CHECK `>= 0` (UTC epoch seconds) |
| kind | text | NOT NULL: `prepare`, `commit`, `mint`, `release_quarantine` |
| request_hash, actor, on_behalf_of, record_id | text | nullable (absent when the request never parsed) |
| decision | text | ALLOW / REVIEW / DENY / EXECUTED / MINTED / REFUSED / RELEASED / NOT_QUARANTINED |
| rules | jsonb | NOT NULL, `[{rule, guarantee, msg}]` |
| detail | jsonb | NOT NULL, kind-specific (nonce, idempotency key, amount, version, reviewer login/person) |
| prev_hash | text | NOT NULL, previous entry's `entry_hash` (genesis `"0"*64`) |
| entry_hash | text | UNIQUE NOT NULL, `sha256(RFC 8785 of every other column)` |

## audit_checkpoints — signed chain heads
| Column | Type | Constraint |
|---|---|---|
| seq | bigint | PRIMARY KEY (the entry it pins) |
| head_hash | text | NOT NULL (that entry's `entry_hash`) |
| ts | bigint | NOT NULL, CHECK `>= 0` |
| sig, kid | text | NOT NULL; Ed25519 by the gate key over RFC 8785 `{seq, head_hash, ts}` |

Both tables are append-only: `BEFORE UPDATE OR DELETE` (row) and `BEFORE TRUNCATE` (statement) triggers call
`audit_append_only()`, which raises. That stops the application and ordinary roles, not a superuser or the owner
(they can disable the trigger); `python -m actionproof.audit verify` detects an edited, deleted, reordered or
truncated entry and a forged checkpoint. `db.reset` (tests only) disables the triggers for its one truncate tx.
Written every `AUDIT_CHECKPOINT_EVERY` entries (default 1).

## Not here
No signing key material, review token or receipt signature is ever stored in the audit tables, and no signing key
material anywhere in the database (invariant 6, ADR-007).
