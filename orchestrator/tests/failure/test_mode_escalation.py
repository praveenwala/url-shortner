"""T047 — execution mode and declared outputs are fixed at planning time
(FR-041, FR-042, SC-019)."""

from pathlib import Path

import pytest

from src.agent.dispatch import BoundedTask, Dispatcher, assert_dispatchable
from src.agent.errors import PreconditionFailed
from src.api.errors import OrchestratorError
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface

pytestmark = pytest.mark.failure

REPO = Path(__file__).resolve().parents[3]
ALL_APPROVALS = frozenset(
    {"interface", "acceptance_criteria", "dependencies", "security_constraints"}
)


def _node(mode=ExecutionMode.AGENT_AUTHORED, outputs=("orchestrator/src/agent/probe.py",),
          sync=False):
    return TaskNode(
        id="t1", description="d", requirement_ref="FR-042", execution_mode=mode,
        surface=Surface.ORCHESTRATOR, declared_outputs=outputs, is_sync=sync,
    )


def test_human_executed_task_is_never_dispatched_to_an_agent():
    task = BoundedTask(_node(mode=ExecutionMode.HUMAN_EXECUTED, outputs=()), ALL_APPROVALS)
    with pytest.raises(PreconditionFailed):
        assert_dispatchable(task)


def test_no_model_call_is_made_when_preconditions_fail():
    """Tier A refuses before any turn happens."""
    calls = []
    task = BoundedTask(_node(mode=ExecutionMode.HUMAN_EXECUTED, outputs=()), ALL_APPROVALS)
    dispatcher = Dispatcher(repo_root=REPO, task=task)
    with pytest.raises(PreconditionFailed):
        dispatcher.run(lambda feedback: calls.append(1) or [])
    assert calls == [], "the model was consulted despite a precondition failure"


def test_mode_cannot_be_escalated_after_planning():
    node = _node(mode=ExecutionMode.HUMAN_EXECUTED, outputs=())
    with pytest.raises(OrchestratorError):
        node.execution_mode = ExecutionMode.AGENT_AUTHORED


def test_declared_outputs_cannot_be_widened_after_planning():
    node = _node()
    with pytest.raises(OrchestratorError):
        node.declared_outputs = ("orchestrator/src/agent/probe.py", "orchestrator/src/x.py")


@pytest.mark.parametrize("missing", [
    "interface", "acceptance_criteria", "dependencies", "security_constraints",
])
def test_each_missing_approval_blocks_dispatch(missing):
    approvals = ALL_APPROVALS - {missing}
    with pytest.raises(PreconditionFailed) as exc:
        assert_dispatchable(BoundedTask(_node(), frozenset(approvals)))
    assert missing in str(exc.value)


def test_sync_node_is_never_dispatched():
    with pytest.raises(PreconditionFailed):
        assert_dispatchable(BoundedTask(_node(outputs=(), sync=True), ALL_APPROVALS))
