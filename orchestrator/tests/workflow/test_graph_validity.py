"""T036 — checkpoint 2b: the plan is a DAG; cycles are rejected before execution (FR-022)."""

import pytest

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode
from src.graph.builder import build_graph, find_cycle, topological_order
from src.models.states import ExecutionMode, NodeState, Surface

pytestmark = pytest.mark.workflow


def _node(nid: str, deps: list[str] | None = None) -> TaskNode:
    return TaskNode(
        id=nid,
        description=f"task {nid}",
        requirement_ref="FR-022",
        execution_mode=ExecutionMode.AGENT_AUTHORED,
        surface=Surface.ORCHESTRATOR,
        depends_on=deps or [],
        declared_outputs=(f"orchestrator/src/{nid}.py",),
    )


def test_acyclic_plan_builds_and_orders():
    graph = build_graph([_node("a"), _node("b", ["a"]), _node("c", ["a"]), _node("d", ["b", "c"])])
    assert find_cycle(graph) is None
    order = topological_order(graph)
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_direct_cycle_is_rejected_before_execution():
    with pytest.raises(OrchestratorError) as exc:
        build_graph([_node("a", ["b"]), _node("b", ["a"])])
    assert exc.value.code is ErrorCode.CYCLE_DETECTED


def test_longer_cycle_is_rejected():
    with pytest.raises(OrchestratorError) as exc:
        build_graph([_node("a", ["c"]), _node("b", ["a"]), _node("c", ["b"])])
    assert exc.value.code is ErrorCode.CYCLE_DETECTED


def test_self_dependency_is_a_cycle():
    with pytest.raises(OrchestratorError):
        build_graph([_node("a", ["a"])])


def test_unknown_dependency_is_rejected():
    with pytest.raises(OrchestratorError) as exc:
        build_graph([_node("a", ["ghost"])])
    assert exc.value.code is ErrorCode.UNKNOWN_DEPENDENCY


def test_readiness_requires_every_predecessor_terminal():
    graph = build_graph([_node("a"), _node("b"), _node("c", ["a", "b"])])
    assert {n.id for n in graph.ready()} == {"a", "b"}
    graph.nodes["a"].state = NodeState.SUCCEEDED
    assert {n.id for n in graph.ready()} == {"b"}
    graph.nodes["b"].state = NodeState.SUCCEEDED
    assert {n.id for n in graph.ready()} == {"c"}


def test_descendants_are_the_dependency_closure():
    graph = build_graph([_node("a"), _node("b", ["a"]), _node("c", ["b"]), _node("d")])
    assert graph.descendants("a") == {"b", "c"}
    assert graph.descendants("d") == set()
