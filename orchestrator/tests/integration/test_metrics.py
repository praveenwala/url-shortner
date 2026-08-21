"""T094 — reliability metrics per the R11 definitions (FR-037, SC-014).

The definition that carries the most weight: time spent in WAITING_FOR_HUMAN is excluded from
MTTR and end-to-end latency, and reported separately. Folding it in would make both metrics a
measure of how fast a person answered their messages rather than how the system performed.
"""

from datetime import timedelta

import pytest

from src.audit.metrics import MetricsService
from src.engine.state import StateStore
from src.models.states import RunState
from src.store.repository import AuditRepository
from src.trace.correlation import Correlation, now

pytestmark = pytest.mark.integration


def _seed(engine, run_id, requirement_id="req-1"):
    store = StateStore(engine)
    with engine.begin() as conn:
        from sqlalchemy import text
        exists = conn.execute(
            text("SELECT 1 FROM requirement WHERE id = :i"), {"i": requirement_id}
        ).one_or_none()
    if not exists:
        store.create_requirement(requirement_id, "provide short links", "human:lead")
    store.create_run(run_id, requirement_id, wall_clock_ceiling=3600, retry_ceiling=3)
    return store


def _event(engine, run_id, event_type, at, payload=None):
    AuditRepository(engine).append(
        Correlation(run_id=run_id, actor="orchestrator", occurred_at=at),
        event_type, payload or {},
    )


@pytest.fixture()
def metrics(clean_db):
    return MetricsService(clean_db), clean_db


# --- success rate ------------------------------------------------------------

def test_success_rate_counts_only_terminal_runs(metrics):
    service, engine = metrics
    store = _seed(engine, "run-ok")
    store.transition_run("run-ok", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-ok", RunState.EXECUTING)
    store.transition_run("run-ok", RunState.COMPLETED)

    _seed(engine, "run-fail")
    StateStore(engine).transition_run("run-fail", RunState.FAILED)

    _seed(engine, "run-live")  # still PLANNING — not terminal, not counted

    across = service.across_runs()
    assert across.runs_terminal == 2
    assert across.runs_completed == 1
    assert across.success_rate == pytest.approx(0.5)


def test_success_rate_is_none_when_nothing_has_terminated(metrics):
    service, engine = metrics
    _seed(engine, "run-live")
    assert service.across_runs().success_rate is None


# --- retry and rollback frequency -------------------------------------------

def test_retry_and_rollback_frequency_are_ratios_not_counts(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    base = now()
    for i in range(4):
        _event(engine, "run-1", "OPERATION_EXECUTED", base + timedelta(seconds=i))
    _event(engine, "run-1", "RETRY", base + timedelta(seconds=5))
    _event(engine, "run-1", "CHANGE_APPLIED", base + timedelta(seconds=6))
    _event(engine, "run-1", "CHANGE_APPLIED", base + timedelta(seconds=7))
    _event(engine, "run-1", "ROLLBACK_SUCCEEDED", base + timedelta(seconds=8))

    run = service.for_run("run-1")
    assert run.operations == 4
    assert run.retries == 1
    assert run.retry_frequency == pytest.approx(0.25)
    assert run.changes_applied == 2
    assert run.rollbacks == 1
    assert run.rollback_frequency == pytest.approx(0.5)


# --- MTTR, excluding human wait ---------------------------------------------

def test_mttr_measures_failure_to_recovery(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    base = now()
    _event(engine, "run-1", "NODE_FAILED", base, {"node_id": "a"})
    _event(engine, "run-1", "NODE_RECOVERED", base + timedelta(seconds=30), {"node_id": "a"})

    run = service.for_run("run-1")
    assert run.mttr_seconds == pytest.approx(30, abs=1)
    assert run.recoveries == 1


def test_human_wait_is_excluded_from_mttr_and_reported_separately(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    base = now()
    _event(engine, "run-1", "NODE_FAILED", base, {"node_id": "a"})
    _event(engine, "run-1", "RUN_STATE_CHANGED", base + timedelta(seconds=10),
           {"to": "WAITING_FOR_HUMAN"})
    _event(engine, "run-1", "RUN_STATE_CHANGED", base + timedelta(seconds=310),
           {"from": "WAITING_FOR_HUMAN", "to": "EXECUTING"})
    _event(engine, "run-1", "NODE_RECOVERED", base + timedelta(seconds=340), {"node_id": "a"})

    run = service.for_run("run-1")
    # 340s wall clock, 300s of it waiting on a person
    assert run.human_wait_seconds == pytest.approx(300, abs=1)
    assert run.mttr_seconds == pytest.approx(40, abs=1), (
        "MTTR must measure the system, not how fast someone answered")


def test_mttr_is_none_when_nothing_failed(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    _event(engine, "run-1", "OPERATION_EXECUTED", now())
    assert service.for_run("run-1").mttr_seconds is None


def test_an_unrecovered_failure_does_not_contribute_to_mttr(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    _event(engine, "run-1", "NODE_FAILED", now(), {"node_id": "a"})
    run = service.for_run("run-1")
    assert run.mttr_seconds is None
    assert run.unrecovered_failures == 1


# --- end-to-end latency ------------------------------------------------------

def test_end_to_end_latency_excludes_human_wait(metrics):
    service, engine = metrics
    store = _seed(engine, "run-1")
    base = now()
    _event(engine, "run-1", "RUN_STATE_CHANGED", base + timedelta(seconds=10),
           {"to": "WAITING_FOR_HUMAN"})
    _event(engine, "run-1", "RUN_STATE_CHANGED", base + timedelta(seconds=70),
           {"from": "WAITING_FOR_HUMAN", "to": "EXECUTING"})
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    store.transition_run("run-1", RunState.COMPLETED)

    run = service.for_run("run-1")
    assert run.human_wait_seconds == pytest.approx(60, abs=2)
    assert run.end_to_end_seconds is not None
    assert run.end_to_end_seconds < run.wall_clock_seconds


def test_latency_is_none_for_a_run_still_in_flight(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    assert service.for_run("run-1").end_to_end_seconds is None


# --- reporting shape ---------------------------------------------------------

def test_across_runs_aggregates_every_required_metric(metrics):
    service, engine = metrics
    store = _seed(engine, "run-1")
    _event(engine, "run-1", "OPERATION_EXECUTED", now())
    _event(engine, "run-1", "RETRY", now())
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    store.transition_run("run-1", RunState.COMPLETED)

    report = service.across_runs().as_dict()
    for required in ("success_rate", "retry_frequency", "rollback_frequency",
                     "mttr_seconds", "end_to_end_seconds", "human_wait_seconds"):
        assert required in report, required


def test_metrics_carry_no_secrets_or_personal_data(metrics):
    service, engine = metrics
    _seed(engine, "run-1")
    _event(engine, "run-1", "OPERATION_EXECUTED", now(), {"task_id": "a"})
    payload = str(service.across_runs().as_dict()) + str(service.for_run("run-1").as_dict())
    for marker in ("password", "secret", "api_key", "token", "@"):
        assert marker not in payload.lower()


def test_metrics_agree_with_independently_observed_outcomes(metrics):
    """SC-014: the report must match what actually happened, counted by hand."""
    service, engine = metrics
    observed_completed, observed_failed = 0, 0
    for index in range(5):
        run_id = f"run-{index}"
        store = _seed(engine, run_id)
        store.transition_run(run_id, RunState.AWAITING_PLAN_APPROVAL)
        store.transition_run(run_id, RunState.EXECUTING)
        if index % 2 == 0:
            store.transition_run(run_id, RunState.COMPLETED)
            observed_completed += 1
        else:
            store.transition_run(run_id, RunState.FAILED)
            observed_failed += 1

    across = service.across_runs()
    assert across.runs_completed == observed_completed
    assert across.runs_terminal == observed_completed + observed_failed
    assert across.success_rate == pytest.approx(observed_completed / (observed_completed + observed_failed))


# --- safe-stop, reload, and the zero-vs-unavailable distinction --------------

def test_mttr_measures_recovery_from_a_safe_stop(metrics):
    """A safe-stop is a failure to recover from, not a quiet ending (FR-031)."""
    service, engine = metrics
    _seed(engine, "run-1")
    base = now()
    _event(engine, "run-1", "SAFE_STOP_SANDBOX_UNAVAILABLE", base, {"reason": "no daemon"})
    _event(engine, "run-1", "RUN_RESUMED", base + timedelta(seconds=45))

    run = service.for_run("run-1")
    assert run.failures == 1
    assert run.recoveries == 1
    assert run.mttr_seconds == pytest.approx(45, abs=1)


def test_metrics_survive_a_reload_because_nothing_is_counted_in_memory(metrics):
    service, engine = metrics
    store = _seed(engine, "run-1")
    base = now()
    _event(engine, "run-1", "OPERATION_EXECUTED", base)
    _event(engine, "run-1", "RETRY", base + timedelta(seconds=1))
    _event(engine, "run-1", "NODE_FAILED", base + timedelta(seconds=2))
    _event(engine, "run-1", "NODE_RECOVERED", base + timedelta(seconds=12))
    store.transition_run("run-1", RunState.AWAITING_PLAN_APPROVAL)
    store.transition_run("run-1", RunState.EXECUTING)
    store.transition_run("run-1", RunState.COMPLETED)
    before = service.for_run("run-1").as_dict()

    # the process dies; a fresh service reads the same rows
    del service
    after = MetricsService(engine).for_run("run-1").as_dict()
    assert after == before
    assert after["mttr_seconds"] == pytest.approx(10, abs=1)


def test_zero_activity_is_zero_and_unavailable_is_none(metrics):
    """A rate with no denominator is unknown, not 0.0 — reporting 0% retries for a
    run that executed nothing would be a lie a reviewer could act on."""
    service, engine = metrics
    _seed(engine, "run-quiet")
    run = service.for_run("run-quiet")

    assert run.operations == 0 and run.retries == 0        # zero activity: counts are 0
    assert run.retry_frequency is None                     # no denominator: unknown
    assert run.rollback_frequency is None
    assert run.mttr_seconds is None
    assert run.end_to_end_seconds is None

    _event(engine, "run-quiet", "OPERATION_EXECUTED", now())
    assert service.for_run("run-quiet").retry_frequency == 0.0, (
        "with a denominator and no retries, the rate is genuinely zero")
