"""T063/T066/T067/T068 — decision lineage, audit invariants, rollback linkage,
and the requirement → task → change → test round trip."""

import pytest
from sqlalchemy import text

from src.agent.changes import apply_write
from src.audit.trace import TraceStore
from src.engine.decisions import DecisionStore
from src.engine.identity import APPROVER_ROLE, Actor
from src.engine.rollback import RollbackFailed, RollbackStore, revert_change
from src.store.repository import AuditRepository, ChangeStore
from src.trace.correlation import Correlation

pytestmark = [pytest.mark.failure, pytest.mark.integration]

HUMAN = Actor(id="human:lead", roles=frozenset({APPROVER_ROLE}))


@pytest.fixture()
def seeded(clean_db):
    from src.engine.decompose import TaskNode
    from src.engine.state import StateStore
    from src.models.states import ExecutionMode, Surface

    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.persist_nodes("run-1", [
        TaskNode(id="t1", description="d", requirement_ref="FR-004",
                 execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
                 declared_outputs=("orchestrator/src/agent/probe.py",)),
    ])
    return clean_db


# --- decision lineage -------------------------------------------------------

def test_decision_lineage_persists_every_required_field(seeded):
    store = DecisionStore(seeded)
    record = store.record(
        run_id="run-1",
        alternatives=[{"option": "SQLite", "rejected_because": "single writer"},
                      {"option": "PostgreSQL"}],
        selection="PostgreSQL",
        rationale="concurrent writers and durable commit semantics",
        actor=HUMAN.id,
        serves_ref="FR-025",
    )
    stored = store.for_run("run-1")
    assert len(stored) == 1
    only = stored[0]
    assert only.selection == "PostgreSQL"
    assert only.actor == "human:lead"
    assert only.rationale
    assert only.serves_ref == "FR-025"
    assert only.decided_at
    assert {a["option"] for a in only.alternatives} == {"SQLite", "PostgreSQL"}
    assert only.id == record.id


# --- audit invariants -------------------------------------------------------

def test_audit_repository_has_no_update_or_delete_method():
    public = {n for n in dir(AuditRepository) if not n.startswith("_")}
    assert public == {"append", "for_run", "count"}


def test_runtime_role_cannot_update_delete_or_truncate_audit(seeded):
    """The database refuses it, not merely the application (FR-036).

    The privilege model from ops/db/02-apply-runtime-grants.sql is reproduced
    here on the throwaway container so the invariant is proven, not assumed.
    """
    repo = AuditRepository(seeded)
    repo.append(Correlation(run_id="run-1"), "RUN_CREATED", {"x": 1})

    with seeded.begin() as conn:
        conn.execute(text("DROP ROLE IF EXISTS runtime_probe"))
        conn.execute(text("CREATE ROLE runtime_probe LOGIN PASSWORD 'probe-only-local'"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO runtime_probe"))
        conn.execute(text("GRANT SELECT, INSERT ON public.audit_event TO runtime_probe"))
        conn.execute(text("REVOKE UPDATE, DELETE ON public.audit_event FROM runtime_probe"))
        conn.execute(
            text("REVOKE TRUNCATE, REFERENCES, TRIGGER ON public.audit_event FROM runtime_probe")
        )
        conn.execute(text("GRANT USAGE ON SEQUENCE public.audit_event_id_seq TO runtime_probe"))

    from sqlalchemy import create_engine

    url = seeded.url.set(username="runtime_probe", password="probe-only-local")
    probe = create_engine(url, future=True)
    try:
        with probe.begin() as conn:
            assert conn.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 1
            conn.execute(
                text(
                    "INSERT INTO audit_event (run_id,event_type,actor,trace_id,span_id,"
                    "payload,occurred_at) VALUES ('run-1','X','system','t','s','{}'::jsonb,now())"
                )
            )
        for statement in (
            "UPDATE audit_event SET actor = 'tampered'",
            "DELETE FROM audit_event",
            "TRUNCATE audit_event",
        ):
            with pytest.raises(Exception) as exc, probe.begin() as conn:
                conn.execute(text(statement))
            assert "permission denied" in str(exc.value).lower(), statement
    finally:
        probe.dispose()

    assert AuditRepository(seeded).count("run-1") == 2


# --- change records and rollback linkage ------------------------------------

def test_change_record_persists_with_run_and_task_linkage(seeded, tmp_path):
    target = tmp_path / "probe.py"
    target.write_text("original\n", encoding="utf-8")
    record = apply_write(
        path=target, content="rewritten\n", task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path="orchestrator/src/agent/probe.py",
        now_iso="2026-08-18T00:00:00+00:00",
    )
    store = ChangeStore(seeded)
    change_id = store.persist(record, run_id="run-1")

    stored = store.for_run("run-1")
    assert len(stored) == 1
    assert stored[0].task_id == "t1"
    assert stored[0].run_id == "run-1"
    assert stored[0].prior_state == "original\n"
    assert stored[0].prior_sha256 and stored[0].new_sha256
    assert stored[0].id == change_id


def test_successful_rollback_links_to_the_original_change(seeded, tmp_path):
    target = tmp_path / "probe.py"
    target.write_text("v0\n", encoding="utf-8")
    record = apply_write(
        path=target, content="v1\n", task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path="orchestrator/src/agent/probe.py",
        now_iso="2026-08-18T00:00:00+00:00",
    )
    change_id = ChangeStore(seeded).persist(record, run_id="run-1")

    event = revert_change(
        engine=seeded, run_id="run-1", change_id=change_id, record=record, path=target,
    )
    assert target.read_text() == "v0\n"
    assert event.outcome == "succeeded"
    assert event.change_id == change_id

    events = RollbackStore(seeded).for_change(change_id)
    assert [e.outcome for e in events] == ["succeeded"]


def test_failed_rollback_safe_stops_and_is_audited(seeded, tmp_path):
    target = tmp_path / "probe.py"
    target.write_text("v0\n", encoding="utf-8")
    record = apply_write(
        path=target, content="v1\n", task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path="orchestrator/src/agent/probe.py",
        now_iso="2026-08-18T00:00:00+00:00",
    )
    change_id = ChangeStore(seeded).persist(record, run_id="run-1")

    target.write_text("edited by someone else\n", encoding="utf-8")
    with pytest.raises(RollbackFailed):
        revert_change(engine=seeded, run_id="run-1", change_id=change_id,
                      record=record, path=target)

    assert target.read_text() == "edited by someone else\n"
    events = RollbackStore(seeded).for_change(change_id)
    assert [e.outcome for e in events] == ["failed"]
    audit_types = [e.event_type for e in AuditRepository(seeded).for_run("run-1")]
    assert "ROLLBACK_FAILED" in audit_types
    assert "SAFE_STOP_ROLLBACK_FAILED" in audit_types


# --- traceability round trip ------------------------------------------------

def test_requirement_to_task_to_change_to_test_round_trip(seeded, tmp_path):
    target = tmp_path / "probe.py"
    record = apply_write(
        path=target, content="new\n", task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path="orchestrator/src/agent/probe.py",
        now_iso="2026-08-18T00:00:00+00:00",
    )
    change_id = ChangeStore(seeded).persist(record, run_id="run-1")

    trace = TraceStore(seeded)
    trace.link(requirement_ref="FR-004", task_ref="t1", change_ref=change_id,
               test_ref="tests/failure/test_lineage_and_rollback.py::round_trip")

    forward = trace.for_requirement("FR-004")
    assert forward.tasks == ("t1",)
    assert forward.changes == (change_id,)
    assert forward.tests[0].endswith("round_trip")

    backward = trace.requirement_for_change(change_id)
    assert backward == "FR-004"


def test_a_change_with_no_requirement_is_reported_as_untraceable(seeded, tmp_path):
    target = tmp_path / "probe.py"
    record = apply_write(
        path=target, content="new\n", task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path="orchestrator/src/agent/probe.py",
        now_iso="2026-08-18T00:00:00+00:00",
    )
    change_id = ChangeStore(seeded).persist(record, run_id="run-1")
    assert TraceStore(seeded).requirement_for_change(change_id) is None
    assert change_id in TraceStore(seeded).untraceable_changes("run-1")
