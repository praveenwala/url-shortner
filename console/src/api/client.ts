/**
 * Typed client for the orchestrator API.
 *
 * There is deliberately no module-level store or cache here. Every value the
 * console shows is fetched per render; nothing about a run is retained between
 * mounts, so a reload cannot show a state the server does not hold.
 */

export type RunSummary = {
  id: string;
  state: string;
  requirement_id: string;
  summary: string;
  started_at: string;
};

export type RunDetail = {
  id: string;
  state: string;
  waiting_on: string | null;
  approved_scope: string[];
  started_at: string;
  ended_at: string | null;
  requirement: { id: string; summary: string; resolution_state: string };
  metrics: {
    nodes_total: number;
    nodes_by_state: Record<string, number>;
    // `null` means no denominator — unknown, not zero. The view must not render
    // those the same way (FR-037).
    task_success_rate: number | null;
    retries: number;
    retry_rate: number | null;
    rollbacks: number;
    rollback_rate: number | null;
    mttr_seconds: number | null;
    end_to_end_seconds: number | null;
    human_wait_seconds: number;
    failures: number;
    unrecovered_failures: number;
  };
  replans: { trigger: string; blast_radius: unknown; occurred_at: string }[];
};

export type GraphNode = {
  id: string;
  description: string;
  requirement_ref: string;
  execution_mode: string;
  surface: string;
  is_sync: boolean;
  state: string;
  is_stale: boolean;
  attempt_count: number;
  depends_on: string[];
};

export type Graph = { nodes: GraphNode[]; edges: { from: string; to: string }[] };

export type Gate = {
  id: string;
  stage: string;
  kind: string;
  criteria: string;
  outcome: string | null;
  reason: string | null;
  evaluated_at: string | null;
};

export type LineageItem = {
  kind: string;
  selection: string;
  rationale: string;
  alternatives: unknown[];
  actor: string;
  serves_ref: string;
  at: string;
};

export type AuditEvent = {
  event_type: string;
  actor: string;
  trace_id: string;
  payload: unknown;
  occurred_at: string;
};

export type PendingApproval = {
  id: string;
  checkpoint: string;
  action: string | null;
  detail: Record<string, unknown>;
  requested_by: string;
  requested_at: string;
  fingerprint: string;
};

export type PendingClarification = {
  id: string;
  question: string;
  affects: string;
  requested_by: string;
  requested_at: string;
};

export type Pending = {
  approvals: PendingApproval[];
  clarifications: PendingClarification[];
};

export type ApprovalResult = {
  id: string;
  request_id: string;
  checkpoint: string;
  human_actor: string;
  approver_role_held: string;
  decision: string;
  rationale: string;
  decided_at: string;
};

export type ClarificationResult = {
  id: string;
  answer: string | null;
  answered_by: string | null;
  answered_at: string | null;
  run_state: string;
};

export type Api = {
  listRuns(): Promise<RunSummary[]>;
  getRun(runId: string): Promise<RunDetail>;
  getGraph(runId: string): Promise<Graph>;
  getGates(runId: string): Promise<Gate[]>;
  getDecisions(runId: string): Promise<LineageItem[]>;
  getAudit(runId: string): Promise<AuditEvent[]>;
  getPending(runId: string): Promise<Pending>;
  decideApproval(
    runId: string,
    requestId: string,
    body: { decision: "approved" | "rejected"; rationale: string },
    actorId: string,
  ): Promise<ApprovalResult>;
  answerClarification(
    runId: string,
    requestId: string,
    body: { answer: string },
    actorId: string,
  ): Promise<ClarificationResult>;
};

async function request<T>(path: string, actorId?: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // Identity only. Roles come from the server-side directory — a header cannot
  // grant the approver role.
  if (actorId) headers["X-Actor-Id"] = actorId;

  const response = await fetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = (body as { message?: string }).message ?? response.statusText;
    const code = (body as { error?: string }).error ?? "error";
    throw new Error(`${code}: ${message}`);
  }
  return body as T;
}

export function createApi(baseUrl = ""): Api {
  const at = (path: string) => `${baseUrl}/v1${path}`;
  return {
    listRuns: () => request(at("/runs")),
    getRun: (runId) => request(at(`/runs/${runId}`)),
    getGraph: (runId) => request(at(`/runs/${runId}/graph`)),
    getGates: (runId) => request(at(`/runs/${runId}/gates`)),
    getDecisions: (runId) => request(at(`/runs/${runId}/decisions`)),
    getAudit: (runId) => request(at(`/runs/${runId}/audit`)),
    getPending: (runId) => request(at(`/runs/${runId}/pending`)),
    decideApproval: (runId, requestId, body, actorId) =>
      request(at(`/runs/${runId}/approvals/${requestId}`), actorId, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    answerClarification: (runId, requestId, body, actorId) =>
      request(at(`/runs/${runId}/clarifications/${requestId}`), actorId, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  };
}
