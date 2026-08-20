"""T086 — bounded execution: timeout, bounded retry, declared fallback (FR-030, FR-031).

The rule these defend: every automated operation declares its bounds *before* it runs, and
nothing it does while running can widen them. An operation that could raise its own retry
budget, or invent a fallback after failing, is unbounded in the only sense that matters.
"""

import time

import pytest

from src.engine.bounds import (
    BoundedExecutor,
    FallbackAction,
    OperationPolicy,
    OperationOutcome,
    RetriesExhausted,
    UndeclaredFallback,
    backoff_delays,
)
from src.engine.decompose import TaskNode
from src.engine.state import StateStore
from src.models.states import ExecutionMode, RunState, Surface
from src.store.repository import AuditRepository

pytestmark = [pytest.mark.failure, pytest.mark.integration]

FAST = OperationPolicy(timeout_seconds=1, max_attempts=3, backoff_seconds=0.01,
                       fallback=FallbackAction.SAFE_STOP)


@pytest.fixture()
def wired(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", "provide short links", "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    store.persist_nodes("run-1", [
        TaskNode(id="op-1", description="an operation", requirement_ref="FR-030",
                 execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
                 declared_outputs=("orchestrator/src/agent/probe.py",),
                 timeout_seconds=1, max_attempts=3, backoff_seconds=0),
    ])
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    return BoundedExecutor(engine=clean_db, run_id="run-1"), clean_db


def _events(engine, run_id="run-1"):
    return [e.event_type for e in AuditRepository(engine).for_run(run_id)]


# --- policy is fixed before dispatch -----------------------------------------

def test_policy_is_immutable_once_declared():
    policy = FAST
    for field, value in (("timeout_seconds", 999), ("max_attempts", 99),
                         ("backoff_seconds", 60), ("fallback", FallbackAction.WAIT_FOR_HUMAN)):
        with pytest.raises(Exception):
            setattr(policy, field, value)


def test_a_policy_must_declare_positive_bounds():
    for bad in ({"max_attempts": 0}, {"timeout_seconds": 0}, {"backoff_seconds": -1}):
        with pytest.raises(Exception):
            OperationPolicy(timeout_seconds=1, max_attempts=1, backoff_seconds=0,
                            fallback=FallbackAction.SAFE_STOP, **bad)


def test_an_executing_operation_cannot_widen_its_own_budget(wired):
    """The operation is handed the attempt number, never the policy object."""
    executor, engine = wired
    seen: list = []

    def greedy(attempt: int) -> bool:
        seen.append(attempt)
        # nothing reachable from here can change the policy: it is not passed in
        return False

    with pytest.raises(RetriesExhausted):
        executor.run("op-1", greedy, policy=FAST)
    assert seen == [1, 2, 3], "the budget held at exactly three attempts"


# --- timeout ------------------------------------------------------------------

def test_each_attempt_has_its_own_timeout(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=1, backoff_seconds=0,
                             fallback=FallbackAction.SAFE_STOP)

    started = time.monotonic()
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: time.sleep(30), policy=policy)
    elapsed = time.monotonic() - started

    assert elapsed < 10, "the wait was bounded by the timeout, not by the operation"
    assert "OPERATION_TIMED_OUT" in _events(engine)


def test_timeout_is_per_attempt_not_per_operation(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=2, backoff_seconds=0,
                             fallback=FallbackAction.SAFE_STOP)
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: time.sleep(30), policy=policy)
    assert _events(engine).count("OPERATION_TIMED_OUT") == 2


# --- retries -------------------------------------------------------------------

def test_retry_succeeds_on_a_later_attempt(wired):
    executor, engine = wired
    outcome = executor.run("op-1", lambda attempt: attempt >= 2, policy=FAST)

    assert isinstance(outcome, OperationOutcome)
    assert outcome.succeeded is True
    assert outcome.attempts == 2
    assert _events(engine).count("OPERATION_ATTEMPTED") == 2
    assert _events(engine).count("OPERATION_FAILED") == 1


def test_max_attempts_exhausted_raises_and_stops(wired):
    executor, engine = wired
    calls: list[int] = []
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: calls.append(attempt) or False, policy=FAST)

    assert len(calls) == FAST.max_attempts
    assert _events(engine).count("OPERATION_ATTEMPTED") == 3


def test_no_attempt_occurs_after_exhaustion(wired):
    executor, engine = wired
    calls: list[int] = []

    def always_fail(attempt: int) -> bool:
        calls.append(attempt)
        return False

    with pytest.raises(RetriesExhausted):
        executor.run("op-1", always_fail, policy=FAST)
    before = len(calls)

    # a second run against an already-exhausted operation must not start a fourth attempt
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", always_fail, policy=FAST)
    assert len(calls) == before, "the persisted budget was already spent"


def test_backoff_is_bounded_and_never_unbounded():
    policy = OperationPolicy(timeout_seconds=5, max_attempts=5, backoff_seconds=2,
                             fallback=FallbackAction.SAFE_STOP)
    delays = backoff_delays(policy)

    assert len(delays) == policy.max_attempts - 1, "no wait after the final attempt"
    assert delays == sorted(delays), "backoff grows"
    assert max(delays) <= policy.max_backoff_seconds
    assert sum(delays) < float("inf")


def test_backoff_is_capped_rather_than_doubling_forever():
    policy = OperationPolicy(timeout_seconds=1, max_attempts=12, backoff_seconds=1,
                             fallback=FallbackAction.SAFE_STOP)
    assert max(backoff_delays(policy)) <= policy.max_backoff_seconds


# --- fallback ------------------------------------------------------------------

def test_an_undeclared_fallback_is_rejected_before_the_operation_runs(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=1, backoff_seconds=0,
                             fallback=FallbackAction.HANDLER, fallback_handler="not_registered")
    calls: list[int] = []

    with pytest.raises(UndeclaredFallback):
        executor.run("op-1", lambda attempt: calls.append(attempt) or True, policy=policy)
    assert calls == [], "nothing ran: the policy was rejected before dispatch"


def test_an_agent_cannot_invent_a_fallback_after_failure(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=1, backoff_seconds=0,
                             fallback=FallbackAction.SAFE_STOP)

    def failing_and_scheming(attempt: int) -> bool:
        # An operation has no channel to register a handler mid-flight: the registry
        # is the executor's, and the policy is frozen.
        return False

    with pytest.raises(RetriesExhausted):
        executor.run("op-1", failing_and_scheming, policy=policy)
    assert StateStore(engine).run_state("run-1") is RunState.SAFE_STOPPED


def test_declared_safe_stop_preserves_state_and_is_audited(wired):
    executor, engine = wired
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: False, policy=FAST)

    assert StateStore(engine).run_state("run-1") is RunState.SAFE_STOPPED
    events = _events(engine)
    assert "FALLBACK_EXECUTED" in events
    assert "SAFE_STOP_RETRIES_EXHAUSTED" in events
    # state preserved: the node and its attempt count are still readable
    graph = StateStore(engine).load_graph("run-1")
    assert graph.nodes["op-1"].attempt_count == FAST.max_attempts


def test_declared_wait_for_human_quiesces_execution(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=2, backoff_seconds=0,
                             fallback=FallbackAction.WAIT_FOR_HUMAN)
    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: False, policy=policy)

    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert "FALLBACK_EXECUTED" in _events(engine)
    assert "WAIT_FOR_HUMAN_RETRIES_EXHAUSTED" in _events(engine)


def test_a_declared_handler_runs_and_is_audited(wired):
    executor, engine = wired
    ran: list[str] = []
    executor.register_fallback("compensate", lambda operation_id: ran.append(operation_id))
    policy = OperationPolicy(timeout_seconds=1, max_attempts=1, backoff_seconds=0,
                             fallback=FallbackAction.HANDLER, fallback_handler="compensate")

    with pytest.raises(RetriesExhausted):
        executor.run("op-1", lambda attempt: False, policy=policy)

    assert ran == ["op-1"]
    assert "FALLBACK_EXECUTED" in _events(engine)


# --- restart -------------------------------------------------------------------

def test_restart_preserves_attempts_and_the_remaining_budget(wired):
    executor, engine = wired
    policy = OperationPolicy(timeout_seconds=1, max_attempts=3, backoff_seconds=0,
                             fallback=FallbackAction.SAFE_STOP)

    # first process: two attempts, then it dies
    with pytest.raises(RetriesExhausted):
        BoundedExecutor(engine=engine, run_id="run-1", stop_after=2).run(
            "op-1", lambda attempt: False, policy=policy)
    assert StateStore(engine).load_graph("run-1").nodes["op-1"].attempt_count == 2

    del executor
    calls: list[int] = []
    resumed = BoundedExecutor(engine=engine, run_id="run-1")
    with pytest.raises(RetriesExhausted):
        resumed.run("op-1", lambda attempt: calls.append(attempt) or False, policy=policy)

    assert calls == [3], "only the remaining attempt was spent"
    assert StateStore(engine).load_graph("run-1").nodes["op-1"].attempt_count == 3
