"""run_tests fails closed when the sandbox cannot be established (R15).

These run whether or not Docker is present: the whole point is that an absent
boundary must produce a typed failure and a safe-stop, never a skip and never
host execution.
"""

from pathlib import Path

import pytest

from src.agent import sandbox, testrunner
from src.agent.dispatch import BoundedTask, Dispatcher
from src.agent.errors import SandboxUnavailable
from src.agent.testrunner import TestLayer, TestRunRequest
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface

pytestmark = pytest.mark.failure

REPO = Path(__file__).resolve().parents[3]
ALL_APPROVALS = frozenset(
    {"interface", "acceptance_criteria", "dependencies", "security_constraints"}
)


def _node():
    return TaskNode(
        id="t1", description="d", requirement_ref="R15",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/src/agent/probe.py",),
    )


def test_missing_daemon_raises_typed_error_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)
    copied: list = []
    monkeypatch.setattr(
        sandbox, "materialise_surface_copy",
        lambda *a, **k: copied.append(a) or Path("/nonexistent"),
    )
    with pytest.raises(SandboxUnavailable) as exc:
        testrunner.run_tests(
            TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT)
        )
    assert "Docker daemon is unavailable" in str(exc.value)
    assert "refuses to execute on the host" in str(exc.value)
    assert copied == [], "a surface was copied despite the boundary being unavailable"


def test_missing_image_raises_typed_error_and_names_the_provisioning_step(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: True)
    monkeypatch.setattr(sandbox, "image_present", lambda image: False)
    with pytest.raises(SandboxUnavailable) as exc:
        testrunner.run_tests(
            TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT)
        )
    assert "build-images.sh" in str(exc.value)
    assert "never builds or pulls images on demand" in str(exc.value)


def test_runtime_never_builds_or_pulls_an_image():
    """An agent must not be able to cause an image build.

    Structural rather than textual: every `docker` argv list in the runtime is
    parsed, and its subcommand checked. Grepping for the word "build" would
    match the comments that explain why building is a provisioning step.
    """
    import ast

    forbidden = {"build", "pull", "buildx", "load", "import", "commit"}
    found: list[tuple[str, str]] = []

    for module in (sandbox, testrunner):
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            first = node.elts[0]
            if not (isinstance(first, ast.Constant) and first.value == "docker"):
                continue
            if len(node.elts) < 2:
                continue
            second = node.elts[1]
            if isinstance(second, ast.Constant) and second.value in forbidden:
                found.append((module.__name__, second.value))

    assert found == [], f"runtime can invoke docker {found}"


def test_runtime_docker_subcommands_are_the_expected_minimum():
    """Positive control: the runtime uses only the subcommands the design names."""
    import ast

    allowed = {"info", "run", "kill", "rm", "exec", "network", "image"}
    seen: set[str] = set()
    for module in (sandbox, testrunner):
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts:
                first = node.elts[0]
                if isinstance(first, ast.Constant) and first.value == "docker" and len(node.elts) > 1:
                    second = node.elts[1]
                    if isinstance(second, ast.Constant):
                        seen.add(second.value)
    assert seen <= allowed, f"unexpected docker subcommands: {sorted(seen - allowed)}"
    assert seen, "no docker invocations found at all"


def test_sandbox_unavailable_safe_stops_the_task_and_records_the_reason(monkeypatch):
    """Fail closed: safe-stop path, state preserved, reason audited (FR-031)."""
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)
    audited: list[tuple[str, str]] = []

    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_node(), ALL_APPROVALS),
        on_audit=lambda event, detail: audited.append((event, detail)),
    )
    turns = iter([[("run_tests", {"layer": "unit"})], []])
    outcome = dispatcher.run(lambda feedback: next(turns))

    assert outcome.safe_stopped is True
    assert outcome.completed is False
    assert "sandbox unavailable" in outcome.reason
    assert [e for e, _ in audited] == ["SAFE_STOP_SANDBOX_UNAVAILABLE"]
    assert [e for e, _ in outcome.audit] == ["SAFE_STOP_SANDBOX_UNAVAILABLE"]
    # state preserved: no change was applied, nothing was retried
    assert dispatcher.context.changes == []
    assert outcome.violations == 0, "a missing boundary is not a tool violation to retry"
