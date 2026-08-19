"""DAG construction, cycle rejection, readiness (T039, FR-022, FR-023, FR-024).

The graph is validated acyclic *before* execution starts: a cycle rejects the
plan rather than deadlocking at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode
from src.models.states import TERMINAL_NODE_STATES, NodeState


@dataclass(slots=True)
class TaskGraph:
    nodes: dict[str, TaskNode]
    edges: dict[str, list[str]]          # node -> successors
    reverse: dict[str, list[str]]        # node -> predecessors

    def successors(self, node_id: str) -> list[str]:
        return list(self.edges.get(node_id, []))

    def predecessors(self, node_id: str) -> list[str]:
        return list(self.reverse.get(node_id, []))

    def ready(self) -> list[TaskNode]:
        """FR-023: a task is ready only when every predecessor has SUCCEEDED.

        "Terminal" is not enough. FAILED, SKIPPED, and ROLLED_BACK are terminal
        too, and a node whose predecessor ended in one of those must not run —
        it is unreachable, not ready.
        """
        out: list[TaskNode] = []
        for node in self.nodes.values():
            if node.state is not NodeState.PENDING:
                continue
            preds = self.predecessors(node.id)
            if all(self.nodes[p].state is NodeState.SUCCEEDED for p in preds):
                out.append(node)
        return out

    def unreachable(self) -> list[TaskNode]:
        """PENDING nodes that can never become ready, because some predecessor
        reached a terminal state other than SUCCEEDED. They are skipped rather
        than left to hang (FR-024 edge case)."""
        out: list[TaskNode] = []
        for node in self.nodes.values():
            if node.state is not NodeState.PENDING:
                continue
            for p in self.predecessors(node.id):
                pstate = self.nodes[p].state
                if pstate in TERMINAL_NODE_STATES and pstate is not NodeState.SUCCEEDED:
                    out.append(node)
                    break
        return out

    def all_terminal(self) -> bool:
        return all(n.state in TERMINAL_NODE_STATES for n in self.nodes.values())

    def descendants(self, node_id: str) -> set[str]:
        """Dependency closure — the basis for blast radius (FR-033)."""
        seen: set[str] = set()
        stack = list(self.successors(node_id))
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(self.successors(nid))
        return seen


def build_graph(nodes: list[TaskNode]) -> TaskGraph:
    by_id: dict[str, TaskNode] = {}
    for node in nodes:
        if node.id in by_id:
            raise OrchestratorError(f"duplicate task id {node.id!r}", ErrorCode.INVALID_REQUEST)
        by_id[node.id] = node

    edges: dict[str, list[str]] = {nid: [] for nid in by_id}
    reverse: dict[str, list[str]] = {nid: [] for nid in by_id}
    for node in nodes:
        for dep in node.depends_on:
            if dep not in by_id:
                raise OrchestratorError(
                    f"task {node.id!r} depends on unknown task {dep!r}",
                    ErrorCode.UNKNOWN_DEPENDENCY,
                )
            edges[dep].append(node.id)
            reverse[node.id].append(dep)

    graph = TaskGraph(nodes=by_id, edges=edges, reverse=reverse)
    cycle = find_cycle(graph)
    if cycle:
        raise OrchestratorError(
            "plan is not acyclic: " + " -> ".join(cycle), ErrorCode.CYCLE_DETECTED
        )
    return graph


def find_cycle(graph: TaskGraph) -> list[str] | None:
    """Returns one cycle as a node path, or None. Iterative DFS with colouring."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {nid: WHITE for nid in graph.nodes}
    parent: dict[str, str | None] = {nid: None for nid in graph.nodes}

    for root in graph.nodes:
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            nid, processed = stack.pop()
            if processed:
                colour[nid] = BLACK
                continue
            if colour[nid] == GREY:
                continue
            colour[nid] = GREY
            stack.append((nid, True))
            for succ in graph.successors(nid):
                if colour[succ] == GREY:
                    path = [succ, nid]
                    walk = parent[nid]
                    while walk is not None and walk != succ:
                        path.append(walk)
                        walk = parent[walk]
                    if walk == succ:
                        path.append(succ)
                    return list(reversed(path))
                if colour[succ] == WHITE:
                    parent[succ] = nid
                    stack.append((succ, False))
    return None


def topological_order(graph: TaskGraph) -> list[str]:
    indegree = {nid: len(graph.predecessors(nid)) for nid in graph.nodes}
    queue = sorted(nid for nid, d in indegree.items() if d == 0)
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for succ in sorted(graph.successors(nid)):
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)
    if len(order) != len(graph.nodes):
        raise OrchestratorError("plan is not acyclic", ErrorCode.CYCLE_DETECTED)
    return order
