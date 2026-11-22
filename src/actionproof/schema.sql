-- ActionProof system of record. Idempotent. Money is numeric(18,2) (invariant 4).
-- UNIQUE / CHECK constraints are the G2 enforcement: the database, not app code, refuses replays.
-- See docs/DATA_MODEL.md.

CREATE TABLE IF NOT EXISTS records (
    record_id text PRIMARY KEY,
    kind      text   NOT NULL,
    data      jsonb  NOT NULL,
    version   bigint NOT NULL CHECK (version >= 0)            -- AP-STALE-07
);

CREATE TABLE IF NOT EXISTS delegations (
    on_behalf_of text PRIMARY KEY,
    max_amount   numeric(18,2) NOT NULL CHECK (max_amount >= 0), -- AP-SCOPE-02
    vendors      text[] NOT NULL,                                -- invoice counterparties in scope
    customers    text[] NOT NULL DEFAULT '{}'                    -- refund counterparties in scope (ADR-009)
);
-- Databases created before ADR-009.
ALTER TABLE delegations ADD COLUMN IF NOT EXISTS customers text[] NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS commits (
    id              bigserial PRIMARY KEY,
    nonce           text UNIQUE NOT NULL,                        -- G2 / AP-REP-05
    idempotency_key text UNIQUE NOT NULL,                        -- G2 / AP-REP-05
    request_hash    text NOT NULL,
    actor           text NOT NULL,
    on_behalf_of    text NOT NULL,
    vendor_id       text NOT NULL,                               -- the COUNTERPARTY id (ADR-015): vendor or customer
    amount          numeric(18,2) NOT NULL CHECK (amount >= 0),
    record_id       text NOT NULL,                               -- invoice:<id> | payment:<id> (says which tool)
    created_at      bigint NOT NULL CHECK (created_at >= 0)
);
COMMENT ON COLUMN commits.vendor_id IS
    'counterparty id from the system of record: vendor (payments.approve_invoice) or customer (payments.refund_payment); ADR-015';
-- AP-CUM-03 sums by actor+counterparty inside the commit tx, and by person (people join on on_behalf_of)+counterparty
-- (ADR-016; no column: the person key is read through the directory at decision time).
CREATE INDEX IF NOT EXISTS commits_actor_vendor ON commits (actor, vendor_id);
-- ADR-009: refunds already committed against one payment (refundable balance), re-read inside the commit tx.
CREATE INDEX IF NOT EXISTS commits_record ON commits (record_id);

-- ADR-025: only sha256(token) is stored (hex); the raw token is shown once to the reviewer and cannot be recovered here.
CREATE TABLE IF NOT EXISTS review_tokens (
    token_hash   text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL,
    submitter    text NOT NULL,
    minted_by    text NOT NULL,                                 -- reviewer login (console session subject)
    minted_by_person text NOT NULL,                             -- people.person_id at mint (ADR-008)
    minted_at    bigint,
    exp          bigint NOT NULL,
    used_at      bigint NULL,
    used_nonce   text NULL,
    -- one-use (G2 / AP-REV-10): consumed atomically, and both fields set together or not at all
    CONSTRAINT review_tokens_used_pair CHECK ((used_at IS NULL) = (used_nonce IS NULL))
);

-- Databases created before ADR-008 (the gate always writes it; new tables have it NOT NULL).
ALTER TABLE review_tokens ADD COLUMN IF NOT EXISTS minted_by_person text;

-- ADR-025 migration: plaintext `token` -> sha256 hex digest. Outstanding tokens keep working (the holder's raw token
-- hashes to the stored digest), used rows keep their used_at/used_nonce, then the plaintext column is dropped.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()
             AND table_name = 'review_tokens' AND column_name = 'token') THEN
    ALTER TABLE review_tokens ADD COLUMN IF NOT EXISTS token_hash text;
    UPDATE review_tokens SET token_hash = encode(sha256(convert_to(token, 'UTF8')), 'hex') WHERE token_hash IS NULL;
    ALTER TABLE review_tokens DROP CONSTRAINT review_tokens_pkey;
    ALTER TABLE review_tokens ALTER COLUMN token_hash SET NOT NULL;
    ALTER TABLE review_tokens ADD PRIMARY KEY (token_hash);
    ALTER TABLE review_tokens DROP COLUMN token;
  END IF;
END $$;

-- Directory (ADR-008, AP-SEP-12): console logins, on_behalf_of ids and agent ids (mapped to their operator) in
-- one namespace. Two logins of one human share a person_id. Separation of duties compares person_id, never logins.
-- roles: 'reviewer' may mint review tokens; 'admin' may not; 'team' marks an id that is not a single person.
CREATE TABLE IF NOT EXISTS people (
    login     text PRIMARY KEY,
    person_id text   NOT NULL,
    roles     text[] NOT NULL
);
-- ADR-027: a disabled identity can neither review nor be reviewed for (fail closed in _separation) and cannot log in.
ALTER TABLE people ADD COLUMN IF NOT EXISTS disabled boolean NOT NULL DEFAULT false;

-- A record whose last commit reached the tool but rolled back (unknown outcome). prepare and commit refuse the
-- record (AP-REP-05 / G2) until a reviewer reconciles it (Gate.release_quarantine). ADR-014.
CREATE TABLE IF NOT EXISTS quarantine (
    record_id  text PRIMARY KEY,
    nonce      text   NOT NULL,
    created_at bigint NOT NULL CHECK (created_at >= 0)
);

-- Written on its own connection (committed) just BEFORE the tool is called. A marker whose nonce has no commits row
-- means the tool may have run and the gate died before recording it (crash, lost connection): the record counts as
-- quarantined until Gate.release_quarantine. After a normal commit or a burn the commits row exists, so it blocks nothing.
CREATE TABLE IF NOT EXISTS tool_reached (
    nonce      text PRIMARY KEY,
    record_id  text   NOT NULL,
    created_at bigint NOT NULL CHECK (created_at >= 0)
);

-- ADR-022: the marker now carries the complete logical reservation, so an unresolved execution keeps counting
-- against the caps and keeps its request idempotency key. Columns are nullable only so rows from the ADR-019 version
-- of this table survive the migration; the gate always writes all of them. An unresolved row with ANY NULL column is a legacy marker: its spend is
-- unknown, so the gate blocks every cap-sensitive write until it is reconciled (ADR-024); the view excludes it, never as zero.
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS request_hash    text;
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS actor           text;
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS on_behalf_of    text;
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS vendor_id       text;
ALTER TABLE tool_reached ADD COLUMN IF NOT EXISTS amount          numeric(18,2) CHECK (amount >= 0);
CREATE UNIQUE INDEX IF NOT EXISTS tool_reached_idem ON tool_reached (idempotency_key);  -- G2 / AP-REP-05, NULLs allowed

-- Everything that counts against a cap: committed (or burned) rows plus unresolved executions (a marker with no
-- commits row). Exact numeric(18,2); the caps sum THIS, never commits alone.
CREATE OR REPLACE VIEW reservations AS
    SELECT nonce, idempotency_key, actor, on_behalf_of, vendor_id, amount, record_id FROM commits
    UNION ALL
    SELECT t.nonce, t.idempotency_key, t.actor, t.on_behalf_of, t.vendor_id, t.amount, t.record_id
      FROM tool_reached t
     WHERE t.amount IS NOT NULL AND NOT EXISTS (SELECT 1 FROM commits c WHERE c.nonce = t.nonce);

-- MCP server (Task 5.4, deck slide 3 step 1). A REVIEW decision parks here until a human completes it in the
-- console (review.complete_review). The signed receipt is stored server-side only and never returned to the agent.
-- status: pending -> executed | denied | rejected ('approved' is reserved for a console that splits mint and commit).
CREATE TABLE IF NOT EXISTS pending_reviews (
    request_hash text PRIMARY KEY,
    request      jsonb  NOT NULL,                              -- the strict ActionRequest JSON
    receipt      jsonb  NOT NULL,                              -- gate-signed REVIEW receipt (server-side only)
    actor        text   NOT NULL,                              -- the transport Principal (ADR-012)
    on_behalf_of text   NOT NULL,
    created_at   bigint NOT NULL CHECK (created_at >= 0),
    status       text   NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'approved', 'rejected', 'executed', 'denied')),
    reasons      jsonb  NOT NULL DEFAULT '[]',                 -- [{rule, guarantee, msg}] of the latest outcome
    reviewer     text   NULL,                                  -- console session subject that completed it
    decided_at   bigint NULL
);
CREATE INDEX IF NOT EXISTS pending_reviews_principal ON pending_reviews (actor, on_behalf_of);
-- Reviewer view (Task 5.6), written once at park from the PrepareResult; none of it is receipt or key material.
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS card   text  NULL;               -- deck slide 1 text
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS claims jsonb NOT NULL DEFAULT '{}'; -- {arg: verify.ClaimResult}
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS diff   jsonb NULL;               -- tool dry-run diff
ALTER TABLE pending_reviews ADD COLUMN IF NOT EXISTS before jsonb NULL;               -- {data, version} at prepare
CREATE INDEX IF NOT EXISTS pending_reviews_queue ON pending_reviews (created_at DESC, request_hash);

-- Review console (Task 5.6, src/actionproof/console.py). Passwords are argon2id hashes; a session row stores only
-- sha256(session id), so a database read cannot be replayed as a cookie. Roles come from people.roles.
CREATE TABLE IF NOT EXISTS console_users (
    login         text PRIMARY KEY REFERENCES people (login) ON DELETE CASCADE,
    password_hash text    NOT NULL CHECK (password_hash LIKE '$argon2%'),
    disabled      boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS console_sessions (
    sid_hash   text PRIMARY KEY CHECK (sid_hash ~ '^[0-9a-f]{64}$'),
    login      text   NOT NULL REFERENCES console_users (login) ON DELETE CASCADE,
    csrf_token text   NOT NULL,
    created_at bigint NOT NULL CHECK (created_at >= 0),
    expires_at bigint NOT NULL CHECK (expires_at >= 0),
    last_seen  bigint NOT NULL CHECK (last_seen >= 0)
);

-- HTTP transport clients (ADR-012): the bearer token's sha256 maps to the Principal. The token itself is never
-- stored. Seed with scripts/seed_api_client.py.
CREATE TABLE IF NOT EXISTS api_clients (
    token_hash   text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    actor        text   NOT NULL,
    on_behalf_of text   NOT NULL,
    created_at   bigint NOT NULL CHECK (created_at >= 0)
);

-- ADR-026 credential lifecycle: id, label, issuer, registry-tool scopes, expiry, revocation, last use.
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS cred_id text;
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS label text;
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS issuer text;
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS scopes text[];
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS expires_at bigint;
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS revoked_at bigint;
ALTER TABLE api_clients ADD COLUMN IF NOT EXISTS last_used_at bigint;
-- Legacy rows (pre-ADR-026) keep exactly what they could do (both registry tools) but now EXPIRE 30 days after this
-- migration; they are never permanently valid. Re-issue with `python -m actionproof.credentials`.
UPDATE api_clients SET cred_id = 'legacy-' || substr(token_hash, 1, 12), label = 'legacy (pre-ADR-026)',
    issuer = 'migration', scopes = ARRAY['payments.approve_invoice', 'payments.refund_payment'],
    expires_at = extract(epoch FROM now())::bigint + 2592000 WHERE cred_id IS NULL;
ALTER TABLE api_clients ALTER COLUMN cred_id SET NOT NULL;
ALTER TABLE api_clients ALTER COLUMN scopes SET NOT NULL;
ALTER TABLE api_clients ALTER COLUMN expires_at SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS api_clients_cred_id ON api_clients (cred_id);

-- Audit chain (deck slide 3 step 5, S9.3; src/actionproof/audit.py). entry_hash = sha256(RFC 8785 of every other
-- column, prev_hash included). seq is assigned by audit.append under the audit lock (max + 1), not by a sequence:
-- a sequence is not transactional, so a rolled-back commit entry would leave a gap.
CREATE TABLE IF NOT EXISTS audit_log (
    seq          bigint PRIMARY KEY CHECK (seq >= 1),
    ts           bigint NOT NULL CHECK (ts >= 0),
    kind         text   NOT NULL,                              -- prepare | commit | mint | release_quarantine
    request_hash text,
    actor        text,
    on_behalf_of text,
    record_id    text,
    decision     text,
    rules        jsonb  NOT NULL,                              -- [{rule, guarantee, msg}]
    detail       jsonb  NOT NULL,
    prev_hash    text   NOT NULL,
    entry_hash   text   UNIQUE NOT NULL
);

-- Gate-signed (Ed25519, the receipt key) {seq, head_hash, ts}: pins the chain head so a truncated tail is detected.
CREATE TABLE IF NOT EXISTS audit_checkpoints (
    seq       bigint PRIMARY KEY,
    head_hash text   NOT NULL,
    ts        bigint NOT NULL CHECK (ts >= 0),
    sig       text   NOT NULL,
    kid       text   NOT NULL
);

-- Append-only. A superuser or the table owner can still disable this trigger (or set session_replication_role);
-- the hash chain and the signed checkpoints are what DETECT that tampering (audit.py verify).
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit tables are append-only (% on %)', TG_OP, TG_TABLE_NAME;
END $$;
CREATE OR REPLACE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();
CREATE OR REPLACE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
CREATE OR REPLACE TRIGGER audit_checkpoints_append_only BEFORE UPDATE OR DELETE ON audit_checkpoints
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();
CREATE OR REPLACE TRIGGER audit_checkpoints_no_truncate BEFORE TRUNCATE ON audit_checkpoints
    FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

-- ADR-029 execution journal (src/actionproof/journal.py): append-only, its OWN hash chain (entry_hash = sha256(RFC 8785
-- of every other column)), seq assigned under a journal-only advisory lock, written on its own connections (never
-- under the audit lock). Additive: tool_reached and the reservations view keep their meaning; an execution is
-- journaled from RESERVATION_CREATED on, and markers written before this table existed get no events (no backfill).
CREATE TABLE IF NOT EXISTS execution_journal (
    seq             bigint PRIMARY KEY CHECK (seq >= 1),
    ts              bigint NOT NULL CHECK (ts >= 0),
    execution_id    text   NOT NULL,                           -- "ex-" + sha256(nonce)[:32], one per receipt
    event           text   NOT NULL CHECK (event IN ('RESERVATION_CREATED', 'DISPATCH_STARTED', 'EXECUTION_CONFIRMED',
                                                     'EXECUTION_FAILED', 'EXECUTION_UNKNOWN', 'RECONCILIATION_STARTED',
                                                     'RECONCILIATION_COMPLETED')),
    nonce           text   NOT NULL,
    request_hash    text   NOT NULL,
    idempotency_key text   NOT NULL,
    record_id       text   NOT NULL,
    actor           text   NOT NULL,
    on_behalf_of    text   NOT NULL,
    vendor_id       text   NOT NULL,                           -- counterparty (ADR-015)
    amount          numeric(18,2) NOT NULL CHECK (amount >= 0),
    detail          jsonb  NOT NULL,
    prev_hash       text   NOT NULL,
    entry_hash      text   UNIQUE NOT NULL
);
-- One reservation and one dispatch per execution, and at most ONE outcome (confirmed, failed or unknown).
CREATE UNIQUE INDEX IF NOT EXISTS execution_journal_once ON execution_journal (execution_id, event)
    WHERE event IN ('RESERVATION_CREATED', 'DISPATCH_STARTED');
CREATE UNIQUE INDEX IF NOT EXISTS execution_journal_outcome ON execution_journal (execution_id)
    WHERE event IN ('EXECUTION_CONFIRMED', 'EXECUTION_FAILED', 'EXECUTION_UNKNOWN');
CREATE INDEX IF NOT EXISTS execution_journal_nonce ON execution_journal (nonce);
CREATE OR REPLACE TRIGGER execution_journal_append_only BEFORE UPDATE OR DELETE ON execution_journal
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();
CREATE OR REPLACE TRIGGER execution_journal_no_truncate BEFORE TRUNCATE ON execution_journal
    FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
