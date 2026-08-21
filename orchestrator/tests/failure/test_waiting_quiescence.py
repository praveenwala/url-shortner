"""T079 — while a run waits for a human, nothing runs (FR-049, SC-021).

`WAITING_FOR_HUMAN` is a persisted state, not a blocked process. No agent loop, no retry
timer, no polling cycle. The run consumes nothing, and only a recorded human response moves it.
"""

import threading

import pytest

from src.engine.ambiguity import AmbiguityGate, GateState
from src.engine.clarifications import ClarificationService
from src.engine.state import StateStore
from src.models.states import RunState

pytestmark = [pytest.mark.failure, pytest.mark.integration]

AMBIGUOUS = "Make links smarter."


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def dispatch(self, task_id: str) -> None:
        self.calls.append(task_id)


@pytest.fixture()
def waiting(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", AMBIGUOUS, "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    dispatcher = RecordingDispatcher()
    gate = AmbiguityGate(engine=clean_db, dispatcher=dispatcher)
    gate.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                submitted_by="human:lead")
    return gate, dispatcher, clean_db


def test_no_thread_or_timer_is_started_while_waiting(waiting):
    gate, dispatcher, _engine = waiting
    before = threading.active_count()

    for _ in range(5):
        gate.resume("run-1")  # a caller polling must not cause the run to poll

    assert threading.active_count() == before
    assert dispatcher.calls == []


def test_the_gate_holds_no_background_worker(waiting):
    gate, _dispatcher, _engine = waiting
    for attribute in vars(gate).values():
        assert not isinstance(attribute, (threading.Thread, threading.Timer))


def test_repeated_resume_without_an_answer_changes_nothing(waiting):
    gate, dispatcher, engine = waiting
    for _ in range(3):
        outcome = gate.resume("run-1")
        assert outcome.state is GateState.AWAITING_CLARIFICATION

    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert len(ClarificationService(engine).pending("run-1")) == 1, "questions must not multiply"
    assert dispatcher.calls == []


def test_the_state_never_expires_into_autonomous_execution(waiting):
    gate, dispatcher, engine = waiting
    import time

    time.sleep(1.5)
    gate.resume("run-1")

    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert gate.task_count("run-1") == 0
    assert dispatcher.calls == []


def test_only_a_recorded_answer_moves_the_run(waiting):
    gate, _dispatcher, engine = waiting
    pending = ClarificationService(engine).pending("run-1")[0]

    assert gate.resume("run-1").state is GateState.AWAITING_CLARIFICATION
    ClarificationService(engine).answer(
        pending.id,
        answer="Allow an optional expiry of up to 90 days and expose the redirect count.",
        answered_by="human:lead",
    )
    assert gate.resume("run-1").state is GateState.CLEAR
    assert StateStore(engine).run_state("run-1") is RunState.PLANNING
