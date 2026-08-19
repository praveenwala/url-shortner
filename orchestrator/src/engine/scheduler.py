"""Concurrent scheduler (T043, FR-023, FR-024).

Tasks whose dependencies are satisfied run concurrently; a task never starts
while a predecessor is unfinished. Sync nodes are not executed as work — they
are evaluated, and they release downstream only when every inbound branch is
terminal.

The executor is injected, so workflow tests can drive it deterministically and
so the bounded agent runtime (checkpoint 2d, not yet built) can be substituted
without touching this module.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from src.engine.decompose import TaskNode
from src.graph.builder import TaskGraph
from src.graph.sync import SyncPolicy, SyncResult, evaluate_sync
from src.models.states import NodeState, check_node_transition

TaskExecutor = Callable[[TaskNode], bool]
"""Returns True on success. Raising is treated as failure."""


@dataclass(slots=True)
class RunTrace:
    """What actually happened — used by tests to assert concurrency and ordering."""

    started: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    sync_results: dict[str, SyncResult] = field(default_factory=dict)
    max_concurrent: int = 0
    transitions: list[tuple[str, NodeState, NodeState]] = field(default_factory=list)


class Scheduler:
    def __init__(
        self,
        graph: TaskGraph,
        executor: TaskExecutor,
        max_workers: int = 8,
        sync_policy: SyncPolicy = SyncPolicy.ALL_MUST_SUCCEED,
        on_transition: Callable[[TaskNode, NodeState, NodeState], None] | None = None,
    ) -> None:
        self._graph = graph
        self._executor = executor
        self._max_workers = max_workers
        self._sync_policy = sync_policy
        self._on_transition = on_transition
        self._lock = threading.Lock()
        self._in_flight = 0
        self.trace = RunTrace()

    # -- state transitions are the only place node state changes -------------
    def _transition(self, node: TaskNode, target: NodeState) -> None:
        check_node_transition(node.state, target)
        previous = node.state
        node.state = target
        with self._lock:
            self.trace.transitions.append((node.id, previous, target))
        if self._on_transition is not None:
            self._on_transition(node, previous, target)

    def _run_one(self, node: TaskNode) -> None:
        with self._lock:
            self._in_flight += 1
            self.trace.max_concurrent = max(self.trace.max_concurrent, self._in_flight)
            self.trace.started.append(node.id)
        try:
            node.attempt_count += 1
            ok = bool(self._executor(node))
        except Exception:
            ok = False
        finally:
            with self._lock:
                self._in_flight -= 1
                self.trace.finished.append(node.id)
        self._transition(node, NodeState.SUCCEEDED if ok else NodeState.FAILED)

    def _settle_sync_nodes(self) -> bool:
        """Evaluate every pending sync node. Returns True if anything changed."""
        changed = False
        for node in list(self._graph.nodes.values()):
            if not node.is_sync or node.state is not NodeState.PENDING:
                continue
            result = evaluate_sync(self._graph, node.id, self._sync_policy)
            self.trace.sync_results[node.id] = result
            if result.released:
                self._transition(node, NodeState.READY)
                self._transition(node, NodeState.RUNNING)
                self._transition(node, NodeState.SUCCEEDED)
                changed = True
            elif all(
                b.state in {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.ROLLED_BACK,
                            NodeState.SKIPPED}
                for b in result.branches
            ) and result.branches:
                # Every branch terminal but policy not met: fail rather than hang.
                self._transition(node, NodeState.SKIPPED)
                changed = True
        return changed

    def run(self) -> RunTrace:
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            while True:
                self._settle_sync_nodes()

                ready = [n for n in self._graph.ready() if not n.is_sync]
                if not ready:
                    # Nodes whose predecessors ended in a non-SUCCEEDED terminal
                    # state can never run. Skip them so the run resolves instead
                    # of hanging (FR-024 edge case).
                    unreachable = [n for n in self._graph.unreachable() if not n.is_sync]
                    if unreachable:
                        for node in unreachable:
                            self._transition(node, NodeState.SKIPPED)
                        continue
                    if self._settle_sync_nodes():
                        continue
                    if all(n.state is not NodeState.PENDING for n in self._graph.nodes.values()):
                        break
                    # Nothing ready, nothing unreachable, nothing settled: the
                    # remaining PENDING nodes are waiting on sync nodes that are
                    # themselves waiting. Resolve them rather than spin.
                    for node in self._graph.nodes.values():
                        if node.state is NodeState.PENDING:
                            self._transition(node, NodeState.SKIPPED)
                    continue

                for node in ready:
                    self._transition(node, NodeState.READY)

                futures = []
                for node in ready:
                    self._transition(node, NodeState.RUNNING)
                    futures.append(pool.submit(self._run_one, node))
                wait(futures)

        return self.trace
