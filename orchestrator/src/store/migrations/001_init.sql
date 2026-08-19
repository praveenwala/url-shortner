-- Orchestrator schema (data-model.md). PostgreSQL.
-- Owned by orchestrator_db only; no reference crosses to shortener_db (R3).

CREATE TABLE IF NOT EXISTS requirement (
    id                TEXT PRIMARY KEY,
    submitted_text    TEXT        NOT NULL,
    interpretation    JSONB,
    ambiguities       JSONB       NOT NULL DEFAULT '[]'::jsonb,
    resolution_state  TEXT        NOT NULL,
    submitted_by      TEXT        NOT NULL,
    submitted_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_run (
    id                  TEXT PRIMARY KEY,
    requirement_id      TEXT        NOT NULL REFERENCES requirement(id),
    state               TEXT        NOT NULL,
    waiting_on          TEXT,
    wall_clock_ceiling  INTEGER     NOT NULL,
    retry_ceiling       INTEGER     NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL,
    ended_at            TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS task_node (
    id               TEXT PRIMARY KEY,
    run_id           TEXT        NOT NULL REFERENCES workflow_run(id),
    description      TEXT        NOT NULL,
    requirement_ref  TEXT        NOT NULL,          -- FR-035: never null
    execution_mode   TEXT        NOT NULL,          -- FR-042: fixed at planning time
    surface          TEXT        NOT NULL,          -- R6: scopes the agent allow-list
    is_sync          BOOLEAN     NOT NULL DEFAULT FALSE,
    state            TEXT        NOT NULL,
    is_stale         BOOLEAN     NOT NULL DEFAULT FALSE,   -- FR-033: flag, not a state
    attempt_count    INTEGER     NOT NULL DEFAULT 0,
    timeout_seconds  INTEGER     NOT NULL,
    max_attempts     INTEGER     NOT NULL,
    backoff_seconds  INTEGER     NOT NULL,
    result           JSONB,
    CONSTRAINT requirement_ref_not_blank CHECK (length(trim(requirement_ref)) > 0)
);
CREATE INDEX IF NOT EXISTS task_node_run_idx ON task_node (run_id, state);

CREATE TABLE IF NOT EXISTS task_dependency (
    run_id     TEXT NOT NULL REFERENCES workflow_run(id),
    from_node  TEXT NOT NULL REFERENCES task_node(id),
    to_node    TEXT NOT NULL REFERENCES task_node(id),
    PRIMARY KEY (run_id, from_node, to_node)
);

CREATE TABLE IF NOT EXISTS gate (
    id            TEXT PRIMARY KEY,
    run_id        TEXT        NOT NULL REFERENCES workflow_run(id),
    stage         TEXT        NOT NULL,
    kind          TEXT        NOT NULL,   -- entry | exit
    criteria      TEXT        NOT NULL,
    outcome       TEXT,
    reason        TEXT,
    evaluated_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS approval_record (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT        NOT NULL REFERENCES workflow_run(id),
    checkpoint          TEXT        NOT NULL,
    human_actor         TEXT        NOT NULL,
    approver_role_held  TEXT        NOT NULL,
    decision            TEXT        NOT NULL,
    rationale           TEXT        NOT NULL,
    decided_at          TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_record (
    id            TEXT PRIMARY KEY,
    run_id        TEXT        NOT NULL REFERENCES workflow_run(id),
    alternatives  JSONB       NOT NULL,
    selection     TEXT        NOT NULL,
    rationale     TEXT        NOT NULL,
    actor         TEXT        NOT NULL,
    decided_at    TIMESTAMPTZ NOT NULL,
    serves_ref    TEXT        NOT NULL
);

CREATE TABLE IF NOT EXISTS change_record (
    id               TEXT PRIMARY KEY,
    task_id          TEXT        NOT NULL REFERENCES task_node(id),
    surface          TEXT        NOT NULL,
    artifact_path    TEXT        NOT NULL,
    execution_mode   TEXT        NOT NULL,
    prior_state      TEXT,
    applied_at       TIMESTAMPTZ NOT NULL,
    approving_human  TEXT
);

-- Append-only (FR-036). Immutability is also enforced by role privilege in
-- ops/db/provision.sql: the orchestrator role holds INSERT and SELECT only.
CREATE TABLE IF NOT EXISTS audit_event (
    id           BIGSERIAL PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    event_type   TEXT        NOT NULL,
    actor        TEXT        NOT NULL,
    trace_id     TEXT        NOT NULL,
    span_id      TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_event_run_idx ON audit_event (run_id, id);

CREATE TABLE IF NOT EXISTS replan_event (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT        NOT NULL REFERENCES workflow_run(id),
    trigger             TEXT        NOT NULL,
    blast_radius        JSONB       NOT NULL,
    nodes_marked_stale  JSONB       NOT NULL,
    graph_delta         JSONB       NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS trace_link (
    id               BIGSERIAL PRIMARY KEY,
    requirement_ref  TEXT NOT NULL,
    task_ref         TEXT,
    change_ref       TEXT,
    test_ref         TEXT
);
CREATE INDEX IF NOT EXISTS trace_link_req_idx ON trace_link (requirement_ref);
