"""US4 — selective replanning (FR-033, SC-011).

The scenario: the shortener exists and passes. A new requirement arrives —
"Improve redirect latency for hot links while preserving exact redirect analytics."

What must *not* happen: a full restart. What must happen: the affected dependency closure is
identified, only those nodes go stale, unaffected successful work is preserved, replacements
supersede rather than erase, and anything that introduces a new component stops for a human.
"""

import pytest

from src.api.errors import OrchestratorError
from src.engine.approvals import ApprovalService, Checkpoint, Decision
from src.engine.decisions import DecisionStore
from src.engine.decompose import TaskNode
from src.engine.identity import APPROVER_ROLE, Actor
from src.engine.replan import (
    Measurements,
    OptimisationOption,
    ReplanService,
    ReplanState,
)
from src.engine.state import StateStore
from src.models.states import ExecutionMode, NodeState, RunState, Surface

pytestmark = [pytest.mark.workflow, pytest.mark.integration]

HUMAN = Actor(id="human:lead", roles=frozenset({APPROVER_ROLE}))
CHANGE = "Improve redirect latency for hot links while preserving exact redirect analytics."


def _node(nid, ref, deps=None, state=NodeState.SUCCEEDED,
          mode=ExecutionMode.AGENT_AUTHORED, outputs=None):
    return TaskNode(
        id=nid, description=f"task {nid}", requirement_ref=ref, execution_mode=mode,
        surface=Surface.SHORTENER, depends_on=deps or [], state=state,
        declared_outputs=outputs or (f"shortener/src/main/java/{nid}.java",),
    )


@pytest.fixture()
def run(clean_db):
    """A completed shortener run: validation → service → redirect → analytics,
    plus an unrelated revoke branch."""
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short-link creation and resolution", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.set_approved_scope("run-1", ["FR-001", "FR-007", "FR-012", "FR-013"])
    store.persist_nodes("run-1", [
        _node("validate", "FR-001"),
        _node("service", "FR-007", deps=["validate"]),
        _node("redirect", "FR-013", deps=["service"]),
        _node("analytics", "FR-014", deps=["redirect"]),
        _node("revoke", "FR-012", deps=["service"]),
    ])
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    return ReplanService(engine=clean_db), clean_db


# --- 1. upstream change intake ----------------------------------------------

def test_change_request_is_persisted_and_linked_to_the_prior_run(run):
    service, _engine = run
    change = service.submit_change(
        run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
        reason="measured p95 regression on hot links", submitted_by="human:lead",
    )
    stored = service.change_request(change.id)
    assert stored.run_id == "run-1"
    assert stored.prior_requirement_id == "req-1"
    assert stored.reason == "measured p95 regression on hot links"
    assert stored.submitted_by == "human:lead"
    assert stored.submitted_at


# --- 2. impact analysis ------------------------------------------------------

def test_one_change_invalidates_only_its_dependency_closure(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    impact = service.analyse_impact(change.id, affected_nodes=["redirect"])

    assert set(impact.affected) == {"redirect"}
    assert set(impact.stale) == {"redirect", "analytics"}
    assert set(impact.preserved) == {"validate", "service", "revoke"}


def test_unaffected_successful_nodes_remain_succeeded(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)

    graph = StateStore(engine).load_graph("run-1")
    for preserved in ("validate", "service", "revoke"):
        assert graph.nodes[preserved].state is NodeState.SUCCEEDED
        assert graph.nodes[preserved].is_stale is False


def test_affected_completed_nodes_become_stale_but_keep_their_state(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)

    graph = StateStore(engine).load_graph("run-1")
    for stale in ("redirect", "analytics"):
        assert graph.nodes[stale].is_stale is True
        assert graph.nodes[stale].state is NodeState.SUCCEEDED, (
            "staleness is a flag; the prior result must remain queryable")


def test_the_whole_dag_is_not_rebuilt(run):
    service, engine = run
    before = {n.id for n in StateStore(engine).load_graph("run-1").nodes.values()}
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)

    after = {n.id for n in StateStore(engine).load_graph("run-1").nodes.values()}
    assert before <= after, "no original node may disappear"


# --- 3. selective replanning -------------------------------------------------

def test_replacements_are_created_only_for_stale_work(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    outcome = service.replan(change.id, measurements=Measurements())

    assert outcome.state is ReplanState.REPLANNED
    replacements = service.replacements("run-1")
    assert {r.supersedes for r in replacements} == {"redirect", "analytics"}
    assert all(r.state is NodeState.PENDING for r in replacements)


def test_replacement_links_to_what_it_supersedes_and_prior_results_stay_queryable(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements())

    replacement = next(r for r in service.replacements("run-1") if r.supersedes == "redirect")
    original = StateStore(engine).load_graph("run-1").nodes["redirect"]
    assert original.state is NodeState.SUCCEEDED
    assert replacement.id != "redirect"
    assert replacement.declared_outputs, "outputs stay explicit on a replacement"


def test_execution_mode_is_recalculated_but_never_silently_escalated(run):
    service, engine = run
    StateStore(engine).persist_nodes("run-1", [
        _node("human-step", "FR-013", deps=["redirect"],
              mode=ExecutionMode.HUMAN_EXECUTED, outputs=()),
    ])
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements())

    replacement = next(r for r in service.replacements("run-1") if r.supersedes == "human-step")
    assert replacement.execution_mode is ExecutionMode.HUMAN_EXECUTED


def test_a_replan_that_would_introduce_a_cycle_is_rejected(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)

    with pytest.raises(OrchestratorError):
        service.replan(change.id, measurements=Measurements(),
                       extra_dependencies=[("analytics", "validate"), ("validate", "analytics")])


def test_repeated_replanning_does_not_duplicate_unaffected_work(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements())
    first = {r.id for r in service.replacements("run-1")}

    service.replan(change.id, measurements=Measurements())
    second = {r.id for r in service.replacements("run-1")}

    assert first == second, "a second replan must not clone the same replacements"
    graph = StateStore(engine).load_graph("run-1")
    assert graph.nodes["validate"].state is NodeState.SUCCEEDED
    assert graph.nodes["validate"].is_stale is False


# --- 4/5. architecture checkpoint and the decision ladder --------------------

def test_default_choice_is_the_cheapest_rung_not_redis(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    outcome = service.replan(change.id, measurements=Measurements())

    assert outcome.proposal.option is OptimisationOption.VERIFY_QUERY_PATH
    assert outcome.proposal.requires_architecture_approval is False


def test_counter_contention_selects_a_bounded_change_not_a_new_component(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    outcome = service.replan(change.id, measurements=Measurements(
        p95_ms=400, exceeds_budget=True, attributed_to="counter_contention",
        query_path_verified=True, pooling_verified=True,
    ))

    assert outcome.proposal.option is OptimisationOption.BATCH_COUNTER
    assert outcome.proposal.requires_architecture_approval is False
    assert any("Redis" in alternative["option"] for alternative in outcome.proposal.alternatives)


def test_redis_is_only_reachable_when_every_cheaper_rung_is_exhausted(run):
    service, _engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    outcome = service.replan(change.id, measurements=Measurements(
        p95_ms=900, exceeds_budget=True, attributed_to="datastore_access",
        query_path_verified=True, pooling_verified=True, batching_attempted=True,
        cache_design_preserves_exactness=True,
    ))

    assert outcome.proposal.option is OptimisationOption.CACHE_TIER
    assert outcome.proposal.requires_architecture_approval is True
    assert outcome.state is ReplanState.AWAITING_ARCHITECTURE_APPROVAL


def test_a_new_component_halts_for_approval_and_implements_nothing(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements(
        p95_ms=900, exceeds_budget=True, attributed_to="datastore_access",
        query_path_verified=True, pooling_verified=True, batching_attempted=True,
        cache_design_preserves_exactness=True,
    ))

    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    pending = ApprovalService(engine).pending("run-1")
    assert pending and pending[0].checkpoint is Checkpoint.ARCHITECTURE
    assert service.replacements("run-1") == [], "no work may be planned before approval"
    assert "postgres" in str(pending[0].detail).lower(), (
        "the cheaper alternative must be preserved in the request")


def test_rejected_architecture_approval_keeps_the_prior_architecture(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements(
        p95_ms=900, exceeds_budget=True, attributed_to="datastore_access",
        query_path_verified=True, pooling_verified=True, batching_attempted=True,
        cache_design_preserves_exactness=True,
    ))
    request = ApprovalService(engine).pending("run-1")[0]
    ApprovalService(engine).decide(request.id, actor=HUMAN, decision=Decision.REJECTED,
                                   rationale="no new datastore for this deliverable")

    outcome = service.resume_after_approval(change.id, request.id)
    assert outcome.state is ReplanState.REPLANNED
    assert outcome.proposal.option is not OptimisationOption.CACHE_TIER
    assert outcome.proposal.requires_architecture_approval is False
    assert service.replacements("run-1"), "the fallback path must still be planned"


def test_approved_architecture_change_resumes_only_the_affected_path(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements(
        p95_ms=900, exceeds_budget=True, attributed_to="datastore_access",
        query_path_verified=True, pooling_verified=True, batching_attempted=True,
        cache_design_preserves_exactness=True,
    ))
    request = ApprovalService(engine).pending("run-1")[0]
    ApprovalService(engine).decide(request.id, actor=HUMAN, decision=Decision.APPROVED,
                                   rationale="measurements justify a cache tier")

    outcome = service.resume_after_approval(change.id, request.id)
    assert outcome.state is ReplanState.REPLANNED
    assert {r.supersedes for r in service.replacements("run-1")} == {"redirect", "analytics"}
    graph = StateStore(engine).load_graph("run-1")
    assert graph.nodes["validate"].state is NodeState.SUCCEEDED
    assert graph.nodes["revoke"].is_stale is False


# --- 6. lineage and 7. restart ------------------------------------------------

def test_lineage_records_the_whole_replan_decision(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements(
        p95_ms=400, exceeds_budget=True, attributed_to="counter_contention",
        query_path_verified=True, pooling_verified=True,
    ))

    events = service.replan_events("run-1")
    assert len(events) == 1
    assert set(events[0]["blast_radius"]) == {"redirect", "analytics"}
    assert set(events[0]["nodes_marked_stale"]) == {"redirect", "analytics"}
    assert events[0]["trigger"]

    decision = DecisionStore(engine).for_run("run-1")[-1]
    assert decision.selection
    assert decision.rationale
    assert decision.actor
    assert decision.serves_ref
    assert any("Redis" in a["option"] for a in decision.alternatives)


def test_restart_preserves_stale_and_replacement_lineage(run):
    service, engine = run
    change = service.submit_change(run_id="run-1", prior_requirement_id="req-1", text=CHANGE,
                                   reason="latency", submitted_by="human:lead")
    service.analyse_impact(change.id, affected_nodes=["redirect"], apply=True)
    service.replan(change.id, measurements=Measurements())
    before = {(r.id, r.supersedes) for r in service.replacements("run-1")}

    del service
    fresh = ReplanService(engine=engine)

    assert {(r.id, r.supersedes) for r in fresh.replacements("run-1")} == before
    graph = StateStore(engine).load_graph("run-1")
    assert graph.nodes["analytics"].is_stale is True
    assert graph.nodes["validate"].is_stale is False
