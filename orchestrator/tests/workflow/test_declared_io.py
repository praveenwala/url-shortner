"""T038 correction — decomposition declares inputs and outputs, and they are
fixed before dispatch (FR-021, FR-041, FR-042).

The write allow-list the bounded agent runtime will derive comes from
`declared_outputs`. These tests exist so that allow-list can be trusted: an
output set an agent could widen mid-run would not be an approved interface.
"""

import pytest

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode, decompose, replan_outputs
from src.engine.intake import Interpretation, Requirement, record_interpretation
from src.models.states import ExecutionMode, NodeState, Surface

pytestmark = pytest.mark.workflow


def _interpreted() -> Requirement:
    req = Requirement(id="r1", submitted_text="provide short links", submitted_by="human:lead")
    record_interpretation(
        req, Interpretation(scope="short links", actors=["creator"], constraints=[])
    )
    return req


def _node(nid="a", *, mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
          outputs=("orchestrator/src/a.py",), inputs=(), sync=False) -> TaskNode:
    return TaskNode(
        id=nid, description=f"task {nid}", requirement_ref="FR-021",
        execution_mode=mode, surface=surface,
        declared_inputs=inputs, declared_outputs=outputs, is_sync=sync,
    )


# --- decomposition produces declared outputs --------------------------------

def test_decomposition_yields_tasks_with_declared_outputs():
    nodes = decompose(_interpreted(), [
        _node("a", outputs=("orchestrator/src/graph/builder.py",)),
        _node("b", outputs=("orchestrator/src/engine/gates.py",),
              inputs=("orchestrator/src/models/states.py",)),
    ])
    assert all(n.declared_outputs for n in nodes)
    assert nodes[1].declared_inputs == ("orchestrator/src/models/states.py",)


def test_agent_authored_task_without_outputs_is_refused_at_construction():
    with pytest.raises(OrchestratorError) as exc:
        _node("a", outputs=())
    assert exc.value.code is ErrorCode.MISSING_REQUIREMENT_REF


def test_decompose_refuses_an_agent_task_smuggled_in_without_outputs():
    """The planner's boundary re-states the rule, catching a node built elsewhere."""
    node = _node("a", mode=ExecutionMode.HUMAN_EXECUTED, outputs=())
    object.__setattr__(node, "execution_mode", ExecutionMode.AGENT_AUTHORED)
    with pytest.raises(OrchestratorError):
        decompose(_interpreted(), [node])


def test_human_executed_task_may_declare_no_outputs():
    assert _node("h", mode=ExecutionMode.HUMAN_EXECUTED, outputs=()).declared_outputs == ()


def test_sync_node_must_not_declare_outputs():
    assert _node("j", sync=True, outputs=()).declared_outputs == ()
    with pytest.raises(OrchestratorError):
        _node("j", sync=True, outputs=("orchestrator/src/x.py",))


# --- outputs must be explicit artifact paths --------------------------------

@pytest.mark.parametrize("bad", [
    "/etc/passwd",                          # absolute
    "orchestrator/../ops/db/provision.sql", # traversal
    "orchestrator/src/*.py",                # pattern
    "orchestrator/src/",                    # directory
    " orchestrator/src/a.py",               # whitespace
    "orchestrator\\src\\a.py",              # backslashes
    "",                                     # empty
])
def test_output_paths_must_be_explicit_and_safe(bad):
    with pytest.raises(OrchestratorError):
        _node("a", outputs=(bad,))


def test_output_must_be_inside_the_tasks_own_surface():
    with pytest.raises(OrchestratorError) as exc:
        _node("a", surface=Surface.ORCHESTRATOR, outputs=("shortener/src/main/java/X.java",))
    assert "surface root" in str(exc.value)
    # the same path is fine for a task on that surface
    assert _node("a", surface=Surface.SHORTENER,
                 outputs=("shortener/src/main/java/X.java",)).declared_outputs


def test_duplicate_outputs_are_refused():
    with pytest.raises(OrchestratorError):
        _node("a", outputs=("orchestrator/src/a.py", "orchestrator/src/a.py"))


# --- immutability during execution ------------------------------------------

def test_outputs_cannot_be_widened_during_execution():
    node = _node("a")
    with pytest.raises(OrchestratorError) as exc:
        node.declared_outputs = ("orchestrator/src/a.py", "orchestrator/src/b.py")
    assert exc.value.code is ErrorCode.MODE_ESCALATION
    assert node.declared_outputs == ("orchestrator/src/a.py",)


def test_declared_sets_are_tuples_and_cannot_be_appended_to():
    node = _node("a")
    assert isinstance(node.declared_outputs, tuple)
    with pytest.raises(AttributeError):
        node.declared_outputs.append("orchestrator/src/b.py")


@pytest.mark.parametrize("attr,value", [
    ("execution_mode", ExecutionMode.AGENT_AUTHORED),
    ("surface", Surface.CONSOLE),
    ("requirement_ref", "FR-999"),
    ("declared_inputs", ("orchestrator/src/z.py",)),
    ("is_sync", True),
])
def test_planning_time_fields_are_frozen(attr, value):
    node = _node("a", mode=ExecutionMode.HUMAN_EXECUTED, outputs=())
    with pytest.raises(OrchestratorError):
        setattr(node, attr, value)


def test_execution_fields_remain_mutable():
    """Freezing must not break the scheduler: state and counters still change."""
    node = _node("a")
    node.state = NodeState.READY
    node.attempt_count += 1
    node.is_stale = True
    assert (node.state, node.attempt_count, node.is_stale) == (NodeState.READY, 1, True)


def test_outputs_survive_a_full_scheduler_run_unchanged():
    from src.engine.scheduler import Scheduler
    from src.graph.builder import build_graph

    graph = build_graph([_node("a"), _node("b", outputs=("orchestrator/src/b.py",))])
    before = {n.id: n.declared_outputs for n in graph.nodes.values()}
    Scheduler(graph, lambda n: True).run()
    assert {n.id: n.declared_outputs for n in graph.nodes.values()} == before


# --- changing outputs requires replanning -----------------------------------

def test_replanning_replaces_the_node_rather_than_widening_it():
    original = _node("a")
    replanned = replan_outputs(original, ("orchestrator/src/a.py", "orchestrator/src/b.py"))

    assert replanned is not original
    assert original.declared_outputs == ("orchestrator/src/a.py",)
    assert replanned.declared_outputs == ("orchestrator/src/a.py", "orchestrator/src/b.py")
    assert replanned.state is NodeState.PENDING
    assert replanned.write_allowlist == replanned.declared_outputs


def test_replanning_still_validates_the_new_outputs():
    with pytest.raises(OrchestratorError):
        replan_outputs(_node("a"), ("../ops/db/provision.sql",))


# --- the allow-list the runtime will consume --------------------------------

def test_write_allowlist_is_outputs_only_never_inputs_or_surface():
    node = _node("a", outputs=("orchestrator/src/a.py",),
                 inputs=("orchestrator/src/models/states.py",))
    assert node.write_allowlist == ("orchestrator/src/a.py",)
    assert "orchestrator/src/models/states.py" not in node.write_allowlist
