"""T062 — scope boundary (FR-039) and governance protection (FR-040).

Both share one shape: the work is not refused outright, it is *halted and
surfaced*. Silently absorbing out-of-scope work into the current run is the
failure mode these guard against.
"""

import pytest

from src.engine.approvals import ApprovalService, Checkpoint, Decision
from src.engine.guardrails import (
    GovernanceViolation,
    Guardrails,
    ScopeViolation,
    classify_governance_path,
)
from src.engine.identity import APPROVER_ROLE, Actor
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface

pytestmark = [pytest.mark.failure, pytest.mark.integration]

HUMAN = Actor(id="human:lead", roles=frozenset({APPROVER_ROLE}))


@pytest.fixture()
def guards(clean_db):
    from src.engine.state import StateStore

    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.set_approved_scope("run-1", ["FR-001", "FR-004"])
    return Guardrails(engine=clean_db, approvals=ApprovalService(engine=clean_db))


def _task(ref: str) -> TaskNode:
    return TaskNode(
        id="t1", description="d", requirement_ref=ref,
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/src/agent/probe.py",),
    )


# --- FR-039 scope boundary --------------------------------------------------

def test_task_inside_the_approved_scope_proceeds(guards):
    guards.assert_task_in_scope("run-1", _task("FR-001"))


def test_out_of_scope_task_halts_and_surfaces_for_a_human(guards):
    with pytest.raises(ScopeViolation) as exc:
        guards.assert_task_in_scope("run-1", _task("FR-999"))
    assert "FR-999" in str(exc.value)

    pending = guards.approvals.pending("run-1")
    assert len(pending) == 1
    assert pending[0].checkpoint is Checkpoint.SCOPE
    assert pending[0].detail["requirement_ref"] == "FR-999"


def test_out_of_scope_work_is_not_silently_absorbed(guards):
    """The run must not simply widen its own scope."""
    with pytest.raises(ScopeViolation):
        guards.assert_task_in_scope("run-1", _task("FR-999"))
    assert guards.approved_scope("run-1") == ("FR-001", "FR-004")


def test_scope_can_be_widened_only_by_an_approved_decision(guards):
    with pytest.raises(ScopeViolation):
        guards.assert_task_in_scope("run-1", _task("FR-999"))
    request = guards.approvals.pending("run-1")[0]
    guards.approvals.decide(request.id, actor=HUMAN, decision=Decision.APPROVED,
                            rationale="in scope after all")
    guards.widen_scope_from_approval("run-1", request.id)
    guards.assert_task_in_scope("run-1", _task("FR-999"))
    assert "FR-999" in guards.approved_scope("run-1")


def test_rejected_scope_request_does_not_widen_scope(guards):
    with pytest.raises(ScopeViolation):
        guards.assert_task_in_scope("run-1", _task("FR-999"))
    request = guards.approvals.pending("run-1")[0]
    guards.approvals.decide(request.id, actor=HUMAN, decision=Decision.REJECTED,
                            rationale="out of scope for this run")
    with pytest.raises(Exception):
        guards.widen_scope_from_approval("run-1", request.id)
    assert "FR-999" not in guards.approved_scope("run-1")


# --- FR-040 governance protection -------------------------------------------

@pytest.mark.parametrize("path,expected", [
    (".specify/memory/constitution.md", Checkpoint.GOVERNANCE),
    ("specs/001-agentic-url-shortener/plan.md", Checkpoint.GOVERNANCE),
    ("specs/001-agentic-url-shortener/tasks.md", Checkpoint.GOVERNANCE),
    ("ops/db/provision.sh", Checkpoint.GOVERNANCE),
    (".github/workflows/ci.yml", Checkpoint.GOVERNANCE),
    ("orchestrator/src/agent/tools.py", None),
])
def test_governance_paths_are_classified(path, expected):
    assert classify_governance_path(path) is expected


def test_governance_modification_halts_and_surfaces(guards):
    with pytest.raises(GovernanceViolation):
        guards.assert_governance_write_allowed(
            "run-1", ".specify/memory/constitution.md", requested_by="agent:worker-1"
        )
    pending = guards.approvals.pending("run-1")
    assert pending and pending[0].checkpoint is Checkpoint.GOVERNANCE


def test_governance_write_permitted_only_after_explicit_approval(guards):
    path = "specs/001-agentic-url-shortener/plan.md"
    with pytest.raises(GovernanceViolation):
        guards.assert_governance_write_allowed("run-1", path, requested_by="agent:worker-1")
    request = guards.approvals.pending("run-1")[0]
    guards.approvals.decide(request.id, actor=HUMAN, decision=Decision.APPROVED,
                            rationale="plan amendment agreed")
    guards.assert_governance_write_allowed("run-1", path, requested_by="agent:worker-1")


def test_an_approval_for_one_governance_file_does_not_cover_another(guards):
    with pytest.raises(GovernanceViolation):
        guards.assert_governance_write_allowed(
            "run-1", "specs/001-agentic-url-shortener/plan.md", requested_by="agent:worker-1"
        )
    request = guards.approvals.pending("run-1")[0]
    guards.approvals.decide(request.id, actor=HUMAN, decision=Decision.APPROVED,
                            rationale="plan only")
    with pytest.raises(GovernanceViolation):
        guards.assert_governance_write_allowed(
            "run-1", ".specify/memory/constitution.md", requested_by="agent:worker-1"
        )
