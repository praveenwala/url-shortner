"""T048 — sandbox escape tests (research R15, HUMAN-approved boundary).

These are the tests that matter most in checkpoint 2d. Bounding the agent's
*tool surface* stops it asking for a shell; it does not bound code the agent
*wrote* once `run_tests` executes it. Each test below runs a probe inside the
real sandbox and asserts the escape fails.

Skipped when Docker is unavailable — and that skip is itself a finding, because
without Docker `run_tests` has no boundary and must not be used.
"""

import os
import subprocess
from pathlib import Path

import pytest

from src.agent import sandbox
from src.agent.errors import SandboxError
from src.agent.sandbox import SandboxLimits, materialise_surface_copy, run_in_sandbox
from src.models.states import Surface

pytestmark = [pytest.mark.failure, pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
PROBE_IMAGE = "alpine:3"
FAST = SandboxLimits(wall_clock_seconds=45, memory="256m", pids=64)

pytestmark.append(
    pytest.mark.skipif(not sandbox.docker_available(), reason="Docker daemon unavailable")
)


@pytest.fixture(scope="module", autouse=True)
def probe_image():
    subprocess.run(["docker", "pull", PROBE_IMAGE], capture_output=True, check=False, timeout=300)


@pytest.fixture()
def surface_copy(tmp_path):
    return materialise_surface_copy(REPO, Surface.ORCHESTRATOR, tmp_path)


def _probe(workdir, argv, limits=FAST, network="none"):
    return run_in_sandbox(
        image=PROBE_IMAGE, argv=argv, workdir_host=workdir, limits=limits, network=network
    )


# --- network ----------------------------------------------------------------

def test_agent_test_code_cannot_reach_arbitrary_internet_hosts(surface_copy):
    result = _probe(surface_copy, ("sh", "-c", "wget -T 5 -q -O- https://example.com; echo rc=$?"))
    assert "rc=0" not in result.output
    assert "<html" not in result.output.lower()


def test_dns_resolution_is_unavailable(surface_copy):
    # No pipeline: `echo rc=$?` must report nslookup's status, not head's.
    result = _probe(surface_copy, ("sh", "-c", "nslookup example.com >/dev/null 2>&1; echo rc=$?"))
    assert "rc=0" not in result.output


# --- filesystem view --------------------------------------------------------

def test_ops_directory_is_not_present_in_the_sandbox(surface_copy):
    result = _probe(surface_copy, ("sh", "-c", "ls -a / /work 2>&1"))
    assert "provision.sh" not in result.output
    assert not (surface_copy / "ops").exists()


def test_git_directory_is_not_present_in_the_sandbox(surface_copy):
    result = _probe(surface_copy, ("sh", "-c", "find / -maxdepth 4 -name '.git' 2>/dev/null"))
    assert result.output.strip() == "" or ".git" not in result.output


def test_host_home_and_secrets_are_not_reachable(surface_copy):
    """Assert on key *material*, not on paths — an error message naturally echoes
    the path that was attempted."""
    result = _probe(
        surface_copy,
        ("sh", "-c",
         "ls -a $HOME 2>&1; cat $HOME/.aws/credentials 2>&1; cat /host/.ssh/id_rsa 2>&1"),
    )
    for material in ("aws_access_key", "BEGIN OPENSSH", "BEGIN RSA", "ssh-rsa "):
        assert material not in result.output
    assert "No such file" in result.output, "the secret paths should not resolve at all"
    assert result.output.count("Documents") == 0, "host home directory is visible"


def test_docker_socket_is_not_mounted(surface_copy):
    result = _probe(
        surface_copy,
        ("sh", "-c", "ls -l /var/run/docker.sock 2>&1; echo rc=$?"),
    )
    assert "rc=0" not in result.output


def test_other_surfaces_are_not_present(surface_copy):
    """/work is the approved surface's own root — no sibling surface is reachable."""
    result = _probe(surface_copy, ("sh", "-c", "ls /work; ls / 2>&1"))
    assert "shortener" not in result.output
    assert "console" not in result.output
    # positive control: it really is the orchestrator surface
    assert "pyproject.toml" in result.output and "src" in result.output


def test_environment_carries_no_secrets(surface_copy):
    os.environ["PROBE_FAKE_SECRET"] = "should-not-be-visible"
    try:
        result = _probe(surface_copy, ("sh", "-c", "env"))
        assert "should-not-be-visible" not in result.output
        assert "ANTHROPIC" not in result.output
        assert "_PW=" not in result.output
    finally:
        os.environ.pop("PROBE_FAKE_SECRET", None)


# --- mutations never propagate ----------------------------------------------

def test_mutations_do_not_propagate_to_the_authoritative_repository(surface_copy):
    victim = REPO / "orchestrator" / "src" / "models" / "states.py"
    before = victim.read_bytes()

    result = _probe(
        surface_copy,
        ("sh", "-c",
         "echo TAMPERED > /work/src/models/states.py; "
         "rm -rf /work/tests 2>/dev/null; echo done"),
    )
    assert "done" in result.output
    # the copy was mutated ...
    assert (surface_copy / "src/models/states.py").read_text().strip() == "TAMPERED"
    # ... and the authoritative file is untouched
    assert victim.read_bytes() == before
    assert (REPO / "orchestrator" / "tests").is_dir()


def test_running_against_the_authoritative_repository_is_refused():
    """The invariant is checked, not merely observed by convention."""
    with pytest.raises(SandboxError):
        sandbox.assert_disposable(REPO, REPO / "orchestrator")


def test_the_copy_is_discarded_after_the_run(tmp_path):
    from src.agent.testrunner import TestLayer, TestRunRequest, run_tests

    seen: list[Path] = []
    original = sandbox.run_in_sandbox

    def spy(**kwargs):
        seen.append(Path(kwargs["workdir_host"]))
        return original(**kwargs, ) if False else sandbox.SandboxResult(0, "", False, False, 0.0)

    sandbox.run_in_sandbox = spy  # type: ignore[assignment]
    try:
        import src.agent.testrunner as tr
        tr.sandbox.run_in_sandbox = spy  # type: ignore[assignment]
        run_tests(TestRunRequest(repo_root=REPO, surface=Surface.ORCHESTRATOR,
                                 layer=TestLayer.UNIT, image_override=PROBE_IMAGE))
    finally:
        sandbox.run_in_sandbox = original  # type: ignore[assignment]
        import src.agent.testrunner as tr
        tr.sandbox.run_in_sandbox = original  # type: ignore[assignment]

    assert seen, "the sandbox was never invoked"
    assert not seen[0].exists(), "the disposable copy outlived the run"


# --- privilege and resource bounds ------------------------------------------

def test_container_is_not_privileged_and_cannot_gain_privileges(surface_copy):
    result = _probe(surface_copy, ("sh", "-c", "id -u; cat /proc/self/status | grep -i nonewprivs"))
    assert result.output.strip().splitlines()[0] != "0", "running as root"
    assert "NoNewPrivs:\t1" in result.output


def test_wall_clock_timeout_terminates_execution(surface_copy):
    limits = SandboxLimits(wall_clock_seconds=5)
    result = _probe(surface_copy, ("sh", "-c", "sleep 120"), limits=limits)
    assert result.timed_out
    assert result.duration_seconds < 30


def test_memory_limit_is_applied(surface_copy):
    limits = SandboxLimits(memory="16m", wall_clock_seconds=30)
    result = _probe(
        surface_copy,
        ("sh", "-c", "dd if=/dev/zero of=/dev/shm/fill bs=1M count=64 2>&1; echo rc=$?"),
        limits=limits,
    )
    assert "rc=0" not in result.output or result.exit_code != 0


def test_output_is_truncated_to_the_cap(surface_copy):
    limits = SandboxLimits(max_output_bytes=2048, wall_clock_seconds=45)
    result = _probe(surface_copy, ("sh", "-c", "yes abcdefghij | head -c 200000"), limits=limits)
    assert result.truncated
    assert len(result.output) <= 2048 + 64
