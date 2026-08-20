-- Clarification requests and human answers (FR-028, FR-046).
--
-- Separate from approval_request because the shapes differ: an approval decides
-- a proposed action, a clarification answers a question. Conflating them would
-- make "approve" mean two things.

CREATE TABLE IF NOT EXISTS clarification_request (
    id            TEXT PRIMARY KEY,
    run_id        TEXT        NOT NULL REFERENCES workflow_run(id),
    question      TEXT        NOT NULL,
    affects       TEXT        NOT NULL,   -- scope | security | user_visible_behaviour
    requested_by  TEXT        NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL,
    state         TEXT        NOT NULL,   -- pending | answered
    answer        TEXT,
    answered_by   TEXT,
    answered_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS clarification_run_idx ON clarification_request (run_id, state);
