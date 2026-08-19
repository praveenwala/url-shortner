"""T040 — checkpoint 2c: independent tasks run concurrently; a sync node waits
for every inbound branch (FR-023, FR-024, SC-008)."""

import threading
import time

import pytest

from src.engine.decompose import TaskNode
from src.engine.scheduler import Scheduler
from src.graph.builder import build_graph
from src.graph.sync import SyncPolicy
from src.models.states import ExecutionMode, NodeState, Surface

pytestmark = pytest.mark.workflow


def _node(nid, deps=None, sync=False):
    return TaskNode(
        id=nid, description=f"task {nid}", requirement_ref="FR-023",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        depends_on=deps or [], is_sync=sync,
    )


def test_independent_tasks_execute_concurrently():
    """SC-008: two independent tasks demonstrably overlap in time."""
    barrier = threading.Barrier(2, timeout=5)

    def executor(node):
        barrier.wait()  # deadlocks unless both run at once
        return True

    graph = build_graph([_node("a"), _node("b")])
    trace = Scheduler(graph, executor, max_workers=4).run()
    assert trace.max_concurrent == 2
    assert graph.nodes["a"].state is NodeState.SUCCEEDED
    assert graph.nodes["b"].state is NodeState.SUCCEEDED


def test_dependent_task_never_starts_before_predecessor_finishes():
    order = []
    lock = threading.Lock()

    def executor(node):
        with lock:
            order.append(("start", node.id))
        time.sleep(0.01)
        with lock:
            order.append(("end", node.id))
        return True

    graph = build_graph([_node("a"), _node("b", ["a"])])
    Scheduler(graph, executor, max_workers=4).run()
    assert order.index(("end", "a")) < order.index(("start", "b"))


def test_sync_node_waits_for_every_inbound_branch():
    """FR-024: downstream is not released until all inbound branches are terminal."""
    graph = build_graph([_node("a"), _node("b"), _node("join", ["a", "b"], sync=True),
                         _node("after", ["join"])])
    trace = Scheduler(graph, lambda n: True, max_workers=4).run()

    result = trace.sync_results["join"]
    assert {b.node_id for b in result.branches} == {"a", "b"}
    assert result.all_succeeded
    assert graph.nodes["join"].state is NodeState.SUCCEEDED
    assert graph.nodes["after"].state is NodeState.SUCCEEDED
    assert trace.finished.index("a") < trace.started.index("after")
    assert trace.finished.index("b") < trace.started.index("after")


def test_sync_node_records_each_branch_outcome_when_one_fails():
    """The edge case: a branch fails while its sibling succeeds. It must be recorded
    and resolved, never hang."""
    def executor(node):
        return node.id != "b"

    graph = build_graph([_node("a"), _node("b"), _node("join", ["a", "b"], sync=True),
                         _node("after", ["join"])])
    trace = Scheduler(graph, executor, max_workers=4).run()

    result = trace.sync_results["join"]
    outcomes = {b.node_id: b.state for b in result.branches}
    assert outcomes["a"] is NodeState.SUCCEEDED
    assert outcomes["b"] is NodeState.FAILED
    assert not result.released
    assert graph.nodes["join"].state is NodeState.SKIPPED
    assert graph.nodes["after"].state is NodeState.SKIPPED   # resolved, not hung
    assert graph.all_terminal()


def test_any_may_fail_policy_releases_downstream():
    def executor(node):
        return node.id != "b"

    graph = build_graph([_node("a"), _node("b"), _node("join", ["a", "b"], sync=True)])
    trace = Scheduler(graph, executor, max_workers=4,
                      sync_policy=SyncPolicy.ANY_MAY_FAIL).run()
    assert trace.sync_results["join"].released
    assert graph.nodes["join"].state is NodeState.SUCCEEDED


def test_every_transition_is_traced():
    """FR-025/FR-036 precondition: transitions are observable, not implicit."""
    graph = build_graph([_node("a"), _node("b", ["a"])])
    trace = Scheduler(graph, lambda n: True).run()
    a_states = [(f, t) for nid, f, t in trace.transitions if nid == "a"]
    assert a_states == [
        (NodeState.PENDING, NodeState.READY),
        (NodeState.READY, NodeState.RUNNING),
        (NodeState.RUNNING, NodeState.SUCCEEDED),
    ]
