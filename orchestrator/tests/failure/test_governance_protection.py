"""T046/T055 — governance artifacts cannot be modified by an agent (FR-040)."""

from pathlib import Path

import pytest

from src.agent.allowlist import PathPolicy
from src.agent.errors import ToolViolation
from src.agent.tools import ToolContext, handle_write_file
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface

pytestmark = pytest.mark.failure

REPO = Path(__file__).resolve().parents[3]

GOVERNANCE_FILES = [
    ".specify/memory/constitution.md",
    "specs/001-agentic-url-shortener/plan.md",
    "specs/001-agentic-url-shortener/tasks.md",
    "specs/001-agentic-url-shortener/spec.md",
    "ops/db/provision.sh",
    "ops/db/01-provision-cluster.sql",
    ".github/workflows/ci.yml",
]


def _ctx(outputs):
    node = TaskNode(
        id="t1", description="d", requirement_ref="FR-040",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=outputs,
    )
    return ToolContext(repo_root=REPO, task=node)


@pytest.mark.parametrize("path", GOVERNANCE_FILES)
def test_governance_files_cannot_be_read(path):
    policy = PathPolicy(repo_root=REPO, task=_ctx(("orchestrator/src/agent/probe.py",)).task)
    with pytest.raises(ToolViolation):
        policy.resolve_read(path)


@pytest.mark.parametrize("path", GOVERNANCE_FILES)
def test_governance_files_cannot_be_written_and_remain_unchanged(path):
    target = REPO / path
    before = target.read_bytes() if target.exists() else None
    ctx = _ctx(("orchestrator/src/agent/probe.py",))
    with pytest.raises(ToolViolation):
        handle_write_file(ctx, path, "tampered")
    if before is not None:
        assert target.read_bytes() == before
    assert ctx.changes == []


def test_declaring_a_governance_file_as_an_output_is_impossible():
    """It cannot even be declared: outputs must be inside the task's surface."""
    from src.api.errors import OrchestratorError

    with pytest.raises(OrchestratorError):
        TaskNode(
            id="t1", description="d", requirement_ref="FR-040",
            execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
            declared_outputs=(".specify/memory/constitution.md",),
        )
