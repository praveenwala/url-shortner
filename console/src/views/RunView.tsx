/**
 * RunView — everything about one run, reconstructed from the API on every mount.
 *
 * No state about the run survives a reload: `useEffect` re-fetches, and nothing
 * is cached at module scope. What you see is what the server holds.
 */
import { useEffect, useState } from "react";
import type { Api, AuditEvent, Gate, Graph, LineageItem, RunDetail } from "../api/client";
import { Dag } from "../components/Dag";

type Loaded = {
  run: RunDetail;
  graph: Graph;
  gates: Gate[];
  lineage: LineageItem[];
  audit: AuditEvent[];
};

const ATTENTION_STATES = new Set(["WAITING_FOR_HUMAN", "SAFE_STOPPED", "FAILED"]);

/** A rate with no denominator is unknown, not zero. Rendering both as "0%" would
 *  tell a reviewer a run had no retries when in fact it ran nothing. */
function rate(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function seconds(value: number | null): string {
  return value === null ? "—" : `${Math.round(value)}s`;
}

export function RunView({ api, runId }: { api: Api; runId: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    Promise.all([
      api.getRun(runId), api.getGraph(runId), api.getGates(runId),
      api.getDecisions(runId), api.getAudit(runId),
    ])
      .then(([run, graph, gates, lineage, audit]) => {
        if (live) setData({ run, graph, gates, lineage, audit });
      })
      .catch((err: Error) => live && setError(err.message));
    return () => { live = false; };
  }, [api, runId]);

  if (error) return <div role="alert">Could not load run: {error}</div>;
  if (!data) return <p>Loading run…</p>;

  const { run, graph, gates, lineage, audit } = data;
  const failedGates = gates.filter((g) => g.outcome === "FAIL");
  const m = run.metrics;

  return (
    <section>
      <h2>
        Run {run.id} —{" "}
        <span style={{ color: ATTENTION_STATES.has(run.state) ? "#b00" : "inherit" }}>
          {run.state}
        </span>
        {run.waiting_on ? ` (waiting on ${run.waiting_on})` : ""}
      </h2>

      <p>
        <strong>Requirement:</strong> {run.requirement.summary}{" "}
        <em>({run.requirement.resolution_state})</em>
      </p>
      <p><strong>Approved scope:</strong> {run.approved_scope.join(", ") || "none"}</p>

      <h3>Reliability</h3>
      <dl data-testid="metrics">
        <div><dt>Task success rate</dt><dd>{rate(m.task_success_rate)}</dd></div>
        <div><dt>Retries</dt><dd>{m.retries} ({rate(m.retry_rate)})</dd></div>
        <div><dt>Rollbacks</dt><dd>{m.rollbacks} ({rate(m.rollback_rate)})</dd></div>
        <div><dt>MTTR</dt><dd>{seconds(m.mttr_seconds)}</dd></div>
        <div><dt>End-to-end latency</dt><dd>{seconds(m.end_to_end_seconds)}</dd></div>
        <div>
          <dt>Human wait (excluded from MTTR and latency)</dt>
          <dd>{seconds(m.human_wait_seconds)}</dd>
        </div>
      </dl>
      <p data-testid="indicators">
        nodes {m.nodes_total} · failures {m.failures} ·
        unrecovered {m.unrecovered_failures}
      </p>

      <h3>Dependency graph</h3>
      <Dag nodes={graph.nodes} />

      <h3>Gates</h3>
      {gates.length === 0 ? <p>No gate evaluations yet.</p> : (
        <ul>
          {gates.map((gate) => (
            <li key={gate.id} style={{ color: gate.outcome === "FAIL" ? "#b00" : "inherit" }}>
              {gate.stage} · {gate.kind} · <strong>{gate.outcome ?? "not evaluated"}</strong>
              {gate.reason ? ` — ${gate.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
      {failedGates.length > 0 && (
        <p role="status">{failedGates.length} gate(s) failed and blocked their stage.</p>
      )}

      <h3>Decision lineage</h3>
      {lineage.length === 0 ? <p>No decisions recorded yet.</p> : (
        <ul>
          {lineage.map((item, index) => (
            <li key={index}>
              [{item.kind}] <strong>{item.selection}</strong> — {item.rationale}{" "}
              <em>by {item.actor}, serving {item.serves_ref}</em>
            </li>
          ))}
        </ul>
      )}

      {run.replans.length > 0 && (
        <>
          <h3>Replans</h3>
          <ul data-testid="replans">
            {run.replans.map((replan, index) => (
              <li key={index}>
                {replan.trigger} — blast radius {JSON.stringify(replan.blast_radius)}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Audit timeline</h3>
      <ol>
        {audit.map((event, index) => (
          <li key={index}>
            <code>{event.event_type}</code> · {event.actor} · {event.occurred_at}
          </li>
        ))}
      </ol>
    </section>
  );
}
