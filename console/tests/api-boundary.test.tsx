/**
 * Regression tests for the console runtime crash found preparing HUMAN T022.
 *
 * `gates.filter is not a function` was never a RunView bug. Vite had no `/v1`
 * proxy, so the SPA fallback answered every API call with `index.html` at HTTP
 * **200**; the client's `.catch(() => ({}))` turned that HTML into `{}`, and
 * `as T` presented the object as `Gate[]`. The type system was satisfied and
 * the failure surfaced three layers away from its cause.
 *
 * These tests pin the boundary, not the symptom: a body that is not what the
 * contract promises must fail *in the client*, naming the path and status, and
 * must never be normalised into an empty array — `[]` would turn a routing
 * outage into a page that renders "no gates" and looks fine.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { RunView } from "../src/views/RunView";
import { ApiClientError, createApi } from "../src/api/client";
import type { Api } from "../src/api/client";

/** Returns the rejection, and fails if the call unexpectedly resolved. */
async function rejection(promise: Promise<unknown>): Promise<ApiClientError> {
  try {
    await promise;
  } catch (error) {
    return error as ApiClientError;
  }
  throw new Error("expected the call to reject, but it resolved");
}

const INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>';

function respondWith(body: string, contentType: string, status = 200) {
  const fetchMock = vi.fn(async (..._args: unknown[]) =>
    new Response(body, { status, headers: { "Content-Type": contentType } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

// --- 1. the exact failure: 200 + HTML ---------------------------------------

describe("an ok response that is not JSON", () => {
  it("fails in the client with ApiClientError rather than reaching a view", async () => {
    respondWith(INDEX_HTML, "text/html");
    await expect(createApi().getGates("run-1")).rejects.toBeInstanceOf(ApiClientError);
  });

  it("names the path, status and content type so the misroute is diagnosable", async () => {
    respondWith(INDEX_HTML, "text/html");
    const error = await rejection(createApi().getGates("run-1"));
    expect(error.message).toContain("/v1/runs/run-1/gates");
    expect(error.message).toContain("200");
    expect(error.message).toContain("text/html");
  });

  it("does not echo the response body", async () => {
    // A body could carry anything — an upstream error page, a token in a query
    // echo. The diagnosis needs the shape, never the contents.
    respondWith('<!doctype html><p>sk-ant-secret-value</p>', "text/html");
    const error = await rejection(createApi().getGates("run-1"));
    expect(error.message).not.toContain("sk-ant-secret-value");
    expect(error.message).not.toContain("<!doctype");
  });
});

// --- 2. 200 + {} where an array is promised ----------------------------------

describe("an ok response whose shape contradicts the contract", () => {
  it("treats {} from getGates as a contract-shape error", async () => {
    respondWith("{}", "application/json");
    const error = await rejection(createApi().getGates("run-1"));
    expect(error).toBeInstanceOf(ApiClientError);
    expect(error.message).toMatch(/array/i);
  });

  it("does not normalise a malformed body to an empty array", async () => {
    // Silently yielding [] would render "no gates" and hide the outage.
    respondWith("{}", "application/json");
    await expect(createApi().getGates("run-1")).rejects.toBeInstanceOf(ApiClientError);
  });

  it.each([
    ["listRuns", (api: Api) => api.listRuns()],
    ["getGraph", (api: Api) => api.getGraph("run-1")],
    ["getGates", (api: Api) => api.getGates("run-1")],
    ["getDecisions", (api: Api) => api.getDecisions("run-1")],
    ["getAudit", (api: Api) => api.getAudit("run-1")],
  ])("%s validates its shape at the boundary", async (_name, call) => {
    respondWith("{}", "application/json");
    await expect(call(createApi())).rejects.toBeInstanceOf(ApiClientError);
  });

  it("validates the pending collections inside the object", async () => {
    respondWith('{"approvals": {}, "clarifications": []}', "application/json");
    await expect(createApi().getPending("run-1")).rejects.toBeInstanceOf(ApiClientError);
  });
});

// --- 3. the healthy path still works -----------------------------------------

describe("a well-formed response", () => {
  it("returns an array from getGates", async () => {
    const gate = {
      id: "g1", stage: "design", kind: "entry", criteria: "spec approved",
      outcome: "PASS", reason: null, evaluated_at: "2026-08-20T10:00:00Z",
    };
    respondWith(JSON.stringify([gate]), "application/json");
    await expect(createApi().getGates("run-1")).resolves.toEqual([gate]);
  });

  it("accepts an empty array — zero gates is a valid answer", async () => {
    respondWith("[]", "application/json");
    await expect(createApi().getGates("run-1")).resolves.toEqual([]);
  });

  it("still surfaces the server's own error envelope", async () => {
    respondWith('{"error":"not_found","message":"unknown run"}', "application/json", 404);
    await expect(createApi().getGates("run-1")).rejects.toThrow(/not_found: unknown run/);
  });
});

// --- 4/5. zero runs -----------------------------------------------------------

describe("a system with no runs", () => {
  const unusedApi = new Proxy({} as Api, {
    get: (_t, prop) => () => {
      throw new Error(`the API must not be called with no run selected (${String(prop)})`);
    },
  });

  it("renders an empty state instead of mounting RunView", () => {
    render(<App api={unusedApi} runId="" actorId="" />);
    expect(screen.getByText(/no workflow runs yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/loading run/i)).not.toBeInTheDocument();
  });

  it("issues no request at all — never /v1/runs//…", async () => {
    const fetchMock = respondWith("[]", "application/json");
    render(<App api={createApi()} runId="" actorId="" />);
    await new Promise((r) => setTimeout(r, 20));
    const paths = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(paths.filter((p) => p.includes("/runs//"))).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fabricates no run object", () => {
    render(<App api={unusedApi} runId="" actorId="" />);
    expect(screen.queryByText(/^Run\s/)).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });

  it("shows a no-run state on the human action tab too", async () => {
    render(<App api={unusedApi} runId="" actorId="human:lead" />);
    await userEvent.click(screen.getByRole("tab", { name: /human action/i }));
    expect(screen.getByText(/no workflow runs yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });
});

// --- 6. RunView is unchanged and still works ----------------------------------

describe("RunView with a valid Gate[]", () => {
  it("renders and filters gates without crashing", async () => {
    const gates = [
      { id: "g1", stage: "design", kind: "entry", criteria: "c", outcome: "PASS",
        reason: null, evaluated_at: "2026-08-20T10:00:00Z" },
      { id: "g2", stage: "build", kind: "exit", criteria: "c", outcome: "FAIL",
        reason: "tests failing", evaluated_at: "2026-08-20T11:00:00Z" },
    ];
    const api = {
      getRun: async () => ({
        id: "run-1", state: "RUNNING", waiting_on: null, approved_scope: [],
        started_at: "2026-08-20T09:00:00Z", ended_at: null,
        requirement: { id: "FR-001", summary: "shorten a URL", resolution_state: "SPECIFIED" },
        metrics: {
          nodes_total: 0, nodes_by_state: {}, task_success_rate: null, retries: 0,
          retry_rate: null, rollbacks: 0, rollback_rate: null, mttr_seconds: null,
          end_to_end_seconds: null, human_wait_seconds: 0, failures: 0,
          unrecovered_failures: 0,
        },
        replans: [],
      }),
      getGraph: async () => ({ nodes: [], edges: [] }),
      getGates: async () => gates,
      getDecisions: async () => [],
      getAudit: async () => [],
    } as unknown as Api;

    render(<RunView api={api} runId="run-1" />);
    expect(await screen.findByText(/tests failing/)).toBeInTheDocument();
  });
});

// --- 7. the proxy that makes the whole thing route --------------------------

describe("vite dev server configuration", () => {
  const config = readFileSync(resolve(__dirname, "../vite.config.ts"), "utf8");

  it("proxies /v1 to the orchestrator", () => {
    expect(config).toMatch(/["']\/v1["']\s*:/);
    expect(config).toContain("127.0.0.1:8000");
  });

  it("proxies /health to the orchestrator", () => {
    expect(config).toMatch(/["']\/health["']\s*:/);
  });

  it("keeps the client on relative URLs — no host in production logic", () => {
    const client = readFileSync(resolve(__dirname, "../src/api/client.ts"), "utf8");
    expect(client).not.toContain("127.0.0.1");
    expect(client).not.toContain("localhost");
  });
});
