"""Ambiguity detection (US3, FR-028).

**The rule, stated plainly**: a requirement is materially ambiguous when it asks for a change
in *quality* without saying what would count as having achieved it. Concretely — a vague
qualifier ("smarter", "better", "faster") or an open-ended improvement verb ("improve",
"modernise"), combined with the *absence* of any concrete specification: no number, no unit,
no named behaviour, no enumerated outcome.

The second half matters as much as the first. "Make links smarter" is ambiguous; "Make links
smarter: add an optional expiry of up to 90 days" is not, even though it still contains
"smarter", because it now says what to build. Flagging the adjective alone would make the gate
fire on ordinary prose and train people to route around it.

This is a deterministic heuristic, not a model. Its limits are real and documented at the
bottom of this module: it is a floor under FR-028, not a substitute for judgement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: Quality words that promise an improvement without defining one.
VAGUE_QUALIFIERS: dict[str, str] = {
    "smarter": "scope",
    "smart": "scope",
    "better": "scope",
    "improved": "scope",
    "faster": "user_visible_behaviour",
    "quicker": "user_visible_behaviour",
    "robust": "scope",
    "reliable": "scope",
    "scalable": "scope",
    "secure": "security",
    "intuitive": "user_visible_behaviour",
    "seamless": "user_visible_behaviour",
    "modern": "scope",
    "clean": "scope",
    "optimal": "scope",
    "nice": "user_visible_behaviour",
    "powerful": "scope",
}

#: Verbs that name a direction of travel but no destination.
OPEN_ENDED_VERBS: dict[str, str] = {
    "improve": "scope",
    "enhance": "scope",
    "optimise": "scope",
    "optimize": "scope",
    "modernise": "scope",
    "modernize": "scope",
    "streamline": "scope",
    "harden": "security",
    "refine": "scope",
}

#: Signals that the requirement says what to build. Any one of these is enough
#: for the qualifier to be describing something specified rather than wished for.
_CONCRETE_PATTERNS = (
    r"\d",                                   # a number, duration, percentage, count
    r"\b(must|shall)\b",                     # normative statement
    r"\bwhen\b.+\bthen\b",                   # a stated behaviour
    r"\bso that\b",                          # a stated outcome
    r"\bexpiry|expire|revoke|redirect count|analytics summary|short code\b",
)

MIN_CONTENT_WORDS = 6


class Affects(StrEnum):
    SCOPE = "scope"
    SECURITY = "security"
    USER_VISIBLE = "user_visible_behaviour"


@dataclass(frozen=True, slots=True)
class AmbiguityFinding:
    """A specific answerable question, never a general complaint (FR-028)."""

    question: str
    affects: str
    rule: str

    def __post_init__(self) -> None:
        if not self.question.strip().endswith("?"):
            raise ValueError("an ambiguity must be phrased as an answerable question")


def has_concrete_specification(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in _CONCRETE_PATTERNS)


def detect(text: str) -> list[AmbiguityFinding]:
    """Return every finding. An empty list means the requirement is specified enough
    to plan against — it does not mean it is a good requirement."""
    if text is None or not text.strip():
        return [AmbiguityFinding(
            question="The requirement is empty — what capability is being requested?",
            affects=Affects.SCOPE, rule="empty",
        )]

    lowered = text.lower()
    concrete = has_concrete_specification(text)
    findings: list[AmbiguityFinding] = []
    seen: set[str] = set()

    for word, affects in VAGUE_QUALIFIERS.items():
        if re.search(rf"\b{word}\b", lowered) and not concrete and word not in seen:
            seen.add(word)
            findings.append(AmbiguityFinding(
                question=(
                    f"What specifically would make it {word} — which behaviour would a user "
                    f"see, and how would we know it had been achieved?"
                ),
                affects=affects, rule=f"vague_qualifier:{word}",
            ))

    for verb, affects in OPEN_ENDED_VERBS.items():
        if re.search(rf"\b{verb}\b", lowered) and not concrete and verb not in seen:
            seen.add(verb)
            findings.append(AmbiguityFinding(
                question=(
                    f"'{verb}' names a direction but not a destination — what measurable "
                    f"outcome counts as done?"
                ),
                affects=affects, rule=f"open_ended_verb:{verb}",
            ))

    # A very short requirement with no specification cannot be planned against even
    # if it happens to avoid every listed word.
    content_words = [w for w in re.findall(r"[a-z']+", lowered) if len(w) > 2]
    if not findings and not concrete and len(content_words) < MIN_CONTENT_WORDS:
        findings.append(AmbiguityFinding(
            question=(
                "The requirement does not say what to build — which capability, for which "
                "actor, and what would count as done?"
            ),
            affects=Affects.SCOPE, rule="underspecified",
        ))

    return findings


# --- Known limitations (recorded, not hidden) --------------------------------
#
# * It is lexical. A requirement that is ambiguous without using any listed word
#   passes — "handle edge cases appropriately" is caught by the short-text rule only
#   by luck of length.
# * It can be satisfied superficially. Adding a number to a vague sentence clears the
#   concreteness check whether or not the number is the relevant one.
# * It has no notion of contradiction, of conflicting requirements, or of a request
#   that is specific but impossible.
#
# It is a deterministic floor that makes the halt behaviour testable and the demo
# reproducible. A model-based classifier would catch more and would need its own
# evaluation before being trusted with a gate that blocks work.


# --- the gate ----------------------------------------------------------------

import json
from typing import Any, Protocol

from sqlalchemy import Engine, text

from src.engine.clarifications import ClarificationService
from src.engine.decisions import DecisionStore
from src.engine.intake import ResolutionState
from src.engine.state import StateStore
from src.models.states import RunState
from src.store.repository import AuditRepository
from src.trace.correlation import Correlation


class GateState(StrEnum):
    CLEAR = "clear"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    SAFE_STOPPED = "safe_stopped"


@dataclass(frozen=True, slots=True)
class GateOutcome:
    state: GateState
    findings: tuple[AmbiguityFinding, ...] = ()
    clarification_ids: tuple[str, ...] = ()
    tasks_created: int = 0
    round: int = 1
    reason: str = ""


class Dispatcher(Protocol):
    def dispatch(self, task_id: str) -> None: ...


class AmbiguityGate:
    """Stands between a submitted requirement and any planning or agent work.

    Nothing downstream — decomposition, task creation, agent dispatch — happens unless this
    gate returns CLEAR. The gate holds no reference to the dispatcher other than to *not*
    call it while a requirement is unresolved; the dispatcher is injected so a test can prove
    that absence rather than assume it.
    """

    MAX_ROUNDS = 3

    def __init__(self, engine: Engine, dispatcher: Dispatcher | None = None) -> None:
        self._engine = engine
        self._dispatcher = dispatcher
        self._clarifications = ClarificationService(engine)
        self._decisions = DecisionStore(engine)
        self._state = StateStore(engine)
        self._audit = AuditRepository(engine)

    # -- submit ---------------------------------------------------------------
    def submit(self, *, run_id: str, requirement_id: str, text: str, submitted_by: str
               ) -> GateOutcome:
        findings = detect(text)
        self._record_interpretation(requirement_id, text, findings, clarified_text=text)

        if not findings:
            self._set_requirement_state(requirement_id, ResolutionState.INTERPRETED)
            self._audit_event(run_id, "REQUIREMENT_INTERPRETED",
                              {"requirement_id": requirement_id})
            return GateOutcome(state=GateState.CLEAR)

        return self._raise_clarifications(run_id, requirement_id, findings, round_number=1)

    # -- resume ---------------------------------------------------------------
    def resume(self, run_id: str) -> GateOutcome:
        """Rebuilt entirely from persisted state — a restarted process resumes identically."""
        requirement_id, original = self._requirement_for_run(run_id)
        answered = self._clarifications.answered(run_id)
        pending = self._clarifications.pending(run_id)

        if not answered:
            # Nothing has been answered: stay put. Waiting is a state, not a poll.
            return GateOutcome(
                state=GateState.AWAITING_CLARIFICATION,
                round=pending[0].round if pending else 1,
                reason="no clarification answer recorded yet",
            )

        latest = answered[-1]
        clarified = f"{original} {latest.answer}".strip()
        findings = detect(clarified)
        self._record_interpretation(requirement_id, original, findings, clarified)

        # Lineage for the human's answer (FR-027): actor, answer, timestamp, requirement.
        self._decisions.record(
            run_id=run_id, alternatives=[], selection=latest.answer or "",
            rationale=f"clarification answer to: {latest.question}",
            actor=latest.answered_by or "unknown", serves_ref=requirement_id,
        )
        self._audit_event(run_id, "CLARIFICATION_ANSWERED", {
            "clarification_id": latest.id, "actor": latest.answered_by,
            "requirement_id": requirement_id,
        })

        if not findings:
            self._set_requirement_state(requirement_id, ResolutionState.CLARIFIED)
            self._leave_waiting(run_id, RunState.PLANNING)
            self._audit_event(run_id, "REQUIREMENT_CLARIFIED",
                              {"requirement_id": requirement_id})
            return GateOutcome(state=GateState.CLEAR, round=latest.round)

        next_round = latest.round + 1
        if next_round > self.MAX_ROUNDS:
            # Principle VII: asking forever is its own failure mode.
            self._leave_waiting(run_id, RunState.SAFE_STOPPED)
            self._audit_event(run_id, "SAFE_STOP_CLARIFICATION_EXHAUSTED", {
                "requirement_id": requirement_id, "rounds": latest.round,
            })
            return GateOutcome(
                state=GateState.SAFE_STOPPED, findings=tuple(findings), round=latest.round,
                reason=f"still ambiguous after {latest.round} clarification rounds",
            )

        return self._raise_clarifications(run_id, requirement_id, findings, next_round)

    # -- queries used by callers and tests ------------------------------------
    def task_count(self, run_id: str) -> int:
        with self._engine.begin() as conn:
            return int(conn.execute(
                text("SELECT count(*) FROM task_node WHERE run_id = :r"), {"r": run_id}
            ).scalar_one())

    def requirement_state(self, requirement_id: str) -> ResolutionState:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT resolution_state FROM requirement WHERE id = :id"),
                {"id": requirement_id},
            ).one()
        return ResolutionState(row[0])

    def interpretation(self, requirement_id: str) -> dict[str, Any]:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT interpretation FROM requirement WHERE id = :id"),
                {"id": requirement_id},
            ).one()
        return row[0] or {}

    # -- internals ------------------------------------------------------------
    def _raise_clarifications(self, run_id: str, requirement_id: str,
                              findings: list[AmbiguityFinding], round_number: int
                              ) -> GateOutcome:
        self._set_requirement_state(requirement_id, ResolutionState.AWAITING_CLARIFICATION)
        self._audit_event(run_id, "AMBIGUITY_DETECTED", {
            "requirement_id": requirement_id, "round": round_number,
            "rules": [f.rule for f in findings],
        })

        ids: list[str] = []
        for finding in findings:
            request = self._clarifications.request(
                run_id=run_id, question=finding.question, affects=finding.affects,
                requested_by="orchestrator", requirement_id=requirement_id,
                round=round_number, rule=finding.rule,
            )
            ids.append(request.id)
            self._audit_event(run_id, "CLARIFICATION_REQUESTED", {
                "clarification_id": request.id, "rule": finding.rule,
                "affects": finding.affects, "round": round_number,
            })

        self._enter_waiting(run_id)
        # Nothing below this line: no decomposition, no task creation, no dispatch.
        return GateOutcome(
            state=GateState.AWAITING_CLARIFICATION, findings=tuple(findings),
            clarification_ids=tuple(ids), tasks_created=0, round=round_number,
            reason="requirement is materially ambiguous",
        )

    def _record_interpretation(self, requirement_id: str, original: str,
                               findings: list[AmbiguityFinding], clarified_text: str) -> None:
        payload = {
            "original_text": original,
            "clarified_text": clarified_text,
            "ambiguities": [
                {"question": f.question, "affects": f.affects, "rule": f.rule}
                for f in findings
            ],
        }
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE requirement SET interpretation = CAST(:i AS JSONB),"
                    " ambiguities = CAST(:a AS JSONB) WHERE id = :id"
                ),
                {"i": json.dumps(payload), "a": json.dumps(payload["ambiguities"]),
                 "id": requirement_id},
            )

    def _set_requirement_state(self, requirement_id: str, state: ResolutionState) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE requirement SET resolution_state = :s WHERE id = :id"),
                {"s": str(state), "id": requirement_id},
            )

    def _requirement_for_run(self, run_id: str) -> tuple[str, str]:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT q.id, q.submitted_text FROM workflow_run r"
                    " JOIN requirement q ON q.id = r.requirement_id WHERE r.id = :id"
                ),
                {"id": run_id},
            ).one()
        return row[0], row[1]

    def _enter_waiting(self, run_id: str) -> None:
        if self._state.run_state(run_id) is not RunState.WAITING_FOR_HUMAN:
            self._state.transition_run(run_id, RunState.WAITING_FOR_HUMAN,
                                       waiting_on="clarification")
            self._audit_event(run_id, "RUN_STATE_CHANGED",
                              {"to": str(RunState.WAITING_FOR_HUMAN)})

    def _leave_waiting(self, run_id: str, target: RunState) -> None:
        current = self._state.run_state(run_id)
        if current is target:
            return
        self._state.transition_run(run_id, target)
        self._audit_event(run_id, "RUN_STATE_CHANGED",
                          {"from": str(current), "to": str(target)})

    def _audit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._audit.append(Correlation(run_id=run_id, actor="orchestrator"),
                           event_type, payload)
