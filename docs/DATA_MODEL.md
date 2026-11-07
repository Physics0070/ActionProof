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
| record_id | text | PRIMARY KEY (e.g. `invoice:INV-2048`, `po:PO-2048`) |
| kind | text | NOT NULL |
| data | jsonb | NOT NULL; amounts inside are 2 dp strings |
| version | bigint | NOT NULL, CHECK `>= 0` |

Enforces: `version` is bound into the receipt and re-read `FOR UPDATE` at commit; mismatch = **AP-STALE-07 (G2)**.
`data` supplies `vendor_id` and SoR totals for G1 verification (never the agent's claims).

## delegations — on-behalf-of scope
| Column | Type | Constraint |
|---|---|---|
| on_behalf_of | text | PRIMARY KEY |
| max_amount | numeric(18,2) | NOT NULL, CHECK `>= 0` |
| vendors | text[] | NOT NULL |

Enforces: policy `scope` input; amount above `max_amount` or vendor not listed = **AP-SCOPE-02 (G1)**.

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

Index `commits_actor_vendor (actor, vendor_id)`.
Enforces: UNIQUE `nonce` / `idempotency_key` = a receipt or key can commit once; a duplicate insert raises
`UniqueViolation` → **AP-REP-05 (G2)**. `SUM(amount)` by actor+vendor inside the commit tx = **AP-CUM-03 (G1, ADR-006)**.

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
`# ponytail: admin edits to people are audited with audit.py (Phase 5); team expansion is a non-goal.`

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

## Not here
Audit tables arrive in Phase 5. No signing key material is ever stored in the database (invariant 6, ADR-007).
