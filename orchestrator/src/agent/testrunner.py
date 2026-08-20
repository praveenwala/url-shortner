"""Fixed per-surface test commands, executed only in the sandbox (T050, R15).

The agent supplies no command text. Its only input is a `TestLayer` enum value,
validated by the tool schema before a handler sees it. Commands come from a
frozen table, so `;`, `&&`, and `$( )` have no meaning anywhere in this path.
"""

from __future__ import annotations

import secrets
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.agent import sandbox
from src.agent.errors import SandboxError, ToolViolation
from src.agent.sandbox import SandboxLimits, SandboxResult
from src.models.states import Surface


class TestLayer(StrEnum):
    __test__ = False  # pytest must not collect this as a test class

    UNIT = "unit"
    INTEGRATION = "integration"
    WORKFLOW = "workflow"
    FAILURE = "failure"


#: The only commands that can ever run. Values are argv tuples, never strings:
#: there is no shell in this path to interpret metacharacters.
TEST_COMMANDS: dict[tuple[Surface, TestLayer], tuple[str, ...]] = {
    (Surface.ORCHESTRATOR, TestLayer.UNIT):
        ("python", "-m", "pytest", "tests", "-m", "unit", "-q"),
    (Surface.ORCHESTRATOR, TestLayer.WORKFLOW):
        ("python", "-m", "pytest", "tests", "-m", "workflow and not integration", "-q"),
    (Surface.ORCHESTRATOR, TestLayer.FAILURE):
        ("python", "-m", "pytest", "tests", "-m", "failure", "-q"),
    (Surface.ORCHESTRATOR, TestLayer.INTEGRATION):
        ("python", "-m", "pytest", "tests", "-m", "integration", "-q"),
    # -o (offline) and the baked repo path are what let this run with
    # --network none: the sandbox image warmed /m2 at build time.
    # -o (offline) plus the repository warmed at image build is what lets this
    # run with --network none. -Dstyle.color=never keeps Maven from unpacking
    # jansi's native library into /tmp, which is deliberately mounted noexec.
    (Surface.SHORTENER, TestLayer.UNIT):
        ("mvn", "-B", "-o", "-Dmaven.repo.local=/m2", "-Dstyle.color=never",
         "test", "-Dtest=**/unit/*Test"),
    (Surface.SHORTENER, TestLayer.INTEGRATION):
        ("mvn", "-B", "-o", "-Dmaven.repo.local=/m2", "-Dstyle.color=never", "verify"),
    (Surface.CONSOLE, TestLayer.UNIT):
        ("npm", "run", "test", "--", "--run"),
}

SURFACE_IMAGES: dict[Surface, str] = {
    Surface.ORCHESTRATOR: "agent-sandbox/orchestrator:latest",
    Surface.SHORTENER: "agent-sandbox/shortener:latest",
    Surface.CONSOLE: "agent-sandbox/console:latest",
}

#: Layers that get a database dependency. Everything else runs with no network.
_NEEDS_DEPENDENCY: frozenset[TestLayer] = frozenset({TestLayer.INTEGRATION})


@dataclass(frozen=True, slots=True)
class TestRunRequest:
    __test__ = False

    repo_root: Path
    surface: Surface
    layer: TestLayer
    limits: SandboxLimits = SandboxLimits()
    image_override: str | None = None


def run_tests(request: TestRunRequest) -> SandboxResult:
    """Copy the surface, run its fixed command in a sandbox, discard the copy."""
    key = (request.surface, request.layer)
    if key not in TEST_COMMANDS:
        raise ToolViolation(
            f"no approved test command for {request.surface.value}/{request.layer.value}"
        )
    argv = TEST_COMMANDS[key]
    image = request.image_override or SURFACE_IMAGES[request.surface]

    # Fail closed before anything is copied. No daemon or no image means no
    # boundary, and no boundary means run_tests does not run (R15).
    sandbox.require_sandbox(image)

    with tempfile.TemporaryDirectory(prefix="agent-surface-") as tmp:
        workroot = Path(tmp)
        sandbox.assert_disposable(request.repo_root, workroot)
        copy = sandbox.materialise_surface_copy(request.repo_root, request.surface, workroot)

        if request.layer in _NEEDS_DEPENDENCY:
            return _run_with_database(copy, image, argv, request.limits)
        return sandbox.run_in_sandbox(
            image=image, argv=argv, workdir_host=copy,
            limits=request.limits, network="none",
        )
    # TemporaryDirectory removes the copy here, on every path including failure.


def _run_with_database(
    copy: Path, image: str, argv: tuple[str, ...], limits: SandboxLimits
) -> SandboxResult:
    """Integration path: the orchestrator provisions the dependency, not the test.

    The test runner never sees the Docker socket, so it cannot start, inspect,
    or reach anything the orchestrator did not put on its network. The network
    is `--internal`, so there is no route to the internet from either container.
    """
    network = sandbox.create_isolated_network()
    password = secrets.token_urlsafe(24)  # test-only, lives as long as the container
    pg = None
    try:
        pg = sandbox.start_postgres_dependency(network, password)
        if not sandbox.wait_for_postgres(pg):
            raise SandboxError("disposable postgres did not become ready")
        dsn = f"postgresql+psycopg://postgres:{password}@{pg}:5432/agent_test"
        return sandbox.run_in_sandbox(
            image=image, argv=argv, workdir_host=copy, limits=limits,
            network=network, env={"ORCHESTRATOR_TEST_DSN": dsn},
        )
    finally:
        if pg:
            sandbox.stop_container(pg)
        sandbox.remove_network(network)
