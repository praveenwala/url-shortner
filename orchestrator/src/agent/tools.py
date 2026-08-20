"""The four model-visible tools (T051, FR-041, R6).

There is no fifth tool. The FR-041 prohibitions hold because nothing here
reaches them: an agent cannot introduce a datastore with no tool that installs
or configures one, and cannot release with no tool that builds or deploys.

`run_tests` takes an enum, never a command. Its execution happens in an
ephemeral container (R15), because bounding the tool surface does not bound
code the agent itself wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.agent.allowlist import PathPolicy
from src.agent.changes import ChangeRecord, apply_write
from src.agent.errors import ToolViolation
from src.agent.sandbox import SandboxLimits
from src.agent.testrunner import TestLayer, TestRunRequest, run_tests
from src.engine.decompose import TaskNode
from src.trace.correlation import now

TOOL_NAMES: tuple[str, ...] = ("read_file", "write_file", "run_tests", "report")


def tool_schemas() -> list[dict[str, Any]]:
    """Declared to the model. `strict` + `additionalProperties: false` means a
    malformed or extended input is rejected before a handler sees it."""
    return [
        {
            "name": "read_file",
            "description": "Read one text file inside this task's read allow-list.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "write_file",
            "description": "Replace one file. Only this task's declared outputs are writable.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        {
            "name": "run_tests",
            "description": (
                "Run this surface's test suite in an isolated sandbox. "
                "No command, path, host, or container option can be supplied."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "enum": [layer.value for layer in TestLayer]}
                },
                "required": ["layer"],
                "additionalProperties": False,
            },
        },
        {
            "name": "report",
            "description": "Return findings and end the turn.",
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "status": {"type": "string", "enum": ["complete", "blocked"]},
                },
                "required": ["summary", "status"],
                "additionalProperties": False,
            },
        },
    ]


@dataclass(slots=True)
class ToolContext:
    repo_root: Path
    task: TaskNode
    limits: SandboxLimits = SandboxLimits()
    changes: list[ChangeRecord] = None  # type: ignore[assignment]
    image_override: str | None = None
    on_change: Callable[[ChangeRecord], None] | None = None

    def __post_init__(self) -> None:
        if self.changes is None:
            self.changes = []

    @property
    def policy(self) -> PathPolicy:
        return PathPolicy(repo_root=self.repo_root, task=self.task)


def handle_read_file(ctx: ToolContext, path: str) -> str:
    resolved = ctx.policy.resolve_read(path)
    if not resolved.exists():
        raise ToolViolation(f"{path!r} does not exist")
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolViolation(f"{path!r} is not UTF-8 text") from exc


def handle_write_file(ctx: ToolContext, path: str, content: str) -> str:
    resolved = ctx.policy.resolve_write(path)
    relative = resolved.relative_to(ctx.repo_root.resolve()).as_posix()
    record = apply_write(
        path=resolved, content=content, task_id=ctx.task.id,
        surface=ctx.task.surface.value, execution_mode=ctx.task.execution_mode.value,
        relative_path=relative, now_iso=now().isoformat(),
    )
    ctx.changes.append(record)
    if ctx.on_change is not None:
        ctx.on_change(record)
    return f"wrote {relative} ({len(content)} bytes)"


def handle_run_tests(ctx: ToolContext, layer: str) -> str:
    try:
        parsed = TestLayer(layer)
    except ValueError as exc:
        raise ToolViolation(f"unknown test layer {layer!r}") from exc
    result = run_tests(
        TestRunRequest(
            repo_root=ctx.repo_root, surface=ctx.task.surface, layer=parsed,
            limits=ctx.limits, image_override=ctx.image_override,
        )
    )
    verdict = "passed" if result.passed else ("timed out" if result.timed_out else "failed")
    return f"tests {verdict} (exit {result.exit_code})\n{result.output}"


def handle_report(ctx: ToolContext, summary: str, status: str) -> str:
    return f"[{status}] {summary}"


HANDLERS: dict[str, Callable[..., str]] = {
    "read_file": handle_read_file,
    "write_file": handle_write_file,
    "run_tests": handle_run_tests,
    "report": handle_report,
}
