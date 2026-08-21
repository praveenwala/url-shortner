"""Fail-closed Docker availability (CI-discovered runtime defect).

`docker_available` previously returned `probe.returncode == 0`. Some Docker CLI versions exit 0
for `docker info --format` even when the daemon is unreachable, rendering an empty or
`<no value>` ServerVersion — so on such a CLI the check reported a daemon that was not there.

That answer gates `require_sandbox`, which is the fail-closed control: a false positive means
`run_tests` proceeds instead of raising `SandboxUnavailable` and safe-stopping. Every case below
must therefore resolve to **unavailable** unless a real daemon named itself.

No Docker daemon is required — `subprocess.run` is substituted so each outcome is exact.
"""

from __future__ import annotations

import subprocess

import pytest

from src.agent import sandbox

pytestmark = pytest.mark.failure


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _probe(monkeypatch, outcome):
    """`outcome` is a _Result to return, or an exception instance to raise."""
    def fake_run(cmd, *args, **kwargs):
        assert cmd[:2] == ["docker", "info"], f"unexpected probe: {cmd}"
        assert kwargs.get("timeout") == 15, "the bounded timeout was dropped"
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    monkeypatch.setattr(subprocess, "run", fake_run)


# --- available only when a daemon actually names itself -----------------------

def test_clean_exit_with_a_real_version_is_available(monkeypatch):
    _probe(monkeypatch, _Result(0, "29.4.3\n"))
    assert sandbox.docker_available() is True


# --- the defect: exit 0 without a usable version ------------------------------

def test_clean_exit_with_empty_stdout_is_unavailable(monkeypatch):
    """The exact CI symptom: the CLI exits 0 but the daemon is not there."""
    _probe(monkeypatch, _Result(0, ""))
    assert sandbox.docker_available() is False


def test_clean_exit_with_no_value_placeholder_is_unavailable(monkeypatch):
    _probe(monkeypatch, _Result(0, "<no value>\n"))
    assert sandbox.docker_available() is False


def test_clean_exit_with_only_whitespace_is_unavailable(monkeypatch):
    _probe(monkeypatch, _Result(0, "   \n\t "))
    assert sandbox.docker_available() is False


# --- the cases that already worked, pinned so they cannot regress -------------

def test_non_zero_exit_is_unavailable(monkeypatch):
    _probe(monkeypatch, _Result(1, "", "Cannot connect to the Docker daemon"))
    assert sandbox.docker_available() is False


def test_non_zero_exit_is_unavailable_even_if_a_version_is_printed(monkeypatch):
    _probe(monkeypatch, _Result(1, "29.4.3\n"))
    assert sandbox.docker_available() is False


def test_missing_docker_binary_is_unavailable(monkeypatch):
    _probe(monkeypatch, FileNotFoundError("docker"))
    assert sandbox.docker_available() is False


def test_oserror_is_unavailable(monkeypatch):
    _probe(monkeypatch, OSError("permission denied"))
    assert sandbox.docker_available() is False


def test_timeout_is_unavailable(monkeypatch):
    _probe(monkeypatch, subprocess.TimeoutExpired(cmd="docker info", timeout=15))
    assert sandbox.docker_available() is False


def test_other_subprocess_errors_are_unavailable(monkeypatch):
    _probe(monkeypatch, subprocess.SubprocessError("broken pipe"))
    assert sandbox.docker_available() is False


# --- the consequence that makes this a security control ----------------------

def test_an_unusable_daemon_makes_require_sandbox_fail_closed(monkeypatch):
    """The whole point: a false positive here would let run_tests proceed unsandboxed."""
    from src.agent.errors import SandboxUnavailable

    _probe(monkeypatch, _Result(0, ""))          # exit 0, no version — the CI symptom
    with pytest.raises(SandboxUnavailable) as exc:
        sandbox.require_sandbox("agent-sandbox/orchestrator:latest")
    assert "refuses to execute on the host" in str(exc.value)
