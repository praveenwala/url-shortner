"""Synchronisation nodes (T043, FR-024).

A sync node releases downstream work only when *every* inbound branch has
reached a terminal state, and it records the outcome of each branch — including
the case where one sibling failed while another succeeded, which must produce a
recorded decision rather than a hang.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from src.graph.builder import TaskGraph
from src.models.states import TERMINAL_NODE_STATES, NodeState


class SyncPolicy(StrEnum):
    ALL_MUST_SUCCEED = "all_must_succeed"
    ANY_MAY_FAIL = "any_may_fail"


@dataclass(slots=True)
class BranchOutcome:
    node_id: str
    state: NodeState

    @property
    def succeeded(self) -> bool:
        return self.state is NodeState.SUCCEEDED


@dataclass(slots=True)
class SyncResult:
    released: bool
    branches: list[BranchOutcome] = field(default_factory=list)
    reason: str = ""

    @property
    def all_succeeded(self) -> bool:
        return all(b.succeeded for b in self.branches)


def evaluate_sync(
    graph: TaskGraph, node_id: str, policy: SyncPolicy = SyncPolicy.ALL_MUST_SUCCEED
) -> SyncResult:
    inbound = graph.predecessors(node_id)
    branches = [BranchOutcome(nid, graph.nodes[nid].state) for nid in inbound]

    pending = [b for b in branches if b.state not in TERMINAL_NODE_STATES]
    if pending:
        return SyncResult(
            released=False,
            branches=branches,
            reason=f"waiting on {len(pending)} branch(es): {', '.join(b.node_id for b in pending)}",
        )

    if policy is SyncPolicy.ALL_MUST_SUCCEED and not all(b.succeeded for b in branches):
        failed = [b.node_id for b in branches if not b.succeeded]
        return SyncResult(
            released=False,
            branches=branches,
            reason=f"all branches terminal but {', '.join(failed)} did not succeed",
        )

    return SyncResult(released=True, branches=branches, reason="all inbound branches terminal")
