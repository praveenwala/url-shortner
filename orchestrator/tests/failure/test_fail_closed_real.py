"""T099 — fail-closed proven against a real Docker client, not a monkeypatch.

`test_sandbox_unavailable.py` substitutes `docker_available`, which proves the
*branch* is wired. It cannot prove that a genuinely unreachable daemon produces
that branch rather than a hang, a stack trace, or a silent fallback. Here the
daemon is made really unreachable by pointing DOCKER_HOST at a socket that does
not exist, and the image is made really absent by naming one that was never
built.
"""

from __future__ import annotations

import subprocess
import sys
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
ORCHESTRATOR = REPO / "orchestrator"
UNREACHABLE_DAEMON = "unix:///nonexistent/claude-t099/docker.sock"
ABSENT_IMAGE = "agent-sandbox/never-built-t099:latest"
ALL_APPROVALS = frozenset(
    {"interface", "acceptance_criteria", "dependencies", "security_constraints"}
)


def _node() -> TaskNode:
    return TaskNode(
        id="t-failclosed", description="d", requirement_ref="R15",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/src/agent/probe.py",),
    )


@pytest.fixture
def unreachable_daemon(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", UNREACHABLE_DAEMON)
    assert sandbox.docker_available() is False, (
        "DOCKER_HOST did not actually disable the daemon; the rest of this file "
        "would be testing nothing"
    )
    return UNREACHABLE_DAEMON


# --- a genuinely unreachable daemon -----------------------------------------

def test_real_unreachable_daemon_raises_sandbox_unavailable(unreachable_daemon):
    with pytest.raises(SandboxUnavailable) as exc:
        testrunner.run_tests(
            TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT)
        )
    assert "refuses to execute on the host" in str(exc.value)


def test_real_unreachable_daemon_does_not_fall_back_to_host_execution(unreachable_daemon):
    """The failure must arrive without pytest ever having been started here."""
    started: list = []
    real_run = subprocess.run

    def watch(cmd, *args, **kwargs):
        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        if argv and argv[0] != "docker":
            started.append(list(argv))
        return real_run(cmd, *args, **kwargs)

    subprocess.run = watch  # type: ignore[assignment]
    try:
        with pytest.raises(SandboxUnavailable):
            testrunner.run_tests(
                TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR,
                               layer=TestLayer.UNIT)
            )
    finally:
        subprocess.run = real_run  # type: ignore[assignment]

    assert started == [], f"a non-docker process was executed on the host: {started}"


def test_real_absent_image_raises_sandbox_unavailable():
    """The daemon is up; the image simply was never provisioned."""
    if not sandbox.docker_available():
        pytest.skip("Docker daemon unavailable")
    assert sandbox.image_present(ABSENT_IMAGE) is False
    with pytest.raises(SandboxUnavailable) as exc:
        testrunner.run_tests(
            TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR,
                           layer=TestLayer.UNIT, image_override=ABSENT_IMAGE)
        )
    assert "build-images.sh" in str(exc.value)
    assert sandbox.image_present(ABSENT_IMAGE) is False, "the runtime built or pulled the image"


# --- the run's response to a real absent boundary ----------------------------

def test_real_unreachable_daemon_safe_stops_and_preserves_state(unreachable_daemon):
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
    assert [event for event, _ in audited] == ["SAFE_STOP_SANDBOX_UNAVAILABLE"]
    assert dispatcher.context.changes == [], "state was mutated despite the safe stop"
    assert outcome.violations == 0, "a missing boundary is not a retryable violation"
    assert "the Docker daemon is unavailable" in audited[0][1], "the reason was not audited"


def test_a_real_process_with_no_daemon_exits_without_running_tests(unreachable_daemon):
    """End-to-end in a separate interpreter: no daemon, no test execution."""
    import os

    env = dict(os.environ)
    env["DOCKER_HOST"] = UNREACHABLE_DAEMON
    env["PYTHONPATH"] = str(ORCHESTRATOR)
    result = subprocess.run(
        [sys.executable, "-c",
         ("from pathlib import Path\n"
          "from src.agent.testrunner import TestLayer, TestRunRequest, run_tests\n"
          "from src.agent.errors import SandboxUnavailable\n"
          "from src.models.states import Surface\n"
          "try:\n"
          f"    run_tests(TestRunRequest(repo_root=Path({str(REPO)!r}), "
          "surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT))\n"
          "    print('RAN')\n"
          "except SandboxUnavailable:\n"
          "    print('SANDBOX_UNAVAILABLE')\n")],
        capture_output=True, text=True, cwd=ORCHESTRATOR, env=env, timeout=180, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "SANDBOX_UNAVAILABLE" in result.stdout
    assert "RAN" not in result.stdout
    assert "passed" not in result.stdout, "tests executed despite an absent sandbox"
