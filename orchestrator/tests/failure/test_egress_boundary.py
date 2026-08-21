"""T099 — the control-plane egress boundary, verified against a real process.

Every assertion here is made against a live socket, a live subprocess, or a real
`EgressDenied` raised by the installed guard. That distinction is the whole
point of this file: `src/agent/config.py` has always *described* an allow-list,
and a unit test that calls `policy.permits(...)` would have passed throughout
the entire period in which the guard was never installed in the running
application at all. Only starting the real process and trying to resolve a
denied host catches that.

The denied-destination proof does not rely on the absence of an exception. A
listener is bound on a real non-loopback address and the guard is asked to
connect to it; the test asserts both that `EgressDenied` was raised *and* that
the listener accepted nothing — no packet, not merely no response.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src.agent.config import (
    DEFAULT_ANTHROPIC_BASE_URL,
    build_policy,
    install_socket_guard,
    remove_socket_guard,
)
from src.agent.errors import EgressDenied
from src.api.errors import ErrorCode

pytestmark = pytest.mark.failure

ORCHESTRATOR = Path(__file__).resolve().parents[2]
DENIED_HOST = "example.com"

#: Sentinels. If any of these strings appears in an error or an audit record,
#: a credential escaped — they are shaped like the real thing on purpose.
FAKE_API_KEY = "sk-ant-api03-EGRESSTEST-NOT-A-REAL-KEY"
FAKE_DB_PASSWORD = "EgressTestDbPassw0rd-not-real"


@pytest.fixture
def guard():
    """Install the real guard against a known policy, and always remove it."""
    policy = build_policy(anthropic_base_url=DEFAULT_ANTHROPIC_BASE_URL,
                          postgres_host="db.internal")
    install_socket_guard(policy)
    try:
        yield policy
    finally:
        remove_socket_guard()


def _subprocess(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run `code` in a real interpreter with the orchestrator importable."""
    import os

    child = dict(os.environ)
    child.update(env or {})
    child["PYTHONPATH"] = str(ORCHESTRATOR)
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=ORCHESTRATOR, env=child, timeout=120, check=False,
    )


# --- the guard is actually in force -----------------------------------------

def test_the_real_application_process_installs_the_guard():
    """Regression for the defect T099 found: the boundary was configured and
    never installed, so the running orchestrator had unrestricted egress."""
    result = _subprocess(
        "import socket\n"
        "from src.api.app import app\n"
        "assert app is not None\n"
        "try:\n"
        f"    socket.getaddrinfo({DENIED_HOST!r}, 443)\n"
        "    print('RESOLVED')\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__)\n",
        env={"ORCHESTRATOR_DB_URL":
             f"postgresql+psycopg://orchestrator_app:{FAKE_DB_PASSWORD}@localhost:5432/orchestrator_db"},
    )
    assert result.returncode == 0, result.stderr
    assert "EgressDenied" in result.stdout, (
        f"the running application did not deny egress to {DENIED_HOST}: {result.stdout!r}"
    )
    assert "RESOLVED" not in result.stdout


def test_the_guard_survives_a_client_library_import():
    """httpx/urllib bind `socket.getaddrinfo` at call time, not import time — so
    installing the guard before or after the import must be equivalent."""
    result = _subprocess(
        "import urllib.request\n"
        "from src.api.app import app\n"
        "try:\n"
        f"    urllib.request.urlopen('https://{DENIED_HOST}', timeout=5)\n"
        "    print('FETCHED')\n"
        "except Exception as exc:\n"
        "    print(type(exc).__name__, str(exc)[:120])\n"
    )
    assert result.returncode == 0, result.stderr
    assert "FETCHED" not in result.stdout
    assert "EgressDenied" in result.stdout, result.stdout


# --- allowed destinations ---------------------------------------------------

def test_configured_claude_host_is_permitted(guard):
    """A real resolution attempt against the configured model endpoint. The
    network may or may not answer; what must not happen is a policy refusal."""
    try:
        socket.getaddrinfo("api.anthropic.com", 443)
    except EgressDenied as exc:  # pragma: no cover - the failure we are testing for
        pytest.fail(f"the only permitted model endpoint was refused: {exc}")
    except OSError:
        pass  # DNS unavailable in this environment; the policy still permitted it


def test_configured_postgres_host_is_permitted(guard):
    assert guard.permits("db.internal")
    with pytest.raises(OSError) as exc:  # resolves nowhere, but is not refused
        socket.getaddrinfo("db.internal", 5432)
    assert not isinstance(exc.value, EgressDenied)


def test_loopback_is_permitted(guard):
    """The orchestrator's own health checks and a local database must work."""
    assert guard.permits("127.0.0.1")
    socket.getaddrinfo("127.0.0.1", 5432)


# --- denied destinations ----------------------------------------------------

def test_dns_for_an_arbitrary_external_host_is_denied(guard):
    with pytest.raises(EgressDenied) as exc:
        socket.getaddrinfo(DENIED_HOST, 443)
    assert DENIED_HOST in str(exc.value)


def test_connection_to_an_arbitrary_external_address_is_denied(guard):
    with pytest.raises(EgressDenied):
        socket.create_connection(("93.184.216.34", 80), timeout=5)


def _non_loopback_address() -> str:
    """A real address of this host that is not 127.0.0.1.

    The obvious `gethostbyname(gethostname())` is not usable: on macOS it
    returns loopback, which the policy always permits, so the probe would prove
    nothing. This asks the routing table which local address would be used to
    leave the machine.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))  # no packet is sent for UDP connect
        address = probe.getsockname()[0]
    finally:
        probe.close()
    if address.startswith("127."):
        pytest.skip("no non-loopback address on this host")
    return address


def test_no_packet_reaches_a_denied_destination():
    """Not 'the call raised' — 'the listener never heard from us'."""
    reachable = _non_loopback_address()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((reachable, 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]

    install_socket_guard(build_policy(anthropic_base_url=DEFAULT_ANTHROPIC_BASE_URL))
    try:
        # Positive control: the destination really is listening and reachable.
        with pytest.raises(EgressDenied):
            socket.create_connection((reachable, port), timeout=5)
        with pytest.raises((TimeoutError, socket.timeout)):
            listener.accept()
    finally:
        remove_socket_guard()
        # ... and with the guard removed, it accepts — so the refusal above was
        # the policy, not an unreachable address.
        confirm = socket.create_connection((reachable, port), timeout=5)
        accepted, _ = listener.accept()
        accepted.close()
        confirm.close()
        listener.close()


def test_a_raw_socket_connect_bypasses_the_guard_by_design():
    """A recorded limitation, asserted so it stays recorded.

    The guard wraps `getaddrinfo` and `create_connection` — the two entry points
    every stdlib and third-party HTTP client uses. It does not wrap
    `socket.socket().connect()`, and it cannot: that is the syscall the wrappers
    themselves call. This is why the guard is defense in depth for the
    orchestrator's own code, and why the boundary for agent-authored code is a
    container with `--network none` instead. If this test ever fails, the
    architecture changed and docs/security/egress-verification.md is stale.
    """
    reachable = _non_loopback_address()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((reachable, 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]

    install_socket_guard(build_policy(anthropic_base_url=DEFAULT_ANTHROPIC_BASE_URL))
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(5)
        raw.connect((reachable, port))  # not intercepted
        accepted, _ = listener.accept()
        accepted.close()
        raw.close()
    finally:
        remove_socket_guard()
        listener.close()


def test_denial_is_the_typed_error_and_is_forbidden(guard):
    with pytest.raises(EgressDenied) as exc:
        socket.getaddrinfo(DENIED_HOST, 443)
    assert exc.value.code is ErrorCode.FORBIDDEN


# --- credentials are never echoed -------------------------------------------

def test_denial_names_the_host_but_never_a_credential(guard, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_API_KEY)
    monkeypatch.setenv("ORCHESTRATOR_DB_PASSWORD", FAKE_DB_PASSWORD)
    with pytest.raises(EgressDenied) as exc:
        socket.getaddrinfo(DENIED_HOST, 443)
    message = str(exc.value)
    assert DENIED_HOST in message, "naming the denied host is intended"
    assert FAKE_API_KEY not in message
    assert FAKE_DB_PASSWORD not in message


def test_a_base_url_carrying_credentials_does_not_echo_them():
    """Regression: the unparseable-URL path used to interpolate the raw URL."""
    with pytest.raises(EgressDenied) as exc:
        build_policy(anthropic_base_url=f"https://user:{FAKE_API_KEY}@")
    assert FAKE_API_KEY not in str(exc.value)


def test_database_host_is_taken_from_the_configured_dsn(monkeypatch):
    """Regression: the allow-list read ORCHESTRATOR_DB_HOST while the
    application configured its database through ORCHESTRATOR_DB_URL, so the
    real database host was not on the list the guard enforced."""
    monkeypatch.delenv("ORCHESTRATOR_DB_HOST", raising=False)
    monkeypatch.setenv(
        "ORCHESTRATOR_DB_URL",
        f"postgresql+psycopg://orchestrator_app:{FAKE_DB_PASSWORD}@db.internal:5432/orchestrator_db",
    )
    policy = build_policy()
    assert policy.permits("db.internal")
    assert FAKE_DB_PASSWORD not in repr(policy)


def test_a_malformed_dsn_is_refused_without_echoing_the_password(monkeypatch):
    monkeypatch.delenv("ORCHESTRATOR_DB_HOST", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_DB_URL", f":::{FAKE_DB_PASSWORD}:::")
    with pytest.raises(EgressDenied) as exc:
        build_policy()
    assert FAKE_DB_PASSWORD not in str(exc.value)
