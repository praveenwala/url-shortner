"""Decomposition into task nodes (T038, FR-021, FR-035, FR-042)."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.intake import Requirement
from src.models.states import ExecutionMode, NodeState, Surface


@dataclass(slots=True)
class TaskNode:
    id: str
    description: str
    requirement_ref: str
    execution_mode: ExecutionMode
    surface: Surface
    depends_on: list[str] = field(default_factory=list)
    is_sync: bool = False
    state: NodeState = NodeState.PENDING
    is_stale: bool = False
    attempt_count: int = 0
    timeout_seconds: int = 60
    max_attempts: int = 3
    backoff_seconds: int = 2
    result: dict | None = None

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
