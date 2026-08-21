"""Readiness of the disposable integration database (CI-discovered runtime defect).

`wait_for_postgres` previously polled `pg_isready -U postgres`. That reports only that *a*
server is accepting connections — including the entrypoint's temporary initialisation server,
and without regard to whether the target database exists. Integration runs were therefore
started against a server that was about to restart, which CI surfaced as
`FATAL: the database system is starting up`.

These tests pin the corrected contract without needing a Docker daemon: `subprocess.run` is
substituted so each probe outcome can be scripted exactly.
"""

from __future__ import annotations

import subprocess

import pytest

from src.agent import sandbox
from src.agent.errors import SandboxError

pytestmark = pytest.mark.failure


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _script(monkeypatch, outcomes):
    """Feed scripted probe results; record every argv the runtime executed."""
    calls: list[list[str]] = []
    queue = list(outcomes)

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        # Once the script is exhausted the last outcome repeats, so a deadline-bounded loop can
        # spin as fast as it likes without falling off the end of the fixture.
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox.time, "sleep", lambda _s: None)
    return calls


OK = _Result(0, "1\n", "")
STARTING_UP = _Result(2, "", "psql: error: FATAL:  the database system is starting up")


# --- the defect itself --------------------------------------------------------

def test_readiness_is_not_granted_by_a_single_success(monkeypatch):
    """One success can land on the temporary init server; the streak must span the restart."""
    calls = _script(monkeypatch, [OK, STARTING_UP, OK, OK, OK])
    assert sandbox.wait_for_postgres("pg-1") is True
    queries = [c for c in calls if "psql" in c]
    assert len(queries) == 5, "readiness returned before the streak was re-established"


def test_a_restart_mid_streak_resets_the_streak(monkeypatch):
    calls = _script(monkeypatch, [OK, OK, STARTING_UP, OK, OK, OK])
    assert sandbox.wait_for_postgres("pg-1") is True
    assert len([c for c in calls if "psql" in c]) == 6


def test_consecutive_successes_release_readiness(monkeypatch):
    calls = _script(monkeypatch, [OK, OK, OK])
    assert sandbox.wait_for_postgres("pg-1") is True
    assert len([c for c in calls if "psql" in c]) == sandbox.READINESS_CONSECUTIVE_OK


def test_a_non_query_success_is_not_readiness(monkeypatch):
    """Exit 0 with the wrong body must not count — this is what pg_isready amounted to."""
    _script(monkeypatch, [_Result(0, "", "")])
    with pytest.raises(SandboxError):
        sandbox.wait_for_postgres("pg-1", timeout_seconds=0.05, poll_seconds=0)


# --- bounded, and diagnosable -------------------------------------------------

def test_timeout_is_bounded_and_raises_the_typed_sandbox_error(monkeypatch):
    _script(monkeypatch, [STARTING_UP])
    with pytest.raises(SandboxError) as exc:
        sandbox.wait_for_postgres("pg-1", timeout_seconds=0.05, poll_seconds=0)
    message = str(exc.value)
    assert "did not become query-ready" in message
    assert "the database system is starting up" in message, "no diagnosis of why it failed"
    assert "polling every" in message, "the bound that was applied is not stated"


def test_timeout_never_loops_unboundedly(monkeypatch):
    """Terminates on a wall-clock deadline, not on an attempt count."""
    import time as _time

    _script(monkeypatch, [STARTING_UP])
    started = _time.monotonic()
    with pytest.raises(SandboxError):
        sandbox.wait_for_postgres("pg-1", timeout_seconds=0.2, poll_seconds=0)
    assert _time.monotonic() - started < 5.0, "the loop is not deadline-bounded"


def test_failure_message_carries_no_credentials(monkeypatch):
    _script(monkeypatch, [STARTING_UP])
    with pytest.raises(SandboxError) as exc:
        sandbox.wait_for_postgres("pg-1", timeout_seconds=0.05, poll_seconds=0)
    assert "password" not in str(exc.value).lower()


# --- the probe targets the right database, in the right place -----------------

def test_the_probe_names_the_configured_user_and_database(monkeypatch):
    calls = _script(monkeypatch, [OK, OK, OK])
    sandbox.wait_for_postgres("pg-1")
    probe = next(c for c in calls if "psql" in c)
    assert "-U" in probe and probe[probe.index("-U") + 1] == sandbox.POSTGRES_DEPENDENCY_USER
    assert "-d" in probe and probe[probe.index("-d") + 1] == sandbox.POSTGRES_DEPENDENCY_DB
    assert "select 1" in probe, "readiness must run a real query, not a liveness ping"
    assert "pg_isready" not in probe, "process readiness is not database readiness"


def test_the_probe_runs_inside_the_named_container_and_never_on_the_host(monkeypatch):
    calls = _script(monkeypatch, [OK, OK, OK])
    sandbox.wait_for_postgres("pg-target")
    for probe in (c for c in calls if "psql" in c):
        assert probe[:3] == ["docker", "exec", "pg-target"], "probe escaped the container"


def test_readiness_adds_no_new_docker_subcommand(monkeypatch):
    """The runtime's docker verb set is an enforced minimum; diagnostics must not widen it."""
    calls = _script(monkeypatch, [STARTING_UP])
    with pytest.raises(SandboxError):
        sandbox.wait_for_postgres("pg-1", timeout_seconds=0.05, poll_seconds=0)
    verbs = {c[1] for c in calls if c and c[0] == "docker"}
    assert verbs == {"exec"}, f"readiness used unexpected docker subcommands: {sorted(verbs)}"


def test_no_password_is_ever_placed_in_an_argv(monkeypatch):
    """A credential in argv leaks into the host process list."""
    calls = _script(monkeypatch, [OK, OK, OK])
    sandbox.wait_for_postgres("pg-1")
    joined = " ".join(" ".join(c) for c in calls)
    for leak in ("PGPASSWORD", "--password", "-W"):
        assert leak not in joined
