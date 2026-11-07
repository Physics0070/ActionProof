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
    vendors      text[] NOT NULL
);

CREATE TABLE IF NOT EXISTS commits (
    id              bigserial PRIMARY KEY,
    nonce           text UNIQUE NOT NULL,                        -- G2 / AP-REP-05
    idempotency_key text UNIQUE NOT NULL,                        -- G2 / AP-REP-05
    request_hash    text NOT NULL,
    actor           text NOT NULL,
    on_behalf_of    text NOT NULL,
    vendor_id       text NOT NULL,
    amount          numeric(18,2) NOT NULL CHECK (amount >= 0),
    record_id       text NOT NULL,
    created_at      bigint NOT NULL CHECK (created_at >= 0)
);
-- AP-CUM-03 sums by actor+vendor inside the commit tx.
CREATE INDEX IF NOT EXISTS commits_actor_vendor ON commits (actor, vendor_id);

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
