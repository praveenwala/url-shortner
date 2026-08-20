-- US4: upstream change intake and replacement lineage (FR-033, FR-044).

CREATE TABLE IF NOT EXISTS change_request (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT        NOT NULL REFERENCES workflow_run(id),
    prior_requirement_id  TEXT        NOT NULL REFERENCES requirement(id),
    text                  TEXT        NOT NULL,
    reason                TEXT        NOT NULL,   -- why replanning was triggered
    submitted_by          TEXT        NOT NULL,
    submitted_at          TIMESTAMPTZ NOT NULL,
    state                 TEXT        NOT NULL    -- submitted | analysed | replanned | awaiting_approval
);
CREATE INDEX IF NOT EXISTS change_request_run_idx ON change_request (run_id);

-- A replacement node names what it supersedes. The superseded node is never
-- deleted or rewritten: its result stays queryable, which is what makes staleness
-- a flag rather than an erasure (FR-033).
ALTER TABLE task_node ADD COLUMN IF NOT EXISTS supersedes TEXT;
CREATE INDEX IF NOT EXISTS task_node_supersedes_idx ON task_node (supersedes)
    WHERE supersedes IS NOT NULL;
