-- Checkpoint 2e: approval requests, rollback linkage, run scope.

CREATE TABLE IF NOT EXISTS approval_request (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT        NOT NULL REFERENCES workflow_run(id),
    checkpoint          TEXT        NOT NULL,
    detail              JSONB       NOT NULL,
    action_fingerprint  TEXT        NOT NULL,   -- an approval covers one action
    requested_by        TEXT        NOT NULL,
    requested_at        TIMESTAMPTZ NOT NULL,
    state               TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS approval_request_run_idx ON approval_request (run_id, state);

-- approval_record gains its link to the request it decides.
ALTER TABLE approval_record ADD COLUMN IF NOT EXISTS request_id TEXT;

-- change_record gains run linkage and content hashes for rollback (FR-044).
ALTER TABLE change_record ADD COLUMN IF NOT EXISTS run_id       TEXT;
ALTER TABLE change_record ADD COLUMN IF NOT EXISTS prior_sha256 TEXT;
ALTER TABLE change_record ADD COLUMN IF NOT EXISTS new_sha256   TEXT;
ALTER TABLE change_record ADD COLUMN IF NOT EXISTS existed      BOOLEAN NOT NULL DEFAULT TRUE;

-- A rollback is an event in its own right, linked to the change it reverses.
CREATE TABLE IF NOT EXISTS rollback_event (
    id           TEXT PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    change_id    TEXT        NOT NULL REFERENCES change_record(id),
    outcome      TEXT        NOT NULL,   -- succeeded | failed
    reason       TEXT,
    occurred_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS rollback_event_change_idx ON rollback_event (change_id);

-- The approved scope of a run: work outside it halts for a human (FR-039).
ALTER TABLE workflow_run ADD COLUMN IF NOT EXISTS approved_scope JSONB NOT NULL DEFAULT '[]'::jsonb;
