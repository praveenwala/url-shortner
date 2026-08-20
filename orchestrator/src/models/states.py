"""Run and node state model (research.md R7, FR-025).

The state sets are closed and named so that persistence (FR-025) and audit
(FR-036) have something testable to record. Staleness is deliberately NOT a
state: it is an orthogonal flag, so a stale-but-succeeded node keeps the result
replanning may still consult (FR-033).
"""

from enum import StrEnum


class RunState(StrEnum):
    PLANNING = "PLANNING"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    EXECUTING = "EXECUTING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SAFE_STOPPED = "SAFE_STOPPED"
    ABANDONED = "ABANDONED"


TERMINAL_RUN_STATES: frozenset[RunState] = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.SAFE_STOPPED, RunState.ABANDONED}
)

# WAITING_FOR_HUMAN never transitions to anything autonomously: only a recorded
# human response moves it (FR-049). It is reachable from EXECUTING and PLANNING
# and returns only to the state that was waiting.
# Principle VII: a safe-stop halts execution and escalates. It must therefore be
# reachable from *every* non-terminal state — a run that cannot stop safely because
# of where it happens to be is exactly the failure the principle prohibits. This was
# corrected during US3, when a clarification budget exhausted while WAITING_FOR_HUMAN
# had nowhere to go.
ALLOWED_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PLANNING: frozenset(
        {RunState.AWAITING_PLAN_APPROVAL, RunState.WAITING_FOR_HUMAN, RunState.FAILED,
         RunState.SAFE_STOPPED, RunState.ABANDONED}
    ),
    RunState.AWAITING_PLAN_APPROVAL: frozenset(
        {RunState.EXECUTING, RunState.WAITING_FOR_HUMAN, RunState.ABANDONED,
         RunState.FAILED, RunState.SAFE_STOPPED}
    ),
    RunState.EXECUTING: frozenset(
        {RunState.WAITING_FOR_HUMAN, RunState.REPLANNING, RunState.COMPLETED,
         RunState.FAILED, RunState.SAFE_STOPPED, RunState.ABANDONED}
    ),
    RunState.WAITING_FOR_HUMAN: frozenset(
        {RunState.PLANNING, RunState.EXECUTING, RunState.REPLANNING, RunState.ABANDONED,
         RunState.SAFE_STOPPED}
    ),
    RunState.REPLANNING: frozenset(
        {RunState.EXECUTING, RunState.WAITING_FOR_HUMAN, RunState.FAILED,
         RunState.ABANDONED, RunState.SAFE_STOPPED}
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.SAFE_STOPPED: frozenset(),
    RunState.ABANDONED: frozenset(),
}


class NodeState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    SKIPPED = "SKIPPED"


TERMINAL_NODE_STATES: frozenset[NodeState] = frozenset(
    {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.ROLLED_BACK, NodeState.SKIPPED}
)

ALLOWED_NODE_TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.READY, NodeState.SKIPPED}),
    NodeState.READY: frozenset({NodeState.RUNNING, NodeState.SKIPPED}),
    NodeState.RUNNING: frozenset({NodeState.SUCCEEDED, NodeState.FAILED}),
    NodeState.SUCCEEDED: frozenset({NodeState.ROLLED_BACK}),
    NodeState.FAILED: frozenset({NodeState.READY, NodeState.ROLLED_BACK}),  # bounded retry
    NodeState.ROLLED_BACK: frozenset(),
    NodeState.SKIPPED: frozenset(),
}


class ExecutionMode(StrEnum):
    """Declared at planning time; never escalated during execution (FR-042)."""

    AGENT_AUTHORED = "agent_authored"
    HUMAN_EXECUTED = "human_executed"


class Surface(StrEnum):
    """Scopes an agent's write allow-list to one language surface (R6)."""

    SHORTENER = "shortener"
    ORCHESTRATOR = "orchestrator"
    CONSOLE = "console"


class GateKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


class GateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class InvalidTransition(Exception):
    """Raised when a transition outside the declared state model is attempted."""


def check_run_transition(current: RunState, target: RunState) -> None:
    if target not in ALLOWED_RUN_TRANSITIONS[current]:
        raise InvalidTransition(f"run: {current} -> {target} is not an allowed transition")


def check_node_transition(current: NodeState, target: NodeState) -> None:
    if target not in ALLOWED_NODE_TRANSITIONS[current]:
        raise InvalidTransition(f"node: {current} -> {target} is not an allowed transition")


def is_escalation(declared: ExecutionMode, attempted: ExecutionMode) -> bool:
    """FR-042: human_executed -> agent_authored is escalation and is forbidden."""
    return declared is ExecutionMode.HUMAN_EXECUTED and attempted is ExecutionMode.AGENT_AUTHORED
