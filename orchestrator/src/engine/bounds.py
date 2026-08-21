"""Bounded execution policy for automated operations (T090, FR-030, FR-031).

Principle VII in one object: every automated operation declares a timeout, a maximum attempt
count, a backoff, and a fallback **before it runs**, and nothing it does while running can
widen any of them.

Two design choices carry the guarantee:

* The policy is a frozen dataclass and is **never handed to the operation**. The callable
  receives an attempt number and nothing else, so there is no reference through which it could
  raise its own budget.
* Attempts are persisted *per attempt*, not at the end. A process that dies mid-retry resumes
  with the budget it had actually spent.

**Scope, and what this deliberately does not touch.** This governs *operations* — a unit of
work identified by a task node. It does not replace the bounds that already exist elsewhere and
are tested in their own right: the dispatcher's per-dispatch violation budget and wall-clock
ceiling, the sandbox's container wall-clock limit, the code generator's collision retry cap, or
the clarification round cap. Those bound different things; consolidating them would mean
rewriting working, tested code to no benefit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Engine

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.state import StateStore
from src.models.states import RunState
from src.obs import logging as olog
from src.store.repository import AuditRepository
from src.trace.correlation import Correlation


class FallbackAction(StrEnum):
    SAFE_STOP = "safe_stop"
    WAIT_FOR_HUMAN = "wait_for_human"
    HANDLER = "handler"


class RetriesExhausted(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class UndeclaredFallback(OrchestratorError):
    """A fallback that was not declared in the policy cannot be invented after failure."""

    code = ErrorCode.FORBIDDEN


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    fallback: FallbackAction
    #: Required when `fallback` is HANDLER. The name must be registered on the
    #: executor before dispatch — see `UndeclaredFallback`.
    fallback_handler: str | None = None
    #: Backoff never grows past this, whatever the attempt count.
    max_backoff_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise OrchestratorError("max_attempts must be at least 1",
                                    ErrorCode.INVALID_REQUEST)
        if self.timeout_seconds <= 0:
            raise OrchestratorError("timeout_seconds must be positive",
                                    ErrorCode.INVALID_REQUEST)
        if self.backoff_seconds < 0:
            raise OrchestratorError("backoff_seconds must not be negative",
                                    ErrorCode.INVALID_REQUEST)
        if self.fallback is FallbackAction.HANDLER and not self.fallback_handler:
            raise OrchestratorError("a HANDLER fallback must name its handler",
                                    ErrorCode.INVALID_REQUEST)


def backoff_delays(policy: OperationPolicy) -> list[float]:
    """The full wait schedule, computable before anything runs.

    Exponential but capped: doubling forever is unbounded retry wearing a hat, and a
    schedule you cannot state in advance is one nobody can reason about.
    """
    delays: list[float] = []
    for attempt in range(1, policy.max_attempts):
        delays.append(min(policy.backoff_seconds * (2 ** (attempt - 1)),
                          policy.max_backoff_seconds))
    return delays


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation_id: str
    succeeded: bool
    attempts: int
    result: Any = None


class BoundedExecutor:
    """Runs one operation under a policy, or fails within its declared bounds."""

    def __init__(self, engine: Engine, run_id: str, *, stop_after: int | None = None) -> None:
        self._engine = engine
        self._run_id = run_id
        self._state = StateStore(engine)
        self._audit = AuditRepository(engine)
        self._fallbacks: dict[str, Callable[[str], None]] = {}
        #: Test seam: simulates a process dying after N attempts. Never used in
        #: normal operation, and it cannot extend a budget — only cut a run short.
        self._stop_after = stop_after

    def register_fallback(self, name: str, handler: Callable[[str], None]) -> None:
        self._fallbacks[name] = handler

    def run(self, operation_id: str, operation: Callable[[int], Any], *,
            policy: OperationPolicy) -> OperationOutcome:
        # Declared before dispatch, verified before anything executes: an unknown
        # handler is a policy error, not a runtime surprise discovered after failure.
        if (policy.fallback is FallbackAction.HANDLER
                and policy.fallback_handler not in self._fallbacks):
            raise UndeclaredFallback(
                f"fallback handler {policy.fallback_handler!r} is not declared; "
                f"a fallback cannot be invented after a failure"
            )

        already_spent = self._state.attempts_spent(operation_id)
        delays = backoff_delays(policy)
        attempts_this_process = 0

        while already_spent < policy.max_attempts:
            if self._stop_after is not None and attempts_this_process >= self._stop_after:
                break

            attempt = self._state.record_attempt(operation_id)
            already_spent = attempt
            attempts_this_process += 1
            self._emit("OPERATION_ATTEMPTED", operation_id,
                       {"attempt": attempt, "max_attempts": policy.max_attempts})

            outcome, failure = self._attempt(operation, attempt, policy.timeout_seconds)
            if failure is None and outcome:
                self._emit("OPERATION_SUCCEEDED", operation_id, {"attempt": attempt})
                return OperationOutcome(operation_id, True, attempt, outcome)

            self._emit(failure or "OPERATION_FAILED", operation_id,
                       {"attempt": attempt, "remaining": policy.max_attempts - attempt})

            if attempt < policy.max_attempts and attempt - 1 < len(delays):
                time.sleep(delays[attempt - 1])

        # Budget spent. The fallback was declared before the first attempt.
        self._fallback(operation_id, policy, already_spent)
        raise RetriesExhausted(
            f"operation {operation_id!r} exhausted {already_spent} of "
            f"{policy.max_attempts} attempts; declared fallback {policy.fallback} executed"
        )

    # -- internals -------------------------------------------------------------
    def _attempt(self, operation: Callable[[int], Any], attempt: int, timeout: float
                 ) -> tuple[Any, str | None]:
        """One attempt, bounded by its own timeout.

        The timeout bounds *waiting*, not the runaway work: Python cannot preempt a thread.
        Where the work is agent-authored and must actually be killed, the sandbox is the
        mechanism (research R15) — this is the in-process bound, and saying otherwise
        would overstate it.
        """
        # Deliberately not a context manager: `with ThreadPoolExecutor(...)` joins the
        # worker on exit, which would block for the full duration of the very operation
        # the timeout exists to stop waiting for. A fresh single-worker pool per attempt,
        # shut down without waiting, is what makes the bound real.
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(operation, attempt)
        try:
            result = future.result(timeout=timeout)
        except FutureTimeout:
            # The worker keeps running until the operation returns — Python cannot
            # preempt it. The *wait* is bounded; killing the work is the sandbox's job.
            pool.shutdown(wait=False, cancel_futures=True)
            return None, "OPERATION_TIMED_OUT"
        except Exception:  # noqa: BLE001 - a bounded operation must absorb ANY failure the
            # callable raises; narrowing this would let an unanticipated exception escape the
            # bound and bypass the declared fallback (Principle VII, FR-030/FR-031).
            pool.shutdown(wait=False, cancel_futures=True)
            return None, "OPERATION_FAILED"
        pool.shutdown(wait=False)
        return result, None

    def _fallback(self, operation_id: str, policy: OperationPolicy, attempts: int) -> None:
        olog.warn("fallback_selected", node_id=operation_id, attempt=attempts,
                  outcome=str(policy.fallback))
        self._emit("FALLBACK_EXECUTED", operation_id,
                   {"fallback": str(policy.fallback), "attempts": attempts})

        if policy.fallback is FallbackAction.SAFE_STOP:
            # State is preserved: the node, its attempt count, and the trail all remain.
            self._transition(RunState.SAFE_STOPPED)
            self._emit("SAFE_STOP_RETRIES_EXHAUSTED", operation_id, {"attempts": attempts})
        elif policy.fallback is FallbackAction.WAIT_FOR_HUMAN:
            self._transition(RunState.WAITING_FOR_HUMAN, waiting_on="operation failure")
            self._emit("WAIT_FOR_HUMAN_RETRIES_EXHAUSTED", operation_id,
                       {"attempts": attempts})
        else:
            self._fallbacks[policy.fallback_handler](operation_id)  # type: ignore[index]
            self._emit("FALLBACK_HANDLER_COMPLETED", operation_id,
                       {"handler": policy.fallback_handler})

    def _transition(self, target: RunState, waiting_on: str | None = None) -> None:
        current = self._state.run_state(self._run_id)
        if current is target:
            return
        self._state.transition_run(self._run_id, target, waiting_on=waiting_on)

    def _emit(self, event_type: str, operation_id: str, payload: dict[str, Any]) -> None:
        self._audit.append(
            Correlation(run_id=self._run_id, actor="orchestrator"),
            event_type, {"operation_id": operation_id, **payload},
        )
