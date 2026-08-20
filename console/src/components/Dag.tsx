/**
 * A readable DAG, laid out by dependency depth. No graph framework: the layout
 * is a topological level per column, which is enough to read a plan and keeps
 * the console free of a large dependency for one view.
 */
import type { GraphNode } from "../api/client";

function levels(nodes: GraphNode[]): GraphNode[][] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = new Map<string, number>();

  const depthOf = (id: string, seen = new Set<string>()): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0; // defensive: the API rejects cycles before this
    seen.add(id);
    const node = byId.get(id);
    const value = !node || node.depends_on.length === 0
      ? 0
      : 1 + Math.max(...node.depends_on.map((p) => depthOf(p, seen)));
    depth.set(id, value);
    return value;
  };

  nodes.forEach((n) => depthOf(n.id));
  const maxDepth = Math.max(0, ...[...depth.values()]);
  return Array.from({ length: maxDepth + 1 }, (_, level) =>
    nodes.filter((n) => depth.get(n.id) === level),
  );
}

const STATE_MARK: Record<string, string> = {
  PENDING: "·", READY: "▷", RUNNING: "▶", SUCCEEDED: "✓",
  FAILED: "✕", ROLLED_BACK: "↩", SKIPPED: "⃠",
};

export function Dag({ nodes }: { nodes: GraphNode[] }) {
  if (nodes.length === 0) return <p>No tasks planned yet.</p>;
  return (
    <div data-testid="dag" style={{ display: "flex", gap: "1.5rem", overflowX: "auto" }}>
      {levels(nodes).map((column, index) => (
        <div key={index} style={{ minWidth: "14rem" }}>
          <h4>Level {index}</h4>
          {column.map((node) => (
            <div
              key={node.id}
              data-testid={`node-${node.id}`}
              style={{ border: "1px solid #999", padding: "0.5rem", marginBottom: "0.5rem" }}
            >
              <strong>{STATE_MARK[node.state] ?? "?"} {node.id}</strong>
              <div>{node.description}</div>
              <div>{node.state}{node.is_stale ? " · stale" : ""}</div>
              <div>{node.execution_mode}{node.is_sync ? " · sync" : ""}</div>
              <div>{node.requirement_ref}</div>
              {node.depends_on.length > 0 && <div>after {node.depends_on.join(", ")}</div>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
