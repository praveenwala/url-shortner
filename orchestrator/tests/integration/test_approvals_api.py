"""API support for approvals and lineage (checkpoint 2e)."""

import pytest

from src.api.approvals_api import ApprovalsApi
from src.engine.approvals import ApprovalService, Checkpoint
from src.engine.identity import APPROVER_ROLE
from src.engine.state import StateStore

pytestmark = pytest.mark.integration


@pytest.fixture()
def api(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    ApprovalService(clean_db).request(
        run_id="run-1", checkpoint=Checkpoint.ARCHITECTURE,
        detail={"action": "write_file", "path": "orchestrator/pyproject.toml"},
        requested_by="agent:worker-1",
    )
    return ApprovalsApi(engine=clean_db)


def test_pending_lists_what_needs_a_human(api):
    pending = api.pending("run-1")
    assert len(pending) == 1
    assert pending[0]["checkpoint"] == "architecture"
    assert pending[0]["detail"]["path"] == "orchestrator/pyproject.toml"


def test_decide_records_actor_role_and_rationale(api):
    request_id = api.pending("run-1")[0]["id"]
    result = api.decide(request_id, actor_id="human:lead", roles=[APPROVER_ROLE],
                        decision="approved", rationale="reviewed the dependency")
    assert result["human_actor"] == "human:lead"
    assert result["approver_role_held"] == APPROVER_ROLE
    assert result["rationale"] == "reviewed the dependency"
    assert api.pending("run-1") == []


def test_api_cannot_be_used_to_approve_as_an_agent(api):
    """Even claiming the role does not help: Actor refuses to construct."""
    from src.engine.identity import AgentCannotHoldApproverRole

    request_id = api.pending("run-1")[0]["id"]
    with pytest.raises(AgentCannotHoldApproverRole):
        api.decide(request_id, actor_id="agent:worker-1", roles=[APPROVER_ROLE],
                   decision="approved", rationale="self-approved")


def test_decisions_endpoint_merges_approvals_and_lineage(api, clean_db):
    from src.engine.decisions import DecisionStore

    request_id = api.pending("run-1")[0]["id"]
    api.decide(request_id, actor_id="human:lead", roles=[APPROVER_ROLE],
               decision="approved", rationale="ok")
    DecisionStore(clean_db).record(
        run_id="run-1", alternatives=[{"option": "A"}, {"option": "B"}], selection="A",
        rationale="cheaper", actor="agent:worker-1", serves_ref="FR-004",
    )
    kinds = {item["kind"] for item in api.decisions("run-1")}
    assert kinds == {"approval", "decision"}


def test_audit_endpoint_exposes_the_trail(api, clean_db):
    from src.store.repository import AuditRepository
    from src.trace.correlation import Correlation

    AuditRepository(clean_db).append(Correlation(run_id="run-1"), "RUN_CREATED", {"a": 1})
    events = api.audit("run-1")
    assert [e["event_type"] for e in events] == ["RUN_CREATED"]
    assert events[0]["trace_id"]
