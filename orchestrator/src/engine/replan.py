"""Selective replanning (US4, FR-033, SC-011).

Two rules carry this module.

**Only the closure moves.** An upstream change invalidates the nodes it names and everything
downstream of them, computed from the dependency graph — not the whole plan. Everything else
keeps its state and its result. A full restart is not the fallback; it is the failure.

**Staleness is a flag, not an erasure.** A stale node keeps `SUCCEEDED` and keeps its result,
and its replacement points back at it with `supersedes`. That is what makes "what did we
previously conclude, and why are we redoing it" answerable after the fact.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# Aliased so `text` stays available as a domain word: a change request has text,
# and the API should say so rather than contorting the parameter name.
from sqlalchemy import Engine
from sqlalchemy import text as sql_text

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.approvals import ApprovalService, Checkpoint
from src.engine.decompose import TaskNode
from src.engine.decisions import DecisionStore
from src.engine.state import StateStore
from src.graph.builder import build_graph
from src.models.states import ExecutionMode, NodeState, RunState, Surface
from src.store.repository import AuditRepository
from src.trace.correlation import Correlation, now


class ReplanState(StrEnum):
    REPLANNED = "replanned"
    AWAITING_ARCHITECTURE_APPROVAL = "awaiting_architecture_approval"


class OptimisationOption(StrEnum):
    """The decision ladder, cheapest first (research R13)."""

    VERIFY_QUERY_PATH = "verify_index_query_pool_transaction_scope"
    NARROW_TRANSACTION = "narrow_synchronous_counter_transaction"
    BATCH_COUNTER = "batch_or_materialise_counter_aggregate"
    CACHE_TIER = "introduce_cache_tier"


#: Options that add a component to the architecture. These stop for a human.
NEW_COMPONENT_OPTIONS = frozenset({OptimisationOption.CACHE_TIER})


@dataclass(frozen=True, slots=True)
class Measurements:
    """What is actually known. Absent evidence, the ladder starts at the bottom rung."""

    p95_ms: float | None = None
    exceeds_budget: bool = False
    attributed_to: str | None = None      # counter_contention | datastore_access | app | network
    query_path_verified: bool = False
    pooling_verified: bool = False
    batching_attempted: bool = False
    cache_design_preserves_exactness: bool = False


@dataclass(frozen=True, slots=True)
class Proposal:
    option: OptimisationOption
    rationale: str
    alternatives: list[dict[str, str]]
    requires_architecture_approval: bool


@dataclass(frozen=True, slots=True)
class ChangeRequest:
    id: str
    run_id: str
    prior_requirement_id: str
    text: str
    reason: str
    submitted_by: str
    submitted_at: str
    state: str


@dataclass(frozen=True, slots=True)
class ImpactReport:
    affected: tuple[str, ...]
    stale: tuple[str, ...]
    preserved: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplanOutcome:
    state: ReplanState
    proposal: Proposal
    impact: ImpactReport | None = None
    replacement_ids: tuple[str, ...] = ()
    approval_request_id: str | None = None


def choose_optimisation(measurements: Measurements) -> Proposal:
    """The ladder. Redis is reachable only from the top rung, and only with evidence.

    Encoded as a ladder rather than a judgement call because the failure mode here is
    well known: reaching for a cache because it is the familiar answer, before anyone
    has shown the cheap fixes are exhausted.
    """
    redis_alternative = {
        "option": "Redis cache tier",
        "status": "not selected",
        "why": "a new datastore requires measurement showing cheaper rungs are exhausted",
    }
    postgres_alternative = {
        "option": "optimise PostgreSQL first",
        "status": "preferred",
        "why": "no new component, no invalidation risk against FR-008/FR-012/SC-006",
    }

    if not measurements.exceeds_budget:
        return Proposal(
            option=OptimisationOption.VERIFY_QUERY_PATH,
            rationale=("no measured breach of the NFR-001 budget; verify index shape, query "
                       "path, pool sizing and transaction scope before changing anything"),
            alternatives=[postgres_alternative, redis_alternative],
            requires_architecture_approval=False,
        )

    if not (measurements.query_path_verified and measurements.pooling_verified):
        return Proposal(
            option=OptimisationOption.VERIFY_QUERY_PATH,
            rationale=("budget exceeded, but index/query/pool/transaction scope has not been "
                       "verified; that is the cheapest rung and must be ruled out first"),
            alternatives=[postgres_alternative, redis_alternative],
            requires_architecture_approval=False,
        )

    if measurements.attributed_to == "counter_contention" and not measurements.batching_attempted:
        return Proposal(
            option=OptimisationOption.BATCH_COUNTER,
            rationale=("measurement attributes the breach to per-link counter contention — the "
                       "recorded hot-row risk; batching or a materialised aggregate is a "
                       "bounded change inside the existing datastore"),
            alternatives=[
                {"option": "keep synchronous per-redirect counter", "status": "rejected",
                 "why": "it is the measured bottleneck"},
                redis_alternative,
            ],
            requires_architecture_approval=False,
        )

    if measurements.attributed_to == "datastore_access" and not measurements.batching_attempted:
        return Proposal(
            option=OptimisationOption.NARROW_TRANSACTION,
            rationale=("breach attributed to datastore access; narrow the synchronous "
                       "transaction before adding anything"),
            alternatives=[postgres_alternative, redis_alternative],
            requires_architecture_approval=False,
        )

    if (measurements.attributed_to == "datastore_access"
            and measurements.batching_attempted
            and measurements.cache_design_preserves_exactness):
        return Proposal(
            option=OptimisationOption.CACHE_TIER,
            rationale=("every cheaper rung is exhausted and measured: budget breached, query "
                       "path and pooling verified, batching attempted, breach attributed to "
                       "datastore access, and a cache design exists that preserves expiry, "
                       "revocation and exact counts"),
            alternatives=[
                {"option": "optimise PostgreSQL first", "status": "exhausted",
                 "why": "verified, batched, still over budget"},
                {"option": "accept the latency", "status": "rejected",
                 "why": "NFR-001 is a stated requirement"},
            ],
            requires_architecture_approval=True,
        )

    return Proposal(
        option=OptimisationOption.BATCH_COUNTER,
        rationale="budget breached with no attribution justifying a new component",
        alternatives=[postgres_alternative, redis_alternative],
        requires_architecture_approval=False,
    )


class ReplanService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._state = StateStore(engine)
        self._approvals = ApprovalService(engine)
        self._decisions = DecisionStore(engine)
        self._audit = AuditRepository(engine)

    # -- 1. intake ------------------------------------------------------------
    def submit_change(self, *, run_id: str, prior_requirement_id: str, text: str,
                      reason: str, submitted_by: str) -> ChangeRequest:
        record = ChangeRequest(
            id=uuid.uuid4().hex, run_id=run_id, prior_requirement_id=prior_requirement_id,
            text=text, reason=reason, submitted_by=submitted_by,
            submitted_at=now().isoformat(), state="submitted",
        )
        with self._engine.begin() as conn:
            conn.execute(
                sql_text("INSERT INTO change_request (id, run_id, prior_requirement_id, text,"
                     " reason, submitted_by, submitted_at, state)"
                     " VALUES (:id,:run,:prior,:t,:why,:by,:at,'submitted')"),
                {"id": record.id, "run": run_id, "prior": prior_requirement_id, "t": text,
                 "why": reason, "by": submitted_by, "at": record.submitted_at},
            )
        self._audit_event(run_id, "CHANGE_REQUEST_SUBMITTED",
                          {"change_id": record.id, "reason": reason})
        return record

    def change_request(self, change_id: str) -> ChangeRequest:
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_text("SELECT id, run_id, prior_requirement_id, text, reason, submitted_by,"
                     " submitted_at, state FROM change_request WHERE id = :id"),
                {"id": change_id},
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown change request {change_id!r}", ErrorCode.NOT_FOUND)
        return ChangeRequest(row[0], row[1], row[2], row[3], row[4], row[5], str(row[6]), row[7])

    # -- 2. impact ------------------------------------------------------------
    def analyse_impact(self, change_id: str, *, affected_nodes: list[str],
                       apply: bool = False) -> ImpactReport:
        change = self.change_request(change_id)
        graph = self._state.load_graph(change.run_id)

        unknown = [n for n in affected_nodes if n not in graph.nodes]
        if unknown:
            raise OrchestratorError(f"unknown affected nodes: {unknown}",
                                    ErrorCode.UNKNOWN_DEPENDENCY)

        blast: set[str] = set()
        for node_id in affected_nodes:
            blast.add(node_id)
            blast |= graph.descendants(node_id)
        # A replacement inherits its predecessor's fate rather than being re-derived.
        blast |= {n.id for n in graph.nodes.values()
                  if n.supersedes in blast and n.supersedes is not None}

        preserved = tuple(sorted(set(graph.nodes) - blast))
        report = ImpactReport(tuple(sorted(affected_nodes)), tuple(sorted(blast)), preserved)

        if apply:
            self._state.mark_stale(list(report.stale))
            self._set_change_state(change_id, "analysed")
            self._audit_event(change.run_id, "IMPACT_ANALYSED", {
                "change_id": change_id, "blast_radius": list(report.stale),
                "preserved": list(report.preserved),
            })
        return report

    # -- 3/4/5. replan ---------------------------------------------------------
    def replan(self, change_id: str, *, measurements: Measurements,
               extra_dependencies: list[tuple[str, str]] | None = None) -> ReplanOutcome:
        change = self.change_request(change_id)
        graph = self._state.load_graph(change.run_id)
        stale = [n for n in graph.nodes.values() if n.is_stale and not self._is_superseded(
            graph, n.id)]
        report = ImpactReport(
            tuple(sorted(n.id for n in stale)), tuple(sorted(n.id for n in stale)),
            tuple(sorted(n.id for n in graph.nodes.values() if not n.is_stale)),
        )
        proposal = choose_optimisation(measurements)

        if proposal.requires_architecture_approval:
            # Nothing is planned before a human decides. The cheaper alternative travels
            # with the request so the approver sees what is being given up.
            request = self._approvals.request(
                run_id=change.run_id, checkpoint=Checkpoint.ARCHITECTURE,
                detail={
                    "action": "introduce_component", "option": str(proposal.option),
                    "rationale": proposal.rationale,
                    "alternatives": proposal.alternatives,
                    "preserved_alternative": "optimise PostgreSQL first",
                },
                requested_by="orchestrator",
            )
            self._park(change.run_id)
            self._set_change_state(change_id, "awaiting_approval")
            self._audit_event(change.run_id, "ARCHITECTURE_APPROVAL_REQUESTED", {
                "change_id": change_id, "option": str(proposal.option),
            })
            return ReplanOutcome(
                state=ReplanState.AWAITING_ARCHITECTURE_APPROVAL, proposal=proposal,
                impact=report, approval_request_id=request.id,
            )

        return self._apply_replan(change, report, proposal, extra_dependencies or [])

    def resume_after_approval(self, change_id: str, request_id: str) -> ReplanOutcome:
        change = self.change_request(change_id)
        approved = self._approvals.is_approved(request_id)
        graph = self._state.load_graph(change.run_id)
        stale = [n.id for n in graph.nodes.values() if n.is_stale]
        report = ImpactReport(tuple(sorted(stale)), tuple(sorted(stale)),
                              tuple(sorted(n.id for n in graph.nodes.values()
                                           if not n.is_stale)))

        if approved:
            proposal = Proposal(
                option=OptimisationOption.CACHE_TIER,
                rationale="architecture checkpoint approved by a human",
                alternatives=[{"option": "optimise PostgreSQL first", "status": "exhausted",
                               "why": "verified, batched, still over budget"}],
                requires_architecture_approval=False,
            )
        else:
            # Rejection does not stall the run: the prior architecture stands and the
            # highest cheaper rung is planned instead.
            proposal = Proposal(
                option=OptimisationOption.BATCH_COUNTER,
                rationale=("architecture checkpoint rejected; the prior architecture stands "
                           "and the bounded in-datastore change is planned instead"),
                alternatives=[{"option": "Redis cache tier", "status": "rejected by human",
                               "why": "no new datastore for this deliverable"}],
                requires_architecture_approval=False,
            )
        self._unpark(change.run_id)
        return self._apply_replan(change, report, proposal, [])

    # -- queries ---------------------------------------------------------------
    def replacements(self, run_id: str) -> list[TaskNode]:
        graph = self._state.load_graph(run_id)
        return [n for n in graph.nodes.values() if n.supersedes is not None]

    def replan_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sql_text("SELECT trigger, blast_radius, nodes_marked_stale, graph_delta,"
                     " occurred_at FROM replan_event WHERE run_id = :r ORDER BY occurred_at"),
                {"r": run_id},
            ).all()
        return [
            {"trigger": r[0], "blast_radius": r[1], "nodes_marked_stale": r[2],
             "graph_delta": r[3], "occurred_at": str(r[4])}
            for r in rows
        ]

    # -- internals -------------------------------------------------------------
    def _apply_replan(self, change: ChangeRequest, report: ImpactReport, proposal: Proposal,
                      extra_dependencies: list[tuple[str, str]]) -> ReplanOutcome:
        graph = self._state.load_graph(change.run_id)
        already = {n.supersedes for n in graph.nodes.values() if n.supersedes}

        replacements: list[TaskNode] = []
        for node_id in report.stale:
            if node_id in already:
                continue  # a second replan must not clone the same replacement
            original = graph.nodes[node_id]
            replacements.append(TaskNode(
                id=f"{node_id}-r{uuid.uuid4().hex[:6]}",
                description=f"replan: {original.description}",
                requirement_ref=original.requirement_ref,
                # Recalculated, but a human-executed task can never become agent-authored
                # by way of a replan (FR-042).
                execution_mode=original.execution_mode,
                surface=original.surface,
                depends_on=list(original.depends_on),
                declared_inputs=original.declared_inputs,
                declared_outputs=original.declared_outputs,
                supersedes=node_id,
            ))

        if replacements or extra_dependencies:
            candidate = list(graph.nodes.values()) + replacements
            if extra_dependencies:
                by_id = {n.id: n for n in candidate}
                for frm, to in extra_dependencies:
                    if to in by_id and frm not in by_id[to].depends_on:
                        by_id[to].depends_on.append(frm)
            # Cycle rejection applies to the replanned graph exactly as it does to a
            # fresh plan (FR-022).
            build_graph(candidate)

        if replacements:
            self._state.persist_nodes(change.run_id, replacements)

        self._record_replan_event(change, report, proposal, replacements)
        self._decisions.record(
            run_id=change.run_id, alternatives=proposal.alternatives,
            selection=str(proposal.option), rationale=proposal.rationale,
            actor="orchestrator", serves_ref=change.prior_requirement_id,
        )
        self._set_change_state(change.id, "replanned")
        self._audit_event(change.run_id, "REPLANNED", {
            "change_id": change.id, "option": str(proposal.option),
            "replacements": [n.id for n in replacements],
        })
        return ReplanOutcome(
            state=ReplanState.REPLANNED, proposal=proposal, impact=report,
            replacement_ids=tuple(n.id for n in replacements),
        )

    def _record_replan_event(self, change: ChangeRequest, report: ImpactReport,
                             proposal: Proposal, replacements: list[TaskNode]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sql_text("INSERT INTO replan_event (id, run_id, trigger, blast_radius,"
                     " nodes_marked_stale, graph_delta, occurred_at)"
                     " VALUES (:id,:run,:trig,CAST(:blast AS JSONB),CAST(:stale AS JSONB),"
                     " CAST(:delta AS JSONB),:at)"),
                {
                    "id": uuid.uuid4().hex, "run": change.run_id,
                    "trig": f"{change.reason} ({change.text})",
                    "blast": json.dumps(list(report.stale)),
                    "stale": json.dumps(list(report.stale)),
                    "delta": json.dumps({
                        "preserved": list(report.preserved),
                        "added": [{"id": n.id, "supersedes": n.supersedes}
                                  for n in replacements],
                        "option": str(proposal.option),
                    }),
                    "at": now(),
                },
            )

    def _is_superseded(self, graph, node_id: str) -> bool:
        return any(n.supersedes == node_id for n in graph.nodes.values())

    def _set_change_state(self, change_id: str, state: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(sql_text("UPDATE change_request SET state = :s WHERE id = :id"),
                         {"s": state, "id": change_id})

    def _park(self, run_id: str) -> None:
        if self._state.run_state(run_id) is not RunState.WAITING_FOR_HUMAN:
            self._state.transition_run(run_id, RunState.WAITING_FOR_HUMAN,
                                       waiting_on="architecture approval")

    def _unpark(self, run_id: str) -> None:
        if self._state.run_state(run_id) is RunState.WAITING_FOR_HUMAN:
            self._state.transition_run(run_id, RunState.REPLANNING)

    def _audit_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._audit.append(Correlation(run_id=run_id, actor="orchestrator"),
                           event_type, payload)
