"""Bounded-task dispatch: preconditions, tier A/B/C handling, safe-stop (T055).

Tier A refuses to dispatch at all. Tier B refuses one call and tells the agent.
Tier C halts before apply and waits for a human. Exceeding the violation budget,
the attempt cap, or the wall clock escalates to safe-stop — never a further try.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.approval_hook import ApprovalHook
from src.agent.errors import (
    CheckpointCrossing,
    PreconditionFailed,
    SafeStop,
    SandboxUnavailable,
    ToolViolation,
)
from src.agent.tools import HANDLERS, ToolContext
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, RunState

MAX_VIOLATIONS_PER_DISPATCH = 3

#: FR-041's four preconditions. A task missing any one is not bounded.
REQUIRED_APPROVALS: tuple[str, ...] = (
    "interface", "acceptance_criteria", "dependencies", "security_constraints"
)


@dataclass(frozen=True, slots=True)
class BoundedTask:
    node: TaskNode
    approvals: frozenset[str]


@dataclass(slots=True)
class DispatchOutcome:
    completed: bool
    violations: int = 0
    safe_stopped: bool = False
    awaiting_human: bool = False
    reason: str = ""
    results: list[str] = field(default_factory=list)
    audit: list[tuple[str, str]] = field(default_factory=list)

    def record(self, event_type: str, detail: str) -> None:
        self.audit.append((event_type, detail))


def assert_dispatchable(task: BoundedTask) -> None:
    """Tier A. Raises before any model call is made."""
    node = task.node
    if node.execution_mode is not ExecutionMode.AGENT_AUTHORED:
        raise PreconditionFailed(
            f"task {node.id!r} is {node.execution_mode.value}; only agent-authored tasks "
            f"may be dispatched to an agent (FR-042)"
        )
    if node.is_sync:
        raise PreconditionFailed(f"task {node.id!r} is a synchronisation node; nothing to author")
    if not node.declared_outputs:
        raise PreconditionFailed(
            f"task {node.id!r} declares no outputs; the write allow-list would be unbounded"
        )
    missing = [name for name in REQUIRED_APPROVALS if name not in task.approvals]
    if missing:
        raise PreconditionFailed(
            f"task {node.id!r} is not bounded: {', '.join(missing)} not approved (FR-041)"
        )


@dataclass(slots=True)
class Dispatcher:
    """Executes one bounded task's tool calls under the tier A/B/C rules.

    The model turn itself is injected as `next_calls`, so workflow and
    failure-path tests drive it deterministically without a provider.
    """

    repo_root: Path
    task: BoundedTask
    limits_seconds: int = 120
    image_override: str | None = None
    on_audit: Callable[[str, str], None] | None = None
    # Checkpoint 2e wiring. Optional so 2d's unit-level tests still construct a
    # dispatcher with no database behind it.
    run_id: str | None = None
    state_store: Any = None
    approvals: Any = None
    audit: Any = None
    hook: ApprovalHook = field(init=False)
    context: ToolContext = field(init=False)

    def __post_init__(self) -> None:
        self.hook = ApprovalHook(task_id=self.task.node.id)
        self.context = ToolContext(
            repo_root=self.repo_root, task=self.task.node,
            image_override=self.image_override,
        )

    def run(self, next_calls: Callable[[list[str]], list[tuple[str, dict[str, Any]]]]
            ) -> DispatchOutcome:
        assert_dispatchable(self.task)

        outcome = DispatchOutcome(completed=False)
        started = time.monotonic()
        feedback: list[str] = []

        while True:
            if time.monotonic() - started > self.limits_seconds:
                outcome.safe_stopped = True
                outcome.reason = "wall-clock ceiling exceeded"
                self._audit(outcome, "SAFE_STOP_WALL_CLOCK", outcome.reason)
                return outcome

            calls = next_calls(feedback)
            if not calls:
                outcome.reason = "agent produced no further calls"
                return outcome

            feedback = []
            for name, payload in calls:
                if name not in HANDLERS:
                    outcome.violations += 1
                    feedback.append(f"{name}: no such tool")
                    continue
                try:
                    self.hook.inspect(name, payload)
                    result = HANDLERS[name](self.context, **payload)
                except SandboxUnavailable as exc:
                    # The boundary itself is missing. Not a tool mistake to
                    # retry and not something to run on the host: safe-stop,
                    # preserve state, record why (FR-031, R15).
                    outcome.safe_stopped = True
                    outcome.reason = f"sandbox unavailable: {exc}"
                    self._audit(outcome, "SAFE_STOP_SANDBOX_UNAVAILABLE", str(exc))
                    return outcome
                except CheckpointCrossing as exc:
                    # Tier C: nothing applied, run waits for a human. The order
                    # matters — the approval request and the WAITING_FOR_HUMAN
                    # transition happen because the write did *not*.
                    outcome.awaiting_human = True
                    outcome.reason = str(exc)
                    self._raise_checkpoint(name, payload, str(exc))
                    self._audit(outcome, "AWAITING_HUMAN_CHECKPOINT", str(exc))
                    self._park_run()
                    return outcome
                except ToolViolation as exc:
                    # Tier B: refuse this call, tell the agent, keep going.
                    outcome.violations += 1
                    feedback.append(f"{name}: {exc}")
                    self._audit(outcome, "TOOL_VIOLATION", f"{name}: {exc}")
                    if outcome.violations > MAX_VIOLATIONS_PER_DISPATCH:
                        outcome.safe_stopped = True
                        outcome.reason = (
                            f"{outcome.violations} tool violations in one dispatch"
                        )
                        self._audit(outcome, "SAFE_STOP_VIOLATION_BUDGET", outcome.reason)
                        return outcome
                    continue

                outcome.results.append(result)
                if name == "report":
                    outcome.completed = True
                    outcome.reason = result
                    return outcome


    def _audit(self, outcome: DispatchOutcome, event_type: str, detail: str) -> None:
        outcome.record(event_type, detail)
        if self.on_audit is not None:
            self.on_audit(event_type, detail)
        if self.audit is not None and self.run_id is not None:
            from src.trace.correlation import Correlation

            self.audit.append(
                Correlation(run_id=self.run_id, actor=f"agent:{self.task.node.id}"),
                event_type,
                {"task_id": self.task.node.id, "detail": detail},
            )

    def _raise_checkpoint(self, tool_name: str, payload: dict[str, Any], reason: str) -> None:
        """Surface the halted action as a pending approval (FR-029, FR-043)."""
        if self.approvals is None or self.run_id is None:
            return
        from src.engine.approvals import Checkpoint

        self.approvals.request(
            run_id=self.run_id,
            checkpoint=Checkpoint.ARCHITECTURE,
            detail={"action": tool_name, **payload_without_content(payload),
                    "reason": reason},
            requested_by=f"agent:{self.task.node.id}",
        )

    def _park_run(self) -> None:
        if self.state_store is None or self.run_id is None:
            return
        current = self.state_store.run_state(self.run_id)
        if current is RunState.WAITING_FOR_HUMAN:
            return
        self.state_store.transition_run(self.run_id, RunState.WAITING_FOR_HUMAN,
                                        waiting_on="approval")
        if self.audit is not None:
            from src.trace.correlation import Correlation

            self.audit.append(
                Correlation(run_id=self.run_id, actor="orchestrator"),
                "RUN_STATE_CHANGED",
                {"from": str(current), "to": str(RunState.WAITING_FOR_HUMAN)},
            )


def payload_without_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Approval details name the action, not the whole proposed file body."""
    return {k: v for k, v in payload.items() if k != "content"}


def safe_stop(reason: str) -> SafeStop:
    return SafeStop(f"safe-stop: {reason}")
