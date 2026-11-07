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
-- AP-CUM-03 sums by actor+counterparty inside the commit tx.
CREATE INDEX IF NOT EXISTS commits_actor_vendor ON commits (actor, vendor_id);
-- ADR-009: refunds already committed against one payment (refundable balance), re-read inside the commit tx.
CREATE INDEX IF NOT EXISTS commits_record ON commits (record_id);

CREATE TABLE IF NOT EXISTS review_tokens (
    token        text PRIMARY KEY,
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

-- Directory (ADR-008, AP-SEP-12): console logins, on_behalf_of ids and agent ids (mapped to their operator) in
-- one namespace. Two logins of one human share a person_id. Separation of duties compares person_id, never logins.
-- roles: 'reviewer' may mint review tokens; 'admin' may not; 'team' marks an id that is not a single person.
CREATE TABLE IF NOT EXISTS people (
    login     text PRIMARY KEY,
    person_id text   NOT NULL,
    roles     text[] NOT NULL
);

-- A record whose last commit reached the tool but rolled back (unknown outcome). prepare and commit refuse the
-- record (AP-REP-05 / G2) until a reviewer reconciles it (Gate.release_quarantine). ADR-014.
CREATE TABLE IF NOT EXISTS quarantine (
    record_id  text PRIMARY KEY,
    nonce      text   NOT NULL,
    created_at bigint NOT NULL CHECK (created_at >= 0)
);

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
