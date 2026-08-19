"""T031 — checkpoint 2a: migrations apply, states enumerable, audit has no mutation path."""

import pytest
from sqlalchemy import text

from src.models.states import (
    TERMINAL_NODE_STATES,
    TERMINAL_RUN_STATES,
    ExecutionMode,
    GateKind,
    NodeState,
    RunState,
    Surface,
)
from src.store.repository import AuditRepository, audit_repository_is_append_only
from src.trace.correlation import Correlation

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "requirement", "workflow_run", "task_node", "task_dependency", "gate",
    "approval_record", "decision_record", "change_record", "audit_event",
    "replan_event", "trace_link",
}


def test_migrations_create_every_table(clean_db):
    with clean_db.begin() as conn:
        found = {
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).all()
        }
    assert EXPECTED_TABLES <= found


def test_states_are_closed_and_enumerable():
    assert len(list(RunState)) == 9
    assert len(list(NodeState)) == 7
    assert TERMINAL_RUN_STATES <= set(RunState)
    assert TERMINAL_NODE_STATES <= set(NodeState)
    assert {m.value for m in ExecutionMode} == {"agent_authored", "human_executed"}
    assert {s.value for s in Surface} == {"shortener", "orchestrator", "console"}
    assert {g.value for g in GateKind} == {"entry", "exit"}


def test_requirement_ref_cannot_be_blank(clean_db):
    """FR-035: a task with no traceable requirement is refused by the store itself."""
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO requirement (id, submitted_text, resolution_state, submitted_by,"
                " submitted_at) VALUES ('r1', 'x', 'OPEN', 'human:lead', now())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO workflow_run (id, requirement_id, state, wall_clock_ceiling,"
                " retry_ceiling, started_at) VALUES ('run1','r1','PLANNING',3600,3,now())"
            )
        )
    with pytest.raises(Exception):
        with clean_db.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO task_node (id, run_id, description, requirement_ref,"
                    " execution_mode, surface, state, timeout_seconds, max_attempts,"
                    " backoff_seconds) VALUES ('n1','run1','d','   ','agent_authored',"
                    "'orchestrator','PENDING',60,3,2)"
                )
            )


def test_audit_repository_exposes_no_mutation_path():
    """FR-036 first layer: no update/delete method exists in application code."""
    assert audit_repository_is_append_only()
    public = {n for n in dir(AuditRepository) if not n.startswith("_")}
    assert public == {"append", "for_run", "count"}


def test_audit_append_and_read_back(clean_db):
    with clean_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO requirement (id, submitted_text, resolution_state, submitted_by,"
                " submitted_at) VALUES ('r2','x','OPEN','human:lead',now())"
            )
        )
    repo = AuditRepository(clean_db)
    c = Correlation(run_id="run-audit", actor="system")
    repo.append(c, "RUN_CREATED", {"detail": "created"})
    repo.append(c.child(), "STATE_CHANGED", {"from": "PLANNING", "to": "EXECUTING"})
    events = repo.for_run("run-audit")
    assert [e.event_type for e in events] == ["RUN_CREATED", "STATE_CHANGED"]
    assert all(e.trace_id == c.trace_id for e in events)
    assert repo.count("run-audit") == 2


def test_audit_refuses_payload_containing_secrets(clean_db):
    """FR-038 / SC-015: fail loudly rather than redact quietly."""
    from src.api.errors import OrchestratorError

    repo = AuditRepository(clean_db)
    c = Correlation(run_id="run-secret")
    with pytest.raises(OrchestratorError):
        repo.append(c, "AGENT_CALL", {"config": {"api_key": "sk-should-never-be-here"}})
