"""Halt-before-apply and audit coverage (FR-029, FR-036, FR-043, FR-049).

The distinction being tested: the change is *not made and then undone*. It is
never made. The run reaches WAITING_FOR_HUMAN with the artifact untouched.
"""

import pytest

from src.agent.dispatch import BoundedTask, Dispatcher
from src.engine.approvals import ApprovalService, Checkpoint, Decision
from src.engine.decompose import TaskNode
from src.engine.identity import APPROVER_ROLE, Actor
from src.engine.state import StateStore
from src.models.states import ExecutionMode, RunState, Surface
from src.store.repository import AuditRepository

pytestmark = [pytest.mark.failure, pytest.mark.integration]

HUMAN = Actor(id="human:lead", roles=frozenset({APPROVER_ROLE}))
ALL_APPROVALS = frozenset(
    {"interface", "acceptance_criteria", "dependencies", "security_constraints"}
)
REPO = __import__("pathlib").Path(__file__).resolve().parents[3]


@pytest.fixture()
def wired(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    return store, ApprovalService(engine=clean_db), AuditRepository(clean_db), clean_db


def _task():
    return TaskNode(
        id="t1", description="add a dependency", requirement_ref="FR-041",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/pyproject.toml",),
    )


def test_checkpoint_crossing_write_halts_before_mutation(wired):
    store, approvals, audit, engine = wired
    target = REPO / "orchestrator" / "pyproject.toml"
    before = target.read_bytes()

    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_task(), ALL_APPROVALS),
        run_id="run-1", state_store=store, approvals=approvals, audit=audit,
    )
    turns = iter([[("write_file", {"path": "orchestrator/pyproject.toml",
                                   "content": "[project]\nname='x'\n"})], []])
    outcome = dispatcher.run(lambda feedback: next(turns))

    # nothing applied
    assert target.read_bytes() == before
    assert dispatcher.context.changes == []
    # run parked for a human
    assert outcome.awaiting_human is True
    assert store.run_state("run-1") is RunState.WAITING_FOR_HUMAN
    # and a pending approval exists, naming the exact action
    pending = approvals.pending("run-1")
    assert len(pending) == 1
    assert pending[0].checkpoint is Checkpoint.ARCHITECTURE
    assert pending[0].detail["path"] == "orchestrator/pyproject.toml"


def test_rejected_approval_leaves_the_artifact_unchanged(wired):
    store, approvals, audit, engine = wired
    target = REPO / "orchestrator" / "pyproject.toml"
    before = target.read_bytes()

    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_task(), ALL_APPROVALS),
        run_id="run-1", state_store=store, approvals=approvals, audit=audit,
    )
    turns = iter([[("write_file", {"path": "orchestrator/pyproject.toml", "content": "x"})], []])
    dispatcher.run(lambda feedback: next(turns))

    request = approvals.pending("run-1")[0]
    approvals.decide(request.id, actor=HUMAN, decision=Decision.REJECTED,
                     rationale="we are not adding that dependency")
    assert target.read_bytes() == before
    assert approvals.is_approved(request.id) is False


def test_waiting_for_human_is_a_persisted_state_not_a_blocked_process(wired):
    store, approvals, audit, engine = wired
    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_task(), ALL_APPROVALS),
        run_id="run-1", state_store=store, approvals=approvals, audit=audit,
    )
    turns = iter([[("write_file", {"path": "orchestrator/pyproject.toml", "content": "x"})], []])
    dispatcher.run(lambda feedback: next(turns))

    # a fresh reader sees the same state — nothing lives only in the dispatcher
    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert ApprovalService(engine=engine).pending("run-1")


def test_audit_records_the_checkpoint_and_the_state_transition(wired):
    store, approvals, audit, engine = wired
    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_task(), ALL_APPROVALS),
        run_id="run-1", state_store=store, approvals=approvals, audit=audit,
    )
    turns = iter([[("write_file", {"path": "orchestrator/pyproject.toml", "content": "x"})], []])
    dispatcher.run(lambda feedback: next(turns))

    events = [e.event_type for e in audit.for_run("run-1")]
    assert "AWAITING_HUMAN_CHECKPOINT" in events
    assert "RUN_STATE_CHANGED" in events


def test_tool_violation_is_audited_and_does_not_park_the_run(wired):
    store, approvals, audit, engine = wired
    task = TaskNode(
        id="t2", description="d", requirement_ref="FR-041",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/src/agent/probe.py",),
    )
    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(task, ALL_APPROVALS),
        run_id="run-1", state_store=store, approvals=approvals, audit=audit,
    )
    turns = iter([
        [("write_file", {"path": "orchestrator/src/models/states.py", "content": "x"})],
        [("report", {"summary": "gave up", "status": "blocked"})],
    ])
    outcome = dispatcher.run(lambda feedback: next(turns))

    assert outcome.violations == 1
    assert store.run_state("run-1") is RunState.EXECUTING, "a tool mistake must not park the run"
    assert "TOOL_VIOLATION" in [e.event_type for e in audit.for_run("run-1")]
