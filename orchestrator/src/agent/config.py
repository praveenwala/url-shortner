"""Orchestrator egress allow-list and socket guard (T015).

**Scope, stated plainly.** This guard covers *this process only*. It is defense
in depth, not the sandbox for agent-authored code — code the agent writes runs
in an ephemeral container with `--network none` (research R15), and that
container is what actually bounds it. A socket guard in the parent process
would do nothing for a child process, and describing it as the sandbox would
overstate what it does.

What it does cover: an accidental or injected outbound call from orchestrator
code itself — a dependency phoning home, a misconfigured base URL, a tool
handler that grew a fetch. Everything except the configured Claude endpoint and
the orchestrator's own PostgreSQL is refused at connect time.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from src.agent.errors import EgressDenied

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"

_ALWAYS_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_original_getaddrinfo = socket.getaddrinfo
_original_create_connection = socket.create_connection


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    allowed_hosts: frozenset[str]

    def permits(self, host: str) -> bool:
        return host in self.allowed_hosts or host in _ALWAYS_ALLOWED_HOSTS


def _redacted(url: str) -> str:
    """A URL safe to put in an error message.

    Configuration URLs carry credentials — a database DSN always does, and a
    base URL pointed at an authenticating proxy can. The failure path is
    precisely where they used to be echoed verbatim, so everything between the
    scheme and the last `@` is dropped before the string is ever formatted.
    """
    scheme, separator, rest = url.partition("://")
    if not separator:
        return "<redacted>"
    _, at, tail = rest.rpartition("@")
    return f"{scheme}://{tail if at else rest}"


def _host_of(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise EgressDenied(f"cannot determine host from {_redacted(url)!r}")
    return parsed.hostname


def build_policy(
    anthropic_base_url: str | None = None, postgres_host: str | None = None
) -> EgressPolicy:
    """Assemble the allow-list from the configuration the process actually uses.

    The database host is derived from `ORCHESTRATOR_DB_URL` — the same variable
    `api.deps.get_engine` connects with — rather than from a second variable
    that could disagree with it. When the two disagree the guard denies the
    application's own database, which is the kind of failure that gets a
    security control switched off instead of fixed.
    """
    base = anthropic_base_url or os.environ.get(
        "ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL
    )
    hosts = {_host_of(base)}
    pg = postgres_host or os.environ.get("ORCHESTRATOR_DB_HOST")
    if not pg:
        dsn = os.environ.get("ORCHESTRATOR_DB_URL")
        if dsn:
            pg = _host_of(dsn)
    if pg:
        hosts.add(pg)
    return EgressPolicy(allowed_hosts=frozenset(hosts))


def install_socket_guard(policy: EgressPolicy) -> None:
    """Wrap the two entry points every Python network client goes through."""

    def guarded_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host is not None and not policy.permits(str(host)):
            raise EgressDenied(
                f"egress to {host!r} is not permitted; allow-list is "
                f"{sorted(policy.allowed_hosts)}"
            )
        return _original_getaddrinfo(host, port, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        host = address[0] if isinstance(address, tuple) else address
        if not policy.permits(str(host)):
            raise EgressDenied(f"egress to {host!r} is not permitted")
        return _original_create_connection(address, *args, **kwargs)

    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]


def remove_socket_guard() -> None:
    """Restore the originals. Used by tests; not called in normal operation."""
    socket.getaddrinfo = _original_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _original_create_connection  # type: ignore[assignment]
