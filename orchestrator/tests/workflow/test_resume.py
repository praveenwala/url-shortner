"""T042 — checkpoint 2c: an interrupted run resumes with no completed task
re-executed and no lost transition (FR-025, NFR-003, SC-012).

The interruption is simulated the honest way: the pre-interruption state is
written through the same persistence path the scheduler uses, the in-memory
graph is then discarded entirely, and the resumed run is rebuilt only from what
PostgreSQL holds. Nothing carries over in process memory.
"""

import pytest

from src.engine.decompose import TaskNode
from src.engine.scheduler import Scheduler
from src.engine.state import StateStore
from src.models.states import ExecutionMode, NodeState, RunState, Surface

pytestmark = [pytest.mark.workflow, pytest.mark.integration]


def _node(nid, deps=None):
    return TaskNode(
        id=nid, description=f"task {nid}", requirement_ref="FR-025",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        depends_on=deps or [],
    )


@pytest.fixture()
def seeded(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.persist_nodes("run-1", [_node("a"), _node("b", ["a"]), _node("c", ["b"])])
    return store


def test_every_transition_is_persisted(seeded):
    store = seeded
    graph = store.load_graph("run-1")
    executed = []

    scheduler = Scheduler(
        graph,
        lambda n: (executed.append(n.id), True)[1],
        on_transition=lambda node, old, new: store.record_node_transition(node),
    )
    scheduler.run()

    reloaded = store.load_graph("run-1")
    assert [reloaded.nodes[n].state for n in ("a", "b", "c")] == [NodeState.SUCCEEDED] * 3
    assert executed == ["a", "b", "c"]


def test_resume_does_not_re_execute_completed_work(seeded):
    """SC-012: zero completed tasks re-executed, zero lost transitions."""
    store = seeded

    # --- before the interruption: 'a' ran to completion, persisted each step ---
    graph = store.load_graph("run-1")
    node_a = graph.nodes["a"]
    for target in (NodeState.READY, NodeState.RUNNING, NodeState.SUCCEEDED):
        node_a.state = target
        node_a.attempt_count = 1 if target is NodeState.RUNNING else node_a.attempt_count
        store.record_node_transition(node_a)

    assert store.completed_node_ids("run-1") == {"a"}

    # --- the process dies here; nothing in memory survives ---
    del graph, node_a

    # --- resume: rebuild only from persisted state ---
    resumed = store.load_graph("run-1")
    assert resumed.nodes["a"].state is NodeState.SUCCEEDED
    assert resumed.nodes["a"].attempt_count == 1

    executed = []
    Scheduler(
        resumed,
        lambda n: (executed.append(n.id), True)[1],
        on_transition=lambda node, old, new: store.record_node_transition(node),
    ).run()

    assert "a" not in executed, "a completed before the interruption and must not re-run"
    assert executed == ["b", "c"]

    final = store.load_graph("run-1")
    assert all(final.nodes[n].state is NodeState.SUCCEEDED for n in ("a", "b", "c"))
    assert final.nodes["a"].attempt_count == 1


def test_run_state_transitions_are_validated_and_persisted(seeded):
    store = seeded
    assert store.run_state("run-1") is RunState.PLANNING
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    assert store.run_state("run-1") is RunState.EXECUTING

    from src.models.states import InvalidTransition

    store.transition_run("run-1", RunState.COMPLETED)
    with pytest.raises(InvalidTransition):
        store.transition_run("run-1", RunState.EXECUTING)  # terminal is terminal


def test_graph_reloaded_from_store_preserves_dependencies(seeded):
    graph = seeded.load_graph("run-1")
    assert graph.predecessors("b") == ["a"]
    assert graph.predecessors("c") == ["b"]
    assert graph.descendants("a") == {"b", "c"}
