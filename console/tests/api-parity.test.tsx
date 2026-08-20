/**
 * T071 — FR-048: every field the console renders is present in an orchestrator
 * API response.
 *
 * Two checks. The first is structural: the client's TypeScript types may not
 * declare a field the API does not return. The second is behavioural: rendering
 * both views against fixtures shaped exactly like the API's responses must
 * produce no `undefined` in the DOM — which is what a field the server does not
 * send actually looks like on screen.
 */
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { RunView } from "../src/views/RunView";
import { HumanActionView } from "../src/views/HumanActionView";
import type { Api } from "../src/api/client";

/** Keys returned by orchestrator/src/api/routes.py, per endpoint. */
const API_FIELDS: Record<string, string[]> = {
  RunSummary: ["id", "state", "requirement_id", "summary", "started_at"],
  RunDetail: ["id", "state", "waiting_on", "approved_scope", "started_at", "ended_at",
              "requirement", "metrics", "replans"],
  GraphNode: ["id", "description", "requirement_ref", "execution_mode", "surface", "is_sync",
              "state", "is_stale", "attempt_count", "depends_on"],
  Gate: ["id", "stage", "kind", "criteria", "outcome", "reason", "evaluated_at"],
  LineageItem: ["kind", "selection", "rationale", "alternatives", "actor", "serves_ref", "at"],
  AuditEvent: ["event_type", "actor", "trace_id", "payload", "occurred_at"],
  PendingApproval: ["id", "checkpoint", "action", "detail", "requested_by", "requested_at",
                    "fingerprint"],
  PendingClarification: ["id", "question", "affects", "requested_by", "requested_at"],
  ApprovalResult: ["id", "request_id", "checkpoint", "human_actor", "approver_role_held",
                   "decision", "rationale", "decided_at"],
  ClarificationResult: ["id", "answer", "answered_by", "answered_at", "run_state"],
};

function declaredFields(source: string, typeName: string): string[] {
  const match = source.match(new RegExp(`export type ${typeName} = \\{([\\s\\S]*?)\\n\\};`));
  if (!match) throw new Error(`type ${typeName} not found in client.ts`);
  return [...match[1].matchAll(/^\s{2}(\w+)\??:/gm)].map((m) => m[1]);
}

describe("console/API parity", () => {
  // jsdom gives import.meta.url an http: scheme, so resolve from the project root.
  const source = readFileSync(resolve(process.cwd(), "src/api/client.ts"), "utf8");

  it.each(Object.keys(API_FIELDS))(
    "%s declares no field the API does not return",
    (typeName) => {
      const declared = declaredFields(source, typeName);
      const extra = declared.filter((f) => !API_FIELDS[typeName].includes(f));
      expect(extra).toEqual([]);
    },
  );

  it("client exposes no state store or cache — it is a transport, not a source of truth", () => {
    expect(source).not.toMatch(/\bconst\s+(store|cache|state)\s*=/);
    expect(source).not.toMatch(/localStorage|sessionStorage/);
  });

  it("renders both views with API-shaped fixtures and shows no undefined field", async () => {
    const api: Api = {
      listRuns: vi.fn(async () => []),
      getRun: vi.fn(async () => ({
        id: "run-1", state: "EXECUTING", waiting_on: null, approved_scope: ["FR-001"],
        started_at: "2026-08-18T00:00:00Z", ended_at: null,
        requirement: { id: "req-1", summary: "provide short links", resolution_state: "INTERPRETED" },
        metrics: { nodes_total: 1, nodes_by_state: { PENDING: 1 }, task_success_rate: null,
                   retries: 0, retry_rate: null, rollbacks: 0, rollback_rate: null,
                   mttr_seconds: null, end_to_end_seconds: null, human_wait_seconds: 0,
                   failures: 0, unrecovered_failures: 0 },
        replans: [],
      })),
      getGraph: vi.fn(async () => ({
        nodes: [{ id: "a", description: "d", requirement_ref: "FR-001",
                  execution_mode: "agent_authored", surface: "orchestrator", is_sync: false,
                  state: "PENDING", is_stale: false, attempt_count: 0, depends_on: [] }],
        edges: [],
      })),
      getGates: vi.fn(async () => [{ id: "g1", stage: "planning", kind: "entry",
                                     criteria: "spec complete", outcome: "PASS", reason: "ok",
                                     evaluated_at: "2026-08-18T00:01:00Z" }]),
      getDecisions: vi.fn(async () => [{ kind: "decision", selection: "PostgreSQL",
                                         rationale: "concurrency", alternatives: [],
                                         actor: "human:lead", serves_ref: "FR-025",
                                         at: "2026-08-18T00:02:00Z" }]),
      getAudit: vi.fn(async () => [{ event_type: "RUN_CREATED", actor: "orchestrator",
                                     trace_id: "t1", payload: {},
                                     occurred_at: "2026-08-18T00:03:00Z" }]),
      getPending: vi.fn(async () => ({
        approvals: [{ id: "ap-1", checkpoint: "architecture", action: "write_file",
                      detail: { path: "orchestrator/pyproject.toml" },
                      requested_by: "agent:worker-1", requested_at: "2026-08-18T00:04:00Z",
                      fingerprint: "abc" }],
        clarifications: [{ id: "cl-1", question: "Which schemes?", affects: "scope",
                           requested_by: "orchestrator", requested_at: "2026-08-18T00:05:00Z" }],
      })),
      decideApproval: vi.fn(),
      answerClarification: vi.fn(),
    } as unknown as Api;

    const runView = render(<RunView api={api} runId="run-1" />);
    await screen.findByText(/EXECUTING/);
    expect(runView.container.textContent).not.toMatch(/undefined/);
    runView.unmount();

    const actionView = render(<HumanActionView api={api} runId="run-1" actorId="human:lead" />);
    await screen.findByText(/Which schemes\?/);
    expect(actionView.container.textContent).not.toMatch(/undefined/);
  });
});
