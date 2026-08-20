"""Per-turn approval interception (T054, FR-043).

A checkpoint-crossing tool call is halted *before* it is applied — the run
enters WAITING_FOR_HUMAN and nothing is written. This is the difference between
gating a change and undoing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agent.allowlist import CHECKPOINT_FILES
from src.agent.errors import CheckpointCrossing


@dataclass(frozen=True, slots=True)
class PendingApproval:
    task_id: str
    tool_name: str
    reason: str
    detail: dict[str, Any]


@dataclass(slots=True)
class ApprovalHook:
    task_id: str
    pending: list[PendingApproval] = field(default_factory=list)

    def inspect(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """Raise before the handler runs if this call crosses a checkpoint."""
        if tool_name != "write_file":
            return
        path = str(tool_input.get("path", ""))
        name = path.rsplit("/", 1)[-1]
        if name in CHECKPOINT_FILES:
            reason = (
                f"writing {path!r} changes dependencies or build configuration, which is an "
                f"architecture decision requiring human approval (FR-029, FR-043)"
            )
            self.pending.append(
                PendingApproval(self.task_id, tool_name, reason, {"path": path})
            )
            raise CheckpointCrossing(reason)

    @property
    def has_pending(self) -> bool:
        return bool(self.pending)
