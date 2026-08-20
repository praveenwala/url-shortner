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

/**
 * A response that is not what the contract promises.
 *
 * Distinct from the server's own error envelope: that means the API answered
 * and said no, which callers may reasonably display. This means the thing that
 * answered was not the API, or did not honour its own shape — a routing
 * failure, a proxy outage, a contract break. Those must not reach a view.
 */
export class ApiClientError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiClientError";
  }
}

/** Names a value's shape without reproducing it. */
function shapeOf(value: unknown): string {
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  return typeof value;
}

/**
 * Parse strictly.
 *
 * The previous `.catch(() => ({}))` is what turned a misrouted HTML page into
 * a fabricated object that `as T` then presented as `Gate[]`. Diagnosis needs
 * the path, the status and the content type; it never needs the body, which
 * could carry anything, so only its size is reported.
 */
async function parseJson(response: Response, path: string): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "unknown";
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiClientError(
      `${path}: expected a JSON response but could not parse one ` +
        `(HTTP ${response.status}, Content-Type ${contentType}, ${text.length} bytes). ` +
        `The API is most likely not routed — check that /v1 reaches the orchestrator.`,
    );
  }
}

/**
 * The contract declares these endpoints return arrays, so a non-array is an
 * error — never an empty array. Normalising to `[]` would render "no gates" and
 * make a routing outage look like a healthy, idle system.
 */
function expectArray<T>(value: unknown, path: string): T[] {
  if (!Array.isArray(value)) {
    throw new ApiClientError(
      `${path}: the contract requires a JSON array, received ${shapeOf(value)}.`,
    );
  }
  return value as T[];
}

async function request<T>(path: string, actorId?: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // Identity only. Roles come from the server-side directory — a header cannot
  // grant the approver role.
  if (actorId) headers["X-Actor-Id"] = actorId;

  const response = await fetch(path, { ...init, headers });

  if (!response.ok) {
    // The server's own envelope is parsed leniently: a failure that is also
    // unparseable is still a failure, and the status carries the meaning.
    let envelope: { error?: string; message?: string } = {};
    try {
      envelope = JSON.parse(await response.text());
    } catch {
      envelope = {};
    }
    throw new Error(`${envelope.error ?? "error"}: ${envelope.message ?? response.statusText}`);
  }

  return (await parseJson(response, path)) as T;
}

async function requestArray<T>(path: string): Promise<T[]> {
  return expectArray<T>(await request<unknown>(path), path);
}

export function createApi(baseUrl = ""): Api {
  const at = (path: string) => `${baseUrl}/v1${path}`;
  return {
    listRuns: () => requestArray<RunSummary>(at("/runs")),
    getRun: (runId) => request(at(`/runs/${runId}`)),
    getGraph: async (runId) => {
      const path = at(`/runs/${runId}/graph`);
      const graph = await request<Graph>(path);
      // A graph is an object, but both of its collections are arrays.
      expectArray(graph?.nodes, `${path}.nodes`);
      expectArray(graph?.edges, `${path}.edges`);
      return graph;
    },
    getGates: (runId) => requestArray<Gate>(at(`/runs/${runId}/gates`)),
    getDecisions: (runId) => requestArray<LineageItem>(at(`/runs/${runId}/decisions`)),
    getAudit: (runId) => requestArray<AuditEvent>(at(`/runs/${runId}/audit`)),
    getPending: async (runId) => {
      const path = at(`/runs/${runId}/pending`);
      const pending = await request<Pending>(path);
      expectArray(pending?.approvals, `${path}.approvals`);
      expectArray(pending?.clarifications, `${path}.clarifications`);
      return pending;
    },
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
