"""T061 — approval integrity (FR-029, FR-043, FR-050).

The claim this file defends: an approval is a human act. An agent cannot make
one, cannot borrow one, and cannot stretch one to cover a second action.
"""

import pytest

from src.engine.approvals import (
    AlreadyDecided,
    ApprovalService,
    Checkpoint,
    Decision,
    NotAnApprover,
    RationaleRequired,
)
from src.engine.identity import APPROVER_ROLE, Actor, AgentCannotHoldApproverRole

pytestmark = [pytest.mark.failure, pytest.mark.integration]

HUMAN = Actor(id="human:lead", roles=frozenset({APPROVER_ROLE}))
OTHER_HUMAN = Actor(id="human:observer", roles=frozenset())
AGENT = Actor(id="agent:worker-1", roles=frozenset())


@pytest.fixture()
def service(clean_db):
    from src.engine.state import StateStore

    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    return ApprovalService(engine=clean_db)


def _request(service):
    return service.request(
        run_id="run-1", checkpoint=Checkpoint.ARCHITECTURE,
        detail={"action": "write_file", "path": "orchestrator/pyproject.toml"},
        requested_by="agent:worker-1",
    )


def test_agent_cannot_self_approve(service):
    request = _request(service)
    with pytest.raises(NotAnApprover):
        service.decide(request.id, actor=AGENT, decision=Decision.APPROVED,
                       rationale="I checked it myself")
    assert service.is_approved(request.id) is False


def test_agent_identity_can_never_hold_the_approver_role():
    """Not merely unassigned — unassignable."""
    with pytest.raises(AgentCannotHoldApproverRole):
        Actor(id="agent:worker-1", roles=frozenset({APPROVER_ROLE}))


def test_non_approver_human_is_rejected(service):
    request = _request(service)
    with pytest.raises(NotAnApprover):
        service.decide(request.id, actor=OTHER_HUMAN, decision=Decision.APPROVED,
                       rationale="looks fine to me")
    assert service.is_approved(request.id) is False


def test_approval_requires_a_rationale(service):
    request = _request(service)
    with pytest.raises(RationaleRequired):
        service.decide(request.id, actor=HUMAN, decision=Decision.APPROVED, rationale="  ")


def test_approval_records_actor_decision_rationale_timestamp_and_checkpoint(service):
    request = _request(service)
    record = service.decide(request.id, actor=HUMAN, decision=Decision.APPROVED,
                            rationale="dependency addition reviewed")
    assert record.human_actor == "human:lead"
    assert record.approver_role_held == APPROVER_ROLE
    assert record.decision is Decision.APPROVED
    assert record.rationale == "dependency addition reviewed"
    assert record.decided_at
    assert record.checkpoint is Checkpoint.ARCHITECTURE


def test_approval_permits_only_the_pending_action(service):
    request = _request(service)
    service.decide(request.id, actor=HUMAN, decision=Decision.APPROVED, rationale="ok")

    same = {"action": "write_file", "path": "orchestrator/pyproject.toml"}
    other = {"action": "write_file", "path": "orchestrator/src/agent/tools.py"}
    assert service.authorises(request.id, same) is True
    assert service.authorises(request.id, other) is False


def test_rejected_approval_authorises_nothing(service):
    request = _request(service)
    record = service.decide(request.id, actor=HUMAN, decision=Decision.REJECTED,
                            rationale="introduces a dependency we do not want")
    assert record.decision is Decision.REJECTED
    assert service.is_approved(request.id) is False
    assert service.authorises(request.id, request.detail) is False


def test_a_request_cannot_be_decided_twice(service):
    request = _request(service)
    service.decide(request.id, actor=HUMAN, decision=Decision.APPROVED, rationale="ok")
    with pytest.raises(AlreadyDecided):
        service.decide(request.id, actor=HUMAN, decision=Decision.REJECTED, rationale="changed")


def test_every_human_action_carries_actor_and_rationale(service):
    request = _request(service)
    service.decide(request.id, actor=HUMAN, decision=Decision.APPROVED, rationale="reviewed")
    for record in service.decisions_for_run("run-1"):
        assert record.human_actor and record.rationale.strip()
