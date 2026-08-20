"""US3 — a materially ambiguous requirement halts before implementation (FR-028, SC-010).

The scenario: "Make links smarter." The system must not guess. It must stop, ask something
specific, and stay stopped until a human answers.
"""

import pytest

from src.engine.ambiguity import AmbiguityGate, GateState, detect
from src.engine.clarifications import ClarificationService
from src.engine.decisions import DecisionStore
from src.engine.intake import ResolutionState
from src.engine.state import StateStore
from src.models.states import RunState
from src.store.repository import AuditRepository

pytestmark = [pytest.mark.workflow, pytest.mark.integration]

AMBIGUOUS = "Make links smarter."
CLEAR = (
    "Allow a link creator to set an optional expiry of up to 90 days, and expose the total "
    "redirect count on the analytics summary."
)


class RecordingDispatcher:
    """Stands in for the bounded coding agent. If this is ever called while a
    requirement is unresolved, US3 has failed."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def dispatch(self, task_id: str) -> None:
        self.calls.append(task_id)


@pytest.fixture()
def gate(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-1", AMBIGUOUS, "human:lead")
    store.create_run("run-1", "req-1", wall_clock_ceiling=3600, retry_ceiling=3)
    dispatcher = RecordingDispatcher()
    return AmbiguityGate(engine=clean_db, dispatcher=dispatcher), dispatcher, clean_db


# --- detection ---------------------------------------------------------------

def test_the_scenario_requirement_is_detected_as_ambiguous():
    findings = detect(AMBIGUOUS)
    assert findings, "'Make links smarter.' must not pass as a specified requirement"
    assert all(f.question.strip().endswith("?") for f in findings)
    assert {f.affects for f in findings} <= {"scope", "security", "user_visible_behaviour"}


def test_a_specified_requirement_is_not_flagged():
    assert detect(CLEAR) == []


@pytest.mark.parametrize("text", [
    "Make the service faster.",
    "Improve reliability.",
    "Add better analytics.",
    "Make it more secure.",
    "Modernise the redirect flow.",
])
def test_unquantified_improvements_are_flagged(text):
    assert detect(text), text


def test_questions_are_specific_rather_than_a_general_complaint():
    questions = [f.question for f in detect(AMBIGUOUS)]
    assert any("smarter" in q.lower() for q in questions), questions
    assert not any(q.lower().startswith("this is vague") for q in questions)


# --- halting -----------------------------------------------------------------

def test_ambiguous_requirement_halts_and_creates_no_tasks(gate):
    service, dispatcher, engine = gate
    outcome = service.submit(run_id="run-1", requirement_id="req-1",
                             text=AMBIGUOUS, submitted_by="human:lead")

    assert outcome.state is GateState.AWAITING_CLARIFICATION
    assert outcome.tasks_created == 0
    assert service.task_count("run-1") == 0


def test_the_bounded_coding_agent_is_never_dispatched_while_unresolved(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    assert dispatcher.calls == [], "an agent was dispatched against an unresolved requirement"


def test_clarification_questions_are_persisted_against_the_requirement(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")

    pending = ClarificationService(engine).pending("run-1")
    assert pending, "no clarification was recorded"
    assert all(c.question.endswith("?") for c in pending)
    assert all(c.requirement_id == "req-1" for c in pending)


def test_run_is_waiting_for_human(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN


def test_requirement_is_marked_awaiting_clarification(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    assert service.requirement_state("req-1") is ResolutionState.AWAITING_CLARIFICATION


def test_a_specified_requirement_passes_the_gate_without_clarification(clean_db):
    store = StateStore(clean_db)
    store.create_requirement("req-2", CLEAR, "human:lead")
    store.create_run("run-2", "req-2", wall_clock_ceiling=3600, retry_ceiling=3)
    dispatcher = RecordingDispatcher()

    outcome = AmbiguityGate(engine=clean_db, dispatcher=dispatcher).submit(
        run_id="run-2", requirement_id="req-2", text=CLEAR, submitted_by="human:lead")

    assert outcome.state is GateState.CLEAR
    assert StateStore(clean_db).run_state("run-2") is RunState.PLANNING


# --- answering and resuming --------------------------------------------------

def _answer(engine, run_id, text, actor="human:lead"):
    pending = ClarificationService(engine).pending(run_id)
    assert pending, "expected a pending clarification"
    return ClarificationService(engine).answer(pending[0].id, answer=text, answered_by=actor)


def test_answer_is_persisted_before_the_run_resumes(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    answered = _answer(engine, "run-1", CLEAR)

    # persisted, and the run has not moved yet — resume is a separate, explicit step
    assert answered.answer == CLEAR
    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN

    outcome = service.resume("run-1")
    assert outcome.state is GateState.CLEAR
    assert StateStore(engine).run_state("run-1") is RunState.PLANNING


def test_answer_carries_actor_timestamp_requirement_and_lineage(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    _answer(engine, "run-1", CLEAR, actor="human:reviewer")
    service.resume("run-1")

    stored = ClarificationService(engine).pending("run-1")
    assert stored == [], "the answered clarification should no longer be pending"

    lineage = DecisionStore(engine).for_run("run-1")
    entry = next(d for d in lineage if d.actor == "human:reviewer")
    assert entry.serves_ref == "req-1"
    assert entry.decided_at
    assert CLEAR in entry.selection


def test_resume_re_interprets_using_the_clarification(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    _answer(engine, "run-1", CLEAR)
    service.resume("run-1")

    assert service.requirement_state("req-1") is ResolutionState.CLARIFIED
    interpretation = service.interpretation("req-1")
    assert CLEAR in interpretation["clarified_text"]
    assert interpretation["ambiguities"] == []


def test_an_insufficient_answer_raises_another_bounded_clarification(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    _answer(engine, "run-1", "Just make them better.")

    outcome = service.resume("run-1")
    assert outcome.state is GateState.AWAITING_CLARIFICATION
    assert outcome.round == 2
    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert ClarificationService(engine).pending("run-1"), "no follow-up question was asked"
    assert dispatcher.calls == []


def test_clarification_rounds_are_bounded_and_end_in_safe_stop(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    for _ in range(AmbiguityGate.MAX_ROUNDS + 1):
        pending = ClarificationService(engine).pending("run-1")
        if not pending:
            break
        ClarificationService(engine).answer(pending[0].id, answer="still vague",
                                            answered_by="human:lead")
        outcome = service.resume("run-1")

    assert outcome.state is GateState.SAFE_STOPPED
    assert StateStore(engine).run_state("run-1") is RunState.SAFE_STOPPED
    assert dispatcher.calls == []
    assert "SAFE_STOP_CLARIFICATION_EXHAUSTED" in [
        e.event_type for e in AuditRepository(engine).for_run("run-1")
    ]


def test_resume_without_an_answer_leaves_the_run_waiting(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    outcome = service.resume("run-1")

    assert outcome.state is GateState.AWAITING_CLARIFICATION
    assert StateStore(engine).run_state("run-1") is RunState.WAITING_FOR_HUMAN
    assert dispatcher.calls == []


def test_restart_resumes_from_persisted_state_alone(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    _answer(engine, "run-1", CLEAR)

    # the process dies; nothing in memory survives
    del service, dispatcher

    fresh_dispatcher = RecordingDispatcher()
    fresh = AmbiguityGate(engine=engine, dispatcher=fresh_dispatcher)
    outcome = fresh.resume("run-1")

    assert outcome.state is GateState.CLEAR
    assert StateStore(engine).run_state("run-1") is RunState.PLANNING
    assert fresh.requirement_state("req-1") is ResolutionState.CLARIFIED


def test_every_transition_is_audited(gate):
    service, dispatcher, engine = gate
    service.submit(run_id="run-1", requirement_id="req-1", text=AMBIGUOUS,
                   submitted_by="human:lead")
    _answer(engine, "run-1", CLEAR)
    service.resume("run-1")

    events = [e.event_type for e in AuditRepository(engine).for_run("run-1")]
    assert "AMBIGUITY_DETECTED" in events
    assert "CLARIFICATION_REQUESTED" in events
    assert "CLARIFICATION_ANSWERED" in events
    assert "REQUIREMENT_CLARIFIED" in events
