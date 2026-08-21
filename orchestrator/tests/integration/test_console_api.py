"""Checkpoint 2f — the API surface the two console views need.

The console is a view. Everything it shows must come from here, every mutation
must go through here, and authorisation must hold regardless of what the client
claims about itself.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.engine.approvals import ApprovalService, Checkpoint
from src.engine.clarifications import ClarificationService
from src.engine.decompose import TaskNode
from src.engine.state import StateStore
from src.models.states import ExecutionMode, RunState, Surface

pytestmark = pytest.mark.integration

LEAD = {"X-Actor-Id": "human:lead"}
OBSERVER = {"X-Actor-Id": "human:observer"}
AGENT = {"X-Actor-Id": "agent:worker-1"}


@pytest.fixture()
def client(clean_db, monkeypatch):
    from src.api import deps

    monkeypatch.setattr(deps, "_ENGINE", clean_db)
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short-link creation and resolution", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.set_approved_scope("run-1", ["FR-001"])
    store.persist_nodes("run-1", [
        TaskNode(id="a", description="build validator", requirement_ref="FR-001",
                 execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
                 declared_outputs=("orchestrator/src/agent/a.py",)),
        TaskNode(id="b", description="build service", requirement_ref="FR-001",
                 execution_mode=ExecutionMode.HUMAN_EXECUTED, surface=Surface.ORCHESTRATOR,
                 depends_on=["a"], declared_outputs=()),
    ])
    return TestClient(app)


# --- read surfaces the RunView needs ----------------------------------------

def test_list_and_get_runs(client):
    runs = client.get("/v1/runs").json()
    assert [r["id"] for r in runs] == ["run-1"]

    detail = client.get("/v1/runs/run-1").json()
    assert detail["state"] == "PLANNING"
    assert detail["requirement"]["summary"].startswith("provide short-link")
    assert detail["metrics"]["nodes_total"] == 2


def test_get_graph_returns_nodes_edges_and_states(client):
    graph = client.get("/v1/runs/run-1/graph").json()
    assert {n["id"] for n in graph["nodes"]} == {"a", "b"}
    assert graph["edges"] == [{"from": "a", "to": "b"}]
    by_id = {n["id"]: n for n in graph["nodes"]}
    assert by_id["a"]["state"] == "PENDING"
    assert by_id["a"]["execution_mode"] == "agent_authored"
    assert by_id["b"]["depends_on"] == ["a"]


def test_audit_and_lineage_endpoints(client, clean_db):
    from src.engine.decisions import DecisionStore
    from src.store.repository import AuditRepository
    from src.trace.correlation import Correlation

    AuditRepository(clean_db).append(Correlation(run_id="run-1"), "RUN_CREATED", {"a": 1})
    DecisionStore(clean_db).record(
        run_id="run-1", alternatives=[{"option": "A"}], selection="A", rationale="cheaper",
        actor="agent:worker-1", serves_ref="FR-001",
    )
    assert [e["event_type"] for e in client.get("/v1/runs/run-1/audit").json()] == ["RUN_CREATED"]
    assert client.get("/v1/runs/run-1/decisions").json()[0]["selection"] == "A"


def test_gates_endpoint(client, clean_db):
    from sqlalchemy import text

    with clean_db.begin() as conn:
        conn.execute(text(
            "INSERT INTO gate (id, run_id, stage, kind, criteria, outcome, reason, evaluated_at)"
            " VALUES ('g1','run-1','planning','entry','spec complete','FAIL','ambiguity',now())"
        ))
    gates = client.get("/v1/runs/run-1/gates").json()
    assert gates[0]["outcome"] == "FAIL" and gates[0]["reason"] == "ambiguity"


# --- pending work the HumanActionView needs ---------------------------------

def test_pending_lists_approvals_and_clarifications(client, clean_db):
    ApprovalService(clean_db).request(
        run_id="run-1", checkpoint=Checkpoint.ARCHITECTURE,
        detail={"action": "write_file", "path": "orchestrator/pyproject.toml"},
        requested_by="agent:worker-1",
    )
    ClarificationService(clean_db).request(
        run_id="run-1", question="What does 'smarter' mean for a link?", affects="scope",
        requested_by="orchestrator",
    )
    pending = client.get("/v1/runs/run-1/pending").json()
    assert len(pending["approvals"]) == 1
    assert pending["approvals"][0]["checkpoint"] == "architecture"
    assert len(pending["clarifications"]) == 1
    assert pending["clarifications"][0]["question"].startswith("What does")


# --- approval integrity, enforced server-side -------------------------------

def _request(clean_db, detail=None):
    return ApprovalService(clean_db).request(
        run_id="run-1", checkpoint=Checkpoint.ARCHITECTURE,
        detail=detail or {"action": "write_file", "path": "orchestrator/pyproject.toml"},
        requested_by="agent:worker-1",
    )


def test_approval_requires_a_rationale(client, clean_db):
    request = _request(clean_db)
    response = client.post(f"/v1/runs/run-1/approvals/{request.id}",
                           json={"decision": "approved", "rationale": "   "}, headers=LEAD)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_non_approver_is_rejected_server_side(client, clean_db):
    """UI visibility is not authorization: the observer's own claim is irrelevant."""
    request = _request(clean_db)
    response = client.post(f"/v1/runs/run-1/approvals/{request.id}",
                           json={"decision": "approved", "rationale": "looks fine"},
                           headers=OBSERVER)
    assert response.status_code == 403
    assert ApprovalService(clean_db).is_approved(request.id) is False


def test_client_cannot_grant_itself_the_approver_role(client, clean_db):
    """Roles come from a server-side directory, never from the request."""
    request = _request(clean_db)
    response = client.post(
        f"/v1/runs/run-1/approvals/{request.id}",
        json={"decision": "approved", "rationale": "self-granted"},
        headers={**OBSERVER, "X-Actor-Roles": "approver"},
    )
    assert response.status_code == 403
    assert ApprovalService(clean_db).is_approved(request.id) is False


def test_agent_identity_is_never_accepted_as_an_approver(client, clean_db):
    request = _request(clean_db)
    response = client.post(f"/v1/runs/run-1/approvals/{request.id}",
                           json={"decision": "approved", "rationale": "self-approved"},
                           headers=AGENT)
    assert response.status_code == 403
    assert ApprovalService(clean_db).is_approved(request.id) is False


def test_approval_succeeds_for_the_approver_and_binds_to_the_request(client, clean_db):
    request = _request(clean_db)
    response = client.post(f"/v1/runs/run-1/approvals/{request.id}",
                           json={"decision": "approved", "rationale": "dependency reviewed"},
                           headers=LEAD)
    assert response.status_code == 200
    body = response.json()
    assert body["human_actor"] == "human:lead"
    assert body["request_id"] == request.id
    assert client.get("/v1/runs/run-1/pending").json()["approvals"] == []


def test_stale_already_decided_request_fails_cleanly(client, clean_db):
    request = _request(clean_db)
    client.post(f"/v1/runs/run-1/approvals/{request.id}",
                json={"decision": "approved", "rationale": "ok"}, headers=LEAD)
    again = client.post(f"/v1/runs/run-1/approvals/{request.id}",
                        json={"decision": "rejected", "rationale": "changed my mind"},
                        headers=LEAD)
    assert again.status_code == 409
    assert again.json()["error"] == "invalid_request"


def test_approval_authorises_only_its_own_fingerprint(client, clean_db):
    first = _request(clean_db, {"action": "write_file", "path": "orchestrator/pyproject.toml"})
    client.post(f"/v1/runs/run-1/approvals/{first.id}",
                json={"decision": "approved", "rationale": "ok"}, headers=LEAD)
    service = ApprovalService(clean_db)
    assert service.authorises(first.id, {"action": "write_file",
                                         "path": "orchestrator/pyproject.toml"}) is True
    assert service.authorises(first.id, {"action": "write_file",
                                         "path": "orchestrator/src/agent/tools.py"}) is False


def test_unknown_request_is_a_clean_404(client):
    response = client.post("/v1/runs/run-1/approvals/does-not-exist",
                           json={"decision": "approved", "rationale": "x"}, headers=LEAD)
    assert response.status_code == 404


# --- clarification integrity -------------------------------------------------

def test_clarification_response_is_attributed_and_persisted_before_resume(client, clean_db):
    service = ClarificationService(clean_db)
    request = service.request(run_id="run-1", question="Which scheme set?", affects="scope",
                              requested_by="orchestrator")
    StateStore(clean_db).transition_run("run-1", RunState.WAITING_FOR_HUMAN,
                                        waiting_on=request.id)

    response = client.post(f"/v1/runs/run-1/clarifications/{request.id}",
                           json={"answer": "http and https only"}, headers=LEAD)
    assert response.status_code == 200
    assert response.json()["answered_by"] == "human:lead"

    # persisted first, then the run leaves WAITING_FOR_HUMAN
    stored = service.get(request.id)
    assert stored.answer == "http and https only"
    assert stored.answered_by == "human:lead"
    assert StateStore(clean_db).run_state("run-1") is RunState.PLANNING


def test_clarification_requires_a_non_empty_answer(client, clean_db):
    request = ClarificationService(clean_db).request(
        run_id="run-1", question="Which scheme set?", affects="scope",
        requested_by="orchestrator")
    response = client.post(f"/v1/runs/run-1/clarifications/{request.id}",
                           json={"answer": "  "}, headers=LEAD)
    assert response.status_code == 400
    assert ClarificationService(clean_db).get(request.id).answer is None


def test_clarification_answer_is_recorded_in_decision_lineage(client, clean_db):
    from src.engine.decisions import DecisionStore

    request = ClarificationService(clean_db).request(
        run_id="run-1", question="Which scheme set?", affects="scope",
        requested_by="orchestrator")
    StateStore(clean_db).transition_run("run-1", RunState.WAITING_FOR_HUMAN)
    client.post(f"/v1/runs/run-1/clarifications/{request.id}",
                json={"answer": "http and https only"}, headers=LEAD)

    lineage = DecisionStore(clean_db).for_run("run-1")
    assert any(d.actor == "human:lead" and "http and https" in d.selection for d in lineage)


def test_an_unauthenticated_caller_cannot_act(client, clean_db):
    request = _request(clean_db)
    assert client.post(f"/v1/runs/run-1/approvals/{request.id}",
                       json={"decision": "approved", "rationale": "x"}).status_code == 401


# --- US6: reliability metrics on the existing run endpoint -------------------

def test_run_endpoint_carries_the_reliability_metrics(client, clean_db):
    """No new endpoint and no new screen: metrics ride on GET /v1/runs/{id}."""
    metrics = client.get("/v1/runs/run-1").json()["metrics"]
    for required in ("task_success_rate", "retries", "retry_rate", "rollbacks",
                     "rollback_rate", "mttr_seconds", "end_to_end_seconds",
                     "human_wait_seconds"):
        assert required in metrics, required


def test_metrics_distinguish_zero_activity_from_unavailable(client, clean_db):
    metrics = client.get("/v1/runs/run-1").json()["metrics"]
    assert metrics["retries"] == 0, "zero activity is a measured zero"
    assert metrics["retry_rate"] is None, "no denominator is unknown, not 0.0"
    assert metrics["mttr_seconds"] is None
    assert metrics["task_success_rate"] is None, "nothing terminal yet"


def test_metrics_reflect_recorded_activity(client, clean_db):
    from src.store.repository import AuditRepository
    from src.trace.correlation import Correlation

    audit = AuditRepository(clean_db)
    correlation = Correlation(run_id="run-1", actor="orchestrator")
    audit.append(correlation, "OPERATION_EXECUTED", {})
    audit.append(correlation.child(), "OPERATION_EXECUTED", {})
    audit.append(correlation.child(), "RETRY", {})

    metrics = client.get("/v1/runs/run-1").json()["metrics"]
    assert metrics["retries"] == 1
    assert metrics["retry_rate"] == pytest.approx(0.5)


def test_metrics_preserve_run_and_trace_correlation(client, clean_db):
    from src.store.repository import AuditRepository
    from src.trace.correlation import Correlation

    correlation = Correlation(run_id="run-1", actor="orchestrator")
    AuditRepository(clean_db).append(correlation, "OPERATION_EXECUTED", {})

    audit = client.get("/v1/runs/run-1/audit").json()
    assert audit[0]["trace_id"] == correlation.trace_id
    assert client.get("/v1/runs/run-1").json()["id"] == "run-1"
