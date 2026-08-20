"""T099 — the integration sandbox's real network topology.

The integration layer is the one place the sandbox is *not* `--network none`:
tests need a database. That makes it the interesting case, because a
misconfigured network here would hand agent-authored code both a database and
the internet. This file builds the real topology the runtime builds and probes
it from inside the test-runner container:

    test runner  <--internal network-->  disposable PostgreSQL
                 (no route off the host, no Docker socket)

Connectivity is proved at the PostgreSQL protocol level with `psql`, not with a
TCP knock, so "reachable" means the database actually answered.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from src.agent import sandbox
from src.agent.sandbox import SandboxLimits

pytestmark = [pytest.mark.failure, pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
PROBE_IMAGE = "postgres:16-alpine"  # has psql; also the dependency image
PROBE_LIMITS = SandboxLimits(wall_clock_seconds=60, memory="256m", pids=64)

pytestmark.append(
    pytest.mark.skipif(not sandbox.docker_available(), reason="Docker daemon unavailable")
)


@pytest.fixture(scope="module")
def topology(tmp_path_factory):
    """The exact topology `testrunner._run_with_database` constructs."""
    if not sandbox.image_present(PROBE_IMAGE):
        pytest.skip(f"probe image {PROBE_IMAGE} not present")

    workdir = tmp_path_factory.mktemp("integration-topology")
    (workdir / "marker.txt").write_text("disposable copy\n")

    network = sandbox.create_isolated_network(prefix="t099-net")
    password = secrets.token_urlsafe(24)
    pg = None
    try:
        pg = sandbox.start_postgres_dependency(network, password, image=PROBE_IMAGE)
        assert sandbox.wait_for_postgres(pg), "the disposable database never became ready"
        yield {"network": network, "pg": pg, "password": password, "workdir": workdir}
    finally:
        if pg:
            sandbox.stop_container(pg)
        sandbox.remove_network(network)


def _probe(topology, script: str):
    return sandbox.run_in_sandbox(
        image=PROBE_IMAGE,
        argv=("sh", "-c", script),
        workdir_host=topology["workdir"],
        limits=PROBE_LIMITS,
        network=topology["network"],
        env={"PGHOST": topology["pg"], "PGUSER": "postgres",
             "PGDATABASE": "agent_test", "PGPASSWORD": topology["password"]},
    )


# --- the dependency is reachable --------------------------------------------

def test_the_disposable_postgres_answers_the_test_runner(topology):
    result = _probe(topology, "psql -tAc 'select 1 as reachable' 2>&1")
    assert result.exit_code == 0, result.output
    assert "1" in result.output


def test_the_network_is_internal(topology):
    """Docker's own view: an internal network has no gateway to the outside."""
    import json
    import subprocess

    inspected = subprocess.run(
        ["docker", "network", "inspect", topology["network"]],
        capture_output=True, text=True, check=True, timeout=60,
    )
    assert json.loads(inspected.stdout)[0]["Internal"] is True


# --- and nothing else is ----------------------------------------------------

def test_arbitrary_internet_egress_is_unavailable_to_the_test_runner(topology):
    result = _probe(
        topology,
        "nc -w 5 -z 93.184.216.34 80 >/dev/null 2>&1; echo tcp_rc=$?; "
        "nc -w 5 -z 1.1.1.1 443 >/dev/null 2>&1; echo tls_rc=$?",
    )
    assert "tcp_rc=0" not in result.output, result.output
    assert "tls_rc=0" not in result.output, result.output


def test_dns_for_an_external_host_is_unavailable_to_the_test_runner(topology):
    result = _probe(
        topology,
        "getent hosts example.com >/dev/null 2>&1; echo dns_rc=$?; "
        "getent hosts api.anthropic.com >/dev/null 2>&1; echo model_rc=$?",
    )
    assert "dns_rc=0" not in result.output, result.output
    assert "model_rc=0" not in result.output, (
        "the test runner could resolve the model endpoint; the one permitted "
        "egress must belong to the orchestrator, never to agent-authored code"
    )


def test_the_docker_socket_is_not_mounted_into_the_test_runner(topology):
    result = _probe(topology, "ls -l /var/run/docker.sock 2>&1; echo rc=$?")
    assert "rc=0" not in result.output, result.output


def test_the_test_runner_cannot_reach_the_hosts_own_services(topology):
    """An internal network still must not expose the host's loopback services."""
    result = _probe(
        topology,
        "nc -w 3 -z host.docker.internal 5432 >/dev/null 2>&1; echo host_rc=$?",
    )
    assert "host_rc=0" not in result.output, result.output


def test_only_the_disposable_copy_is_visible(topology):
    result = _probe(topology, "ls /work; ls / 2>&1")
    assert "marker.txt" in result.output
    for surface in ("orchestrator", "shortener", "console", "ops", "specs"):
        assert f"/{surface}" not in result.output


# --- control: the probes themselves work ------------------------------------

def test_the_egress_probes_are_not_vacuous(topology):
    """Without this, every negative test above would still pass on an image
    that simply lacks `nc` and `getent` — a missing binary and a blocked network
    both produce a non-zero exit code. The identical script is run on an
    ordinary bridge network, where it must succeed."""
    import subprocess

    script = (
        "nc -w 5 -z 1.1.1.1 443 >/dev/null 2>&1; echo tls_rc=$?; "
        "getent hosts example.com >/dev/null 2>&1; echo dns_rc=$?"
    )
    control = subprocess.run(
        ["docker", "run", "--rm", "--network", "bridge", PROBE_IMAGE, "sh", "-c", script],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if "tls_rc=0" not in control.stdout or "dns_rc=0" not in control.stdout:
        pytest.skip(f"no outbound network available to run the control: {control.stdout!r}")

    isolated = _probe(topology, script)
    assert "tls_rc=0" not in isolated.output
    assert "dns_rc=0" not in isolated.output
