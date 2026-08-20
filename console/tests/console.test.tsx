/**
 * Checkpoint 2f console tests.
 *
 * The property under test throughout: the console is a *view*. It holds no
 * authoritative workflow state, every render is reconstructed from the API, and
 * no mutation is reflected until the server has been re-read.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { RunView } from "../src/views/RunView";
import { HumanActionView } from "../src/views/HumanActionView";
import type { Api } from "../src/api/client";

const run = {
  id: "run-1",
  state: "WAITING_FOR_HUMAN",
  waiting_on: "approval",
  approved_scope: ["FR-001"],
  started_at: "2026-08-18T00:00:00Z",
  ended_at: null,
  requirement: { id: "req-1", summary: "provide short-link creation", resolution_state: "INTERPRETED" },
  metrics: { nodes_total: 2, nodes_by_state: { PENDING: 1, SUCCEEDED: 1 }, task_success_rate: 0.5, retries: 1, retry_rate: 0.25, rollbacks: 1, rollback_rate: 0.5, mttr_seconds: 42, end_to_end_seconds: 120, human_wait_seconds: 300, failures: 2, unrecovered_failures: 1 },
  replans: [{ trigger: "upstream decision changed", blast_radius: ["b"], occurred_at: "2026-08-18T01:00:00Z" }],
};

const graph = {
  nodes: [
    { id: "a", description: "build validator", requirement_ref: "FR-001", execution_mode: "agent_authored", surface: "orchestrator", is_sync: false, state: "SUCCEEDED", is_stale: false, attempt_count: 1, depends_on: [] },
    { id: "b", description: "build service", requirement_ref: "FR-001", execution_mode: "human_executed", surface: "orchestrator", is_sync: false, state: "PENDING", is_stale: true, attempt_count: 0, depends_on: ["a"] },
  ],
  edges: [{ from: "a", to: "b" }],
};

const gates = [
  { id: "g1", stage: "planning", kind: "entry", criteria: "spec complete", outcome: "FAIL", reason: "unresolved ambiguity", evaluated_at: "2026-08-18T00:10:00Z" },
];

const decisions = [
  { kind: "decision", selection: "PostgreSQL", rationale: "concurrent writers", alternatives: [{ option: "SQLite" }], actor: "agent:worker-1", serves_ref: "FR-025", at: "2026-08-18T00:20:00Z" },
];

const audit = [
  { event_type: "SAFE_STOP_SANDBOX_UNAVAILABLE", actor: "orchestrator", trace_id: "t1", payload: {}, occurred_at: "2026-08-18T00:30:00Z" },
  { event_type: "ROLLBACK_SUCCEEDED", actor: "orchestrator", trace_id: "t2", payload: {}, occurred_at: "2026-08-18T00:31:00Z" },
];

const pending = {
  approvals: [
    { id: "ap-1", checkpoint: "architecture", action: "write_file", detail: { action: "write_file", path: "orchestrator/pyproject.toml", reason: "changes dependencies" }, requested_by: "agent:worker-1", requested_at: "2026-08-18T00:40:00Z", fingerprint: "abc123" },
  ],
  clarifications: [
    { id: "cl-1", question: "What does 'smarter' mean for a link?", affects: "scope", requested_by: "orchestrator", requested_at: "2026-08-18T00:41:00Z" },
  ],
};

function makeApi(overrides: Partial<Api> = {}): Api {
  return {
    listRuns: vi.fn(async () => [{ id: "run-1", state: run.state, requirement_id: "req-1", summary: run.requirement.summary, started_at: run.started_at }]),
    getRun: vi.fn(async () => run),
    getGraph: vi.fn(async () => graph),
    getGates: vi.fn(async () => gates),
    getDecisions: vi.fn(async () => decisions),
    getAudit: vi.fn(async () => audit),
    getPending: vi.fn(async () => pending),
    decideApproval: vi.fn(async () => ({ id: "d1", request_id: "ap-1", checkpoint: "architecture", human_actor: "human:lead", approver_role_held: "approver", decision: "approved", rationale: "ok", decided_at: "now" })),
    answerClarification: vi.fn(async () => ({ id: "cl-1", answer: "a", answered_by: "human:lead", answered_at: "now", run_state: "PLANNING" })),
    ...overrides,
  };
}

describe("RunView", () => {
  it("renders run state, requirement, graph, node states, gates, lineage and audit", async () => {
    render(<RunView api={makeApi()} runId="run-1" />);

    expect(await screen.findByText(/WAITING_FOR_HUMAN/)).toBeInTheDocument();
    expect(screen.getByText(/provide short-link creation/)).toBeInTheDocument();
    // graph: both nodes, their states, and the dependency
    expect(screen.getByTestId("node-a")).toHaveTextContent("SUCCEEDED");
    expect(screen.getByTestId("node-b")).toHaveTextContent("PENDING");
    expect(screen.getByTestId("node-b")).toHaveTextContent("after a");
    // gate outcome and reason
    expect(screen.getByText(/unresolved ambiguity/)).toBeInTheDocument();
    // decision lineage
    expect(screen.getByText(/PostgreSQL/)).toBeInTheDocument();
    // audit timeline
    expect(screen.getByText(/ROLLBACK_SUCCEEDED/)).toBeInTheDocument();
  });

  it("surfaces failure and replan indicators", async () => {
    render(<RunView api={makeApi()} runId="run-1" />);
    const indicators = await screen.findByTestId("indicators");
    expect(indicators).toHaveTextContent("failures 2");
    expect(indicators).toHaveTextContent("unrecovered 1");
    expect(await screen.findByTestId("replans")).toHaveTextContent("upstream decision changed");
  });

  it("renders the reliability metrics inside the run view, not a separate screen", async () => {
    render(<RunView api={makeApi()} runId="run-1" />);
    const metrics = await screen.findByTestId("metrics");
    expect(metrics).toHaveTextContent("Task success rate");
    expect(metrics).toHaveTextContent("50%");   // task_success_rate 0.5
    expect(metrics).toHaveTextContent("1 (25%)"); // retries and rate
    expect(metrics).toHaveTextContent("42s");   // MTTR
    expect(metrics).toHaveTextContent("120s");  // end-to-end
    expect(metrics).toHaveTextContent("300s");  // human wait, reported separately
  });

  it("shows unavailable metrics as em dash rather than zero", async () => {
    const quiet = {
      ...run,
      metrics: { nodes_total: 0, nodes_by_state: {}, task_success_rate: null, retries: 0,
                 retry_rate: null, rollbacks: 0, rollback_rate: null, mttr_seconds: null,
                 end_to_end_seconds: null, human_wait_seconds: 0, failures: 0,
                 unrecovered_failures: 0 },
    };
    const api = makeApi({ getRun: vi.fn(async () => quiet) });
    render(<RunView api={api} runId="run-1" />);
    const metrics = await screen.findByTestId("metrics");
    expect(metrics).toHaveTextContent("—");
    expect(metrics).not.toHaveTextContent("0%");
  });

  it("marks a stale node", async () => {
    render(<RunView api={makeApi()} runId="run-1" />);
    expect(await screen.findByTestId("node-b")).toHaveTextContent("stale");
  });

  it("shows an API failure instead of pretending", async () => {
    const api = makeApi({ getRun: vi.fn(async () => { throw new Error("boom"); }) });
    render(<RunView api={api} runId="run-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/);
  });

  it("reconstructs every value from the API on reload — nothing is retained", async () => {
    const api = makeApi();
    const { unmount } = render(<RunView api={api} runId="run-1" />);
    await screen.findByText(/WAITING_FOR_HUMAN/);
    unmount();

    // the server now reports a different state; a remount must show it
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue({ ...run, state: "SAFE_STOPPED" });
    render(<RunView api={api} runId="run-1" />);
    expect(await screen.findByText(/SAFE_STOPPED/)).toBeInTheDocument();
    expect(api.getRun).toHaveBeenCalledTimes(2);
  });
});

describe("HumanActionView", () => {
  it("displays pending approvals and clarifications with their context", async () => {
    render(<HumanActionView api={makeApi()} runId="run-1" actorId="human:lead" />);
    expect(await screen.findByText(/architecture/)).toBeInTheDocument();
    expect(screen.getByText(/orchestrator\/pyproject.toml/)).toBeInTheDocument();
    expect(screen.getByText(/changes dependencies/)).toBeInTheDocument();
    expect(screen.getByText(/What does 'smarter' mean/)).toBeInTheDocument();
  });

  it("requires a rationale before approve or reject can be submitted", async () => {
    const api = makeApi();
    render(<HumanActionView api={api} runId="run-1" actorId="human:lead" />);
    const approve = await screen.findByRole("button", { name: /approve/i });
    expect(approve).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/rationale/i), "dependency reviewed");
    expect(approve).toBeEnabled();
  });

  it("binds the decision to the request id and re-fetches rather than assuming success", async () => {
    const api = makeApi();
    render(<HumanActionView api={api} runId="run-1" actorId="human:lead" />);
    await screen.findByRole("button", { name: /approve/i });
    await userEvent.type(screen.getByLabelText(/rationale/i), "dependency reviewed");
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => expect(api.decideApproval).toHaveBeenCalledWith(
      "run-1", "ap-1", { decision: "approved", rationale: "dependency reviewed" }, "human:lead",
    ));
    // state is re-read from the server, not assumed
    await waitFor(() => expect(api.getPending).toHaveBeenCalledTimes(2));
  });

  it("does not optimistically remove an item when the server rejects the decision", async () => {
    const api = makeApi({
      decideApproval: vi.fn(async () => { throw new Error("forbidden: not an approver"); }),
    });
    render(<HumanActionView api={api} runId="run-1" actorId="human:observer" />);
    await screen.findByRole("button", { name: /approve/i });
    await userEvent.type(screen.getByLabelText(/rationale/i), "let me through");
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/not an approver/);
    // still listed: the console never decided anything itself
    expect(screen.getByText(/orchestrator\/pyproject.toml/)).toBeInTheDocument();
  });

  it("submits a clarification answer and re-reads the run", async () => {
    const api = makeApi();
    render(<HumanActionView api={api} runId="run-1" actorId="human:lead" />);
    await screen.findByText(/What does 'smarter' mean/);
    await userEvent.type(screen.getByLabelText(/answer/i), "http and https only");
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));

    await waitFor(() => expect(api.answerClarification).toHaveBeenCalledWith(
      "run-1", "cl-1", { answer: "http and https only" }, "human:lead",
    ));
    await waitFor(() => expect(api.getPending).toHaveBeenCalledTimes(2));
  });

  it("does not resume the run from the client", async () => {
    const api = makeApi();
    render(<HumanActionView api={api} runId="run-1" actorId="human:lead" />);
    await screen.findByText(/What does 'smarter' mean/);
    await userEvent.type(screen.getByLabelText(/answer/i), "http and https only");
    await userEvent.click(screen.getByRole("button", { name: /submit answer/i }));
    await waitFor(() => expect(api.answerClarification).toHaveBeenCalled());

    // the console exposes no transition call at all
    expect(Object.keys(api)).not.toContain("transitionRun");
    expect(Object.keys(api)).not.toContain("resumeRun");
  });
});

describe("console scope", () => {
  it("has exactly two primary views", async () => {
    render(<App api={makeApi()} runId="run-1" actorId="human:lead" />);
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Run", "Human action"]);
  });

  it("keeps no authoritative state: no module-level store is exported", async () => {
    const client = await import("../src/api/client");
    const exported = Object.keys(client);
    expect(exported).not.toContain("store");
    expect(exported).not.toContain("cache");
  });
});
