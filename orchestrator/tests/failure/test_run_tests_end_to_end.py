"""End-to-end `run_tests` against the real per-surface sandbox images (R15).

These execute the projects' own suites inside the sandbox, offline and
non-root, proving the boundary is not merely configured but usable. They need
the provisioned images: `ops/sandbox/build-images.sh all`.
"""

from pathlib import Path

import pytest

from src.agent import sandbox
from src.agent.errors import SandboxUnavailable
from src.agent.sandbox import SandboxLimits
from src.agent.testrunner import SURFACE_IMAGES, TestLayer, TestRunRequest, run_tests
from src.models.states import Surface

pytestmark = [pytest.mark.failure, pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]


def _require(surface: Surface) -> None:
    image = SURFACE_IMAGES[surface]
    try:
        sandbox.require_sandbox(image)
    except SandboxUnavailable as exc:
        pytest.skip(f"sandbox image not provisioned: {exc}")


def test_orchestrator_unit_tests_run_in_the_real_sandbox():
    _require(Surface.ORCHESTRATOR)
    result = run_tests(
        TestRunRequest(
            repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT,
            limits=SandboxLimits(wall_clock_seconds=180, memory="1g"),
        )
    )
    assert result.passed, result.output
    assert "passed" in result.output


def test_orchestrator_workflow_tests_run_in_the_real_sandbox():
    """The heavier layer, still with no network: proves dependencies are baked
    into the image rather than fetched at run time."""
    _require(Surface.ORCHESTRATOR)
    result = run_tests(
        TestRunRequest(
            repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.WORKFLOW,
            limits=SandboxLimits(wall_clock_seconds=300, memory="1g"),
        )
    )
    assert result.passed, result.output
    assert "passed" in result.output


def test_shortener_unit_tests_run_in_the_real_sandbox():
    """Maven runs fully offline against the repository warmed at image build."""
    _require(Surface.SHORTENER)
    result = run_tests(
        TestRunRequest(
            repo_root=REPO, surface=Surface.SHORTENER, layer=TestLayer.UNIT,
            limits=SandboxLimits(wall_clock_seconds=600, memory="2g", cpus="2.0",
                                 max_output_bytes=200_000),
        )
    )
    assert result.passed, result.output
    assert "BUILD SUCCESS" in result.output


def test_end_to_end_run_leaves_the_authoritative_repository_untouched():
    _require(Surface.ORCHESTRATOR)
    victim = REPO / "orchestrator" / "src" / "models" / "states.py"
    before = victim.read_bytes()
    run_tests(
        TestRunRequest(
            repo_root=REPO, surface=Surface.ORCHESTRATOR, layer=TestLayer.UNIT,
            limits=SandboxLimits(wall_clock_seconds=180, memory="1g"),
        )
    )
    assert victim.read_bytes() == before
