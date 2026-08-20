"""Per-task read and write allow-lists (T051, FR-041, R6).

Containment is checked on the *resolved* path, never on the string the agent
supplied — a symlink inside a surface pointing at `ops/` or `/etc/passwd`
resolves outside the root and is refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.agent.errors import CheckpointCrossing, ToolViolation
from src.engine.decompose import SURFACE_ROOTS, TaskNode
from src.models.states import Surface

MAX_READ_BYTES = 1024 * 1024
MAX_PATH_LENGTH = 4096

#: Always denied, whatever the surface says. Governance, operations, secrets.
DENIED_PREFIXES: tuple[str, ...] = (
    ".git/", ".github/", "ops/", ".specify/", "specs/",
    ".venv/", "venv/", "node_modules/", "target/",
)
DENIED_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".keystore")
DENIED_NAMES: frozenset[str] = frozenset({".env", ".netrc", ".npmrc", "id_rsa"})

#: Writable only through an approval checkpoint — editing a dependency manifest
#: is how an agent would introduce a service or a library (FR-041).
CHECKPOINT_FILES: frozenset[str] = frozenset(
    {"pom.xml", "pyproject.toml", "package.json", "package-lock.json", "requirements.txt"}
)

WRITABLE_SUFFIXES: dict[Surface, frozenset[str]] = {
    Surface.SHORTENER: frozenset({".java", ".xml", ".yaml", ".yml", ".sql", ".properties"}),
    Surface.ORCHESTRATOR: frozenset({".py", ".sql", ".toml"}),
    Surface.CONSOLE: frozenset({".ts", ".tsx", ".json", ".css"}),
}


@dataclass(frozen=True, slots=True)
class PathPolicy:
    repo_root: Path
    task: TaskNode

    # -- shared checks -------------------------------------------------------
    def _resolve(self, raw: str) -> tuple[Path, str]:
        if not raw or "\x00" in raw or len(raw) > MAX_PATH_LENGTH:
            raise ToolViolation(f"invalid path: {raw[:80]!r}")
        resolved = (self.repo_root / raw).resolve(strict=False)
        try:
            relative = resolved.relative_to(self.repo_root.resolve())
        except ValueError:
            raise ToolViolation(
                f"path {raw!r} resolves outside the repository"
            ) from None
        return resolved, relative.as_posix()

    def _deny_overlay(self, relative: str) -> None:
        if any(relative.startswith(p) for p in DENIED_PREFIXES):
            raise ToolViolation(f"path {relative!r} is in a denied tree")
        if relative.endswith(DENIED_SUFFIXES):
            raise ToolViolation(f"path {relative!r} has a denied extension")
        name = relative.rsplit("/", 1)[-1]
        if name in DENIED_NAMES or name.startswith(".env"):
            raise ToolViolation(f"path {relative!r} is a denied file")

    def _surface_containment(self, relative: str) -> None:
        root = SURFACE_ROOTS[self.task.surface]
        if not relative.startswith(root):
            raise ToolViolation(
                f"path {relative!r} is outside this task's surface root {root!r}"
            )

    # -- read ----------------------------------------------------------------
    def resolve_read(self, raw: str) -> Path:
        resolved, relative = self._resolve(raw)
        self._deny_overlay(relative)
        self._surface_containment(relative)
        if resolved.is_dir():
            raise ToolViolation(f"path {relative!r} is a directory")
        if resolved.exists() and not resolved.is_file():
            raise ToolViolation(f"path {relative!r} is not a regular file")
        if resolved.exists() and resolved.stat().st_size > MAX_READ_BYTES:
            raise ToolViolation(f"path {relative!r} exceeds the {MAX_READ_BYTES} byte read cap")
        return resolved

    # -- write ---------------------------------------------------------------
    def resolve_write(self, raw: str) -> Path:
        resolved, relative = self._resolve(raw)
        self._deny_overlay(relative)
        self._surface_containment(relative)

        name = relative.rsplit("/", 1)[-1]
        if name in CHECKPOINT_FILES:
            # Tier C: not a mistake to correct, a decision a human must make.
            raise CheckpointCrossing(
                f"writing {relative!r} would change dependencies or build configuration; "
                f"this requires human approval before it is applied"
            )

        if relative not in self.task.declared_outputs:
            raise ToolViolation(
                f"path {relative!r} is not a declared output of task {self.task.id!r}; "
                f"declared outputs are {list(self.task.declared_outputs)}"
            )
        if resolved.suffix not in WRITABLE_SUFFIXES[self.task.surface]:
            raise ToolViolation(
                f"path {relative!r} has an extension not writable on this surface"
            )
        if not resolved.parent.is_dir():
            raise ToolViolation(
                f"parent directory of {relative!r} does not exist; the runtime never "
                f"creates directories"
            )
        return resolved

    @property
    def write_allowlist(self) -> tuple[str, ...]:
        return self.task.declared_outputs
