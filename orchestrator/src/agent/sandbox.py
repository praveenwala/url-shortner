"""Ephemeral Docker test sandbox for agent-authored code (T049, research R15).

HUMAN-approved capability boundary. The rule this module exists to enforce:
**the authoritative repository is never mounted into a container** — not
writable, not read-only. Every invocation runs against a disposable
task-scoped copy of one approved surface, which is discarded afterwards, so an
unexpected filesystem mutation has nowhere to propagate to.

Docker is driven through its CLI rather than a Python SDK, deliberately: it adds
no dependency to the orchestrator, and the exact argv is visible at the call
site, which is the thing a reviewer needs to check.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from src.agent.errors import SandboxError, SandboxUnavailable
from src.models.states import Surface

# Never copied into the sandbox. Some are secrets, some are the governance and
# operational trees an agent must not see, some are just noise.
EXCLUDED_FROM_COPY: frozenset[str] = frozenset(
    {
        ".git", ".github", "ops", ".specify", "specs",
        ".venv", "venv", "node_modules", "target", "build", "dist",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        ".env", ".envrc", ".ssh", ".aws", ".docker", ".npmrc", ".netrc",
    }
)

_EXCLUDED_SUFFIXES = (".pem", ".key", ".p12", ".keystore")


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    cpus: str = "1.0"
    memory: str = "512m"
    pids: int = 128
    wall_clock_seconds: int = 120
    max_output_bytes: int = 32 * 1024


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    output: str
    timed_out: bool
    truncated: bool
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, timeout=15, check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def image_present(image: str) -> bool:
    """Images are built by a provisioning step, never by the runtime.

    An agent cannot cause an image build: `run_tests` only ever *checks*. A
    missing image is a provisioning failure the operator must fix, not
    something the runtime resolves by pulling or building on demand.
    """
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, timeout=30, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def require_sandbox(image: str) -> None:
    """Fail closed. Never skip, never degrade to host execution."""
    if not docker_available():
        raise SandboxUnavailable(
            "the Docker daemon is unavailable, so agent-authored test code cannot be "
            "sandboxed; run_tests refuses to execute on the host"
        )
    if not image_present(image):
        raise SandboxUnavailable(
            f"sandbox image {image!r} is not present; build it with "
            f"ops/sandbox/build-images.sh (a provisioning step — the runtime never "
            f"builds or pulls images on demand)"
        )


def _ignore(_dir: str, names: list[str]) -> set[str]:
    skip = {n for n in names if n in EXCLUDED_FROM_COPY}
    skip |= {n for n in names if n.endswith(_EXCLUDED_SUFFIXES)}
    skip |= {n for n in names if n.startswith(".env")}
    return skip


def materialise_surface_copy(repo_root: Path, surface: Surface, destination: Path) -> Path:
    """Copy exactly one surface into a disposable directory.

    Only the named surface is copied, so a task cannot see another surface's
    source even by accident. Symlinks are not followed — a link pointing out of
    the tree is copied as a dangling link inside the sandbox, not as its target.
    """
    source = repo_root / surface.value
    if not source.is_dir():
        raise SandboxError(f"surface directory not found: {source}")

    destination.mkdir(parents=True, exist_ok=True)
    target = destination / surface.value
    shutil.copytree(source, target, ignore=_ignore, symlinks=True, dirs_exist_ok=False)
    return target


def run_in_sandbox(
    *,
    image: str,
    argv: tuple[str, ...],
    workdir_host: Path,
    limits: SandboxLimits,
    network: str = "none",
    env: dict[str, str] | None = None,
    container_workdir: str = "/work",
) -> SandboxResult:
    """Run `argv` in a locked-down container against `workdir_host`.

    `workdir_host` must be a disposable copy. Callers never pass the
    authoritative repository; :func:`assert_disposable` enforces that for the
    paths we can check.
    """
    name = f"agent-sbx-{uuid.uuid4().hex[:12]}"
    uid = os.getuid()
    gid = os.getgid()

    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", network,
        "--user", f"{uid}:{gid}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", str(limits.pids),
        "--memory", limits.memory,
        "--cpus", limits.cpus,
        # The disposable copy is the only host path the container can see.
        # No Docker socket, no host home, no repository, no ops/.
        "-v", f"{workdir_host}:{container_workdir}:rw",
        "-w", container_workdir,
        "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--env", "HOME=/tmp",
        "--env", "PATH=/usr/local/bin:/usr/bin:/bin",
    ]
    for key, value in (env or {}).items():
        cmd += ["--env", f"{key}={value}"]
    cmd += [image, *argv]

    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=limits.wall_clock_seconds, check=False,
        )
        exit_code = completed.returncode
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        output = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(
            exc.stdout, bytes
        ) else (exc.stdout or "")
        # The wall-clock bound is not advisory: kill the container, do not wait.
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)

    duration = time.monotonic() - started
    truncated = len(output) > limits.max_output_bytes
    if truncated:
        output = output[: limits.max_output_bytes] + "\n...[output truncated]"

    return SandboxResult(
        exit_code=exit_code, output=output, timed_out=timed_out,
        truncated=truncated, duration_seconds=duration,
    )


def assert_disposable(repo_root: Path, workdir: Path) -> None:
    """Refuse to run against the authoritative tree.

    Structurally the callers only ever build copies, but this makes the rule a
    checked invariant rather than a convention someone could break later.
    """
    resolved_repo = repo_root.resolve()
    resolved_work = workdir.resolve()
    if resolved_work == resolved_repo or resolved_repo in resolved_work.parents:
        raise SandboxError(
            f"refusing to run a sandbox against the authoritative repository: {resolved_work}"
        )


# --- isolated network for integration dependencies --------------------------

def create_isolated_network(prefix: str = "agent-net") -> str:
    """Create an `--internal` Docker network: containers on it can reach each
    other and nothing else. This is what gives integration tests a database
    without giving them the internet."""
    name = f"{prefix}-{uuid.uuid4().hex[:10]}"
    result = subprocess.run(
        ["docker", "network", "create", "--internal", name],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode != 0:
        raise SandboxError(f"could not create isolated network: {result.stderr.strip()}")
    return name


def remove_network(name: str) -> None:
    subprocess.run(["docker", "network", "rm", name], capture_output=True, check=False)


def start_postgres_dependency(network: str, password: str, image: str = "postgres:16-alpine") -> str:
    """Start a disposable PostgreSQL on the isolated network.

    The orchestrator does this — the test runner never gets the Docker socket
    and so cannot start anything itself.
    """
    name = f"agent-pg-{uuid.uuid4().hex[:10]}"
    result = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "--network", network,
            "--env", f"POSTGRES_PASSWORD={password}",
            "--env", "POSTGRES_DB=agent_test",
            image,
        ],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if result.returncode != 0:
        raise SandboxError(f"could not start postgres dependency: {result.stderr.strip()}")
    return name


#: Credentials and database the disposable dependency is created with. Readiness must be
#: checked against *these*, not against the server's default database.
POSTGRES_DEPENDENCY_USER = "postgres"
POSTGRES_DEPENDENCY_DB = "agent_test"

#: Bounded readiness gate. Deadline-based, polled — never an unbounded loop, never a fixed sleep.
READINESS_TIMEOUT_SECONDS = 60.0
READINESS_POLL_SECONDS = 1.0
#: Consecutive successful queries required before the database is called ready.
#:
#: One success is not sufficient. The official postgres entrypoint starts a *temporary* server
#: to run initdb and create POSTGRES_DB, serves connections on it, then shuts it down and starts
#: the real server. A probe landing in that window succeeds, and the next client sees
#: "FATAL: the database system is starting up". Requiring three successes spaced by the poll
#: interval spans the restart. Three is the smallest streak that covers the observed failure.
READINESS_CONSECUTIVE_OK = 3


def wait_for_postgres(
    container: str,
    *,
    user: str = POSTGRES_DEPENDENCY_USER,
    database: str = POSTGRES_DEPENDENCY_DB,
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
    poll_seconds: float = READINESS_POLL_SECONDS,
    consecutive_ok: int = READINESS_CONSECUTIVE_OK,
) -> bool:
    """Block until the disposable database can actually answer a query, or fail.

    **Process readiness is not database readiness.** This previously polled
    `pg_isready -U postgres`, which reports that *a* server is accepting connections — including
    the entrypoint's temporary initialisation server, and without regard to whether the target
    database exists. Integration runs were therefore started against a server that was about to
    restart. CI surfaced it as `FATAL: the database system is starting up`.

    Readiness now means: the container is reachable, `database` exists, and a real `SELECT`
    against it succeeds, repeatedly enough to prove the initialisation transition is over.

    The probe runs over the container's local socket, so **no password appears in any argv** —
    putting one there would leak it into the host process list, a worse exposure than the gap it
    would close. Password authentication is exercised immediately afterwards by the integration
    run itself, which connects over TCP with the generated credential.

    Raises :class:`SandboxError` on timeout, naming the container, the database, the bound
    applied and the last probe error. Returns True on success, so existing truthiness checks
    keep working.
    """
    deadline = time.monotonic() + timeout_seconds
    streak = 0
    last_error = "no probe completed"

    while time.monotonic() < deadline:
        probe = subprocess.run(
            ["docker", "exec", container,
             "psql", "-U", user, "-d", database, "-tAc", "select 1"],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if probe.returncode == 0 and (probe.stdout or "").strip() == "1":
            streak += 1
            if streak >= consecutive_ok:
                return True
        else:
            streak = 0
            detail = ((probe.stderr or "") + (probe.stdout or "")).strip().splitlines()
            last_error = detail[-1] if detail else f"exit {probe.returncode}"
        time.sleep(poll_seconds)

    # Deliberately no `docker logs` here. The runtime's docker subcommand set is an enforced
    # minimum (`test_runtime_docker_subcommands_are_the_expected_minimum`), and adding an eighth
    # verb to improve an error message is not a trade the boundary should make silently. The
    # probe's own last error is the diagnosis, and it is the same line the server would log.
    raise SandboxError(
        f"disposable postgres {container!r} did not become query-ready for database "
        f"{database!r} within {timeout_seconds:g}s "
        f"(needed {consecutive_ok} consecutive successful queries, polling every "
        f"{poll_seconds:g}s; last probe error: {last_error!r})"
    )


def stop_container(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
