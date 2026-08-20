"""Decomposition into task nodes (T038, FR-021, FR-035, FR-041, FR-042).

Declared inputs and outputs are populated here, at planning time, and frozen.
This is what lets the bounded agent runtime derive a write allow-list from the
task rather than from the whole surface: FR-041 permits agent authorship only
where the interface is *already approved*, and an output set that an agent could
widen mid-run would not be an approved interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.intake import Requirement
from src.models.states import ExecutionMode, NodeState, Surface

SURFACE_ROOTS: dict[Surface, str] = {
    Surface.SHORTENER: "shortener/",
    Surface.ORCHESTRATOR: "orchestrator/",
    Surface.CONSOLE: "console/",
}

# Fixed at planning time and never reassignable on a live node. Changing any of
# these is a replanning decision, not an execution-time adjustment (FR-033,
# FR-042). Mutable execution fields — state, attempt_count, is_stale, result —
# are deliberately absent.
FROZEN_AFTER_PLANNING: frozenset[str] = frozenset(
    {
        "id",
        "requirement_ref",
        "execution_mode",
        "surface",
        "declared_inputs",
        "declared_outputs",
        "is_sync",
        "supersedes",
    }
)


@dataclass(slots=True)
class TaskNode:
    id: str
    description: str
    requirement_ref: str
    execution_mode: ExecutionMode
    surface: Surface
    depends_on: list[str] = field(default_factory=list)
    declared_inputs: tuple[str, ...] = ()
    declared_outputs: tuple[str, ...] = ()
    is_sync: bool = False
    #: The node this one replaces after a selective replan (FR-033). The superseded
    #: node keeps its state and result; this is a link, not a deletion.
    supersedes: str | None = None
    state: NodeState = NodeState.PENDING
    is_stale: bool = False
    attempt_count: int = 0
    timeout_seconds: int = 60
    max_attempts: int = 3
    backoff_seconds: int = 2
    result: dict | None = None
    _frozen: bool = field(default=False, repr=False, compare=False)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False) and name in FROZEN_AFTER_PLANNING:
            raise OrchestratorError(
                f"task {self.id!r}: {name} is fixed at planning time and cannot be "
                f"changed during execution; widening it requires replanning",
                ErrorCode.MODE_ESCALATION,
            )
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        if not self.requirement_ref or not self.requirement_ref.strip():
            # FR-035: a task with no traceable requirement is out of scope.
            raise OrchestratorError(
                f"task {self.id!r} has no requirement reference",
                ErrorCode.MISSING_REQUIREMENT_REF,
            )
        if self.max_attempts < 1:
            # Principle VII: bounds are declared before the operation runs.
            raise OrchestratorError(
                f"task {self.id!r} must declare at least one attempt", ErrorCode.INVALID_REQUEST
            )

        # Normalise to tuples so the sequences cannot be appended to in place.
        object.__setattr__(self, "declared_inputs", tuple(self.declared_inputs))
        object.__setattr__(self, "declared_outputs", tuple(self.declared_outputs))

        for path in self.declared_inputs:
            _validate_artifact_path(self.id, self.surface, path, kind="input")
        for path in self.declared_outputs:
            _validate_artifact_path(self.id, self.surface, path, kind="output")

        if len(set(self.declared_outputs)) != len(self.declared_outputs):
            raise OrchestratorError(
                f"task {self.id!r} declares a duplicate output", ErrorCode.INVALID_REQUEST
            )

        # FR-041: an agent-authored task must state what it will produce, or the
        # write allow-list derived from it would be unbounded. A sync node
        # performs no work and produces nothing.
        if (
            self.execution_mode is ExecutionMode.AGENT_AUTHORED
            and not self.is_sync
            and not self.declared_outputs
        ):
            raise OrchestratorError(
                f"task {self.id!r} is agent-authored but declares no outputs",
                ErrorCode.MISSING_REQUIREMENT_REF,
            )
        if self.is_sync and self.declared_outputs:
            raise OrchestratorError(
                f"sync node {self.id!r} must not declare outputs", ErrorCode.INVALID_REQUEST
            )

        object.__setattr__(self, "_frozen", True)

    @property
    def write_allowlist(self) -> tuple[str, ...]:
        """The write allow-list the bounded agent runtime derives from this task.

        It is exactly the declared outputs — never the surface, never the
        declared inputs. A task may read a module it must not modify.
        """
        return self.declared_outputs


def decompose(requirement: Requirement, nodes: list[TaskNode]) -> list[TaskNode]:
    """FR-021. Refuses to produce tasks for an uninterpreted requirement (FR-020),
    or for one whose ambiguities have not been resolved (FR-028)."""
    if not requirement.is_interpreted:
        raise OrchestratorError(
            "cannot decompose before an interpretation is recorded", ErrorCode.INVALID_REQUEST
        )
    if requirement.blocking_ambiguities:
        raise OrchestratorError(
            "cannot decompose while ambiguities are unresolved", ErrorCode.INVALID_REQUEST
        )
    if not nodes:
        raise OrchestratorError("decomposition produced no tasks", ErrorCode.INVALID_REQUEST)

    # FR-021/FR-041: every agent-authored task leaves decomposition with an
    # explicit output set. TaskNode enforces this per node; re-stating it here
    # makes the planner's contract explicit at its boundary, and catches a node
    # that was constructed elsewhere and handed in.
    for node in nodes:
        if (
            node.execution_mode is ExecutionMode.AGENT_AUTHORED
            and not node.is_sync
            and not node.declared_outputs
        ):
            raise OrchestratorError(
                f"decomposition produced agent-authored task {node.id!r} with no declared "
                f"outputs; the write allow-list would be unbounded",
                ErrorCode.MISSING_REQUIREMENT_REF,
            )
    return nodes


def assert_no_mode_escalation(declared: dict[str, ExecutionMode], node: TaskNode) -> None:
    """FR-042: mode is fixed at planning time; human_executed can never become
    agent_authored during execution."""
    original = declared.get(node.id)
    if original is None:
        return
    if original is ExecutionMode.HUMAN_EXECUTED and node.execution_mode is ExecutionMode.AGENT_AUTHORED:
        raise OrchestratorError(
            f"task {node.id!r} escalated from human_executed to agent_authored",
            ErrorCode.MODE_ESCALATION,
        )


def _validate_artifact_path(task_id: str, surface: Surface, path: str, *, kind: str) -> None:
    """Declared inputs and outputs must be explicit, repo-relative artifact paths
    inside the task's own surface.

    Rejecting absolute paths, traversal, and wildcards here means the bounded
    agent runtime can treat the declared set as trustworthy rather than
    re-deriving safety at every tool call.
    """
    if not path or not path.strip():
        raise OrchestratorError(
            f"task {task_id!r} declares an empty {kind} path", ErrorCode.INVALID_REQUEST
        )
    if path != path.strip():
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} has surrounding whitespace",
            ErrorCode.INVALID_REQUEST,
        )
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} must be repo-relative, not absolute",
            ErrorCode.INVALID_REQUEST,
        )
    if "\\" in path:
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} must use forward slashes",
            ErrorCode.INVALID_REQUEST,
        )
    if any(ch in path for ch in ("*", "?", "[", "]")):
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} must be an explicit path, not a pattern",
            ErrorCode.INVALID_REQUEST,
        )
    if ".." in PurePosixPath(path).parts:
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} must not traverse upwards",
            ErrorCode.INVALID_REQUEST,
        )
    if path.endswith("/"):
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} must be a file, not a directory",
            ErrorCode.INVALID_REQUEST,
        )

    root = SURFACE_ROOTS[surface]
    if not path.startswith(root):
        raise OrchestratorError(
            f"task {task_id!r} {kind} path {path!r} is outside its surface root {root!r}",
            ErrorCode.INVALID_REQUEST,
        )


def replan_outputs(node: TaskNode, declared_outputs: tuple[str, ...]) -> TaskNode:
    """Produce a replacement node with a different output set (FR-033).

    Outputs cannot be widened in place — that is what makes the write allow-list
    trustworthy. Replanning therefore *replaces* the node, leaving the original
    intact for the audit trail, and the replacement starts from PENDING.
    """
    return TaskNode(
        id=node.id,
        description=node.description,
        requirement_ref=node.requirement_ref,
        execution_mode=node.execution_mode,
        surface=node.surface,
        depends_on=list(node.depends_on),
        declared_inputs=node.declared_inputs,
        declared_outputs=declared_outputs,
        is_sync=node.is_sync,
        timeout_seconds=node.timeout_seconds,
        max_attempts=node.max_attempts,
        backoff_seconds=node.backoff_seconds,
    )
