# Contract: Orchestrator API and Console

**Service**: `orchestrator` | **Version**: v1 | **Feature**: 001-agentic-url-shortener

**Implementation**: Python 3.13. The console is a separate React + TypeScript application
(static assets, no server of its own) that consumes this API.

Everything the console displays is retrievable here (FR-048) — the console derives every
displayed value from these responses and holds no workflow state of its own. That constraint
is what keeps demonstration runs verifiable headlessly.

## Operations

| Operation | Route | Purpose | Serves |
|-----------|-------|---------|--------|
| Submit requirement | `POST /v1/requirements` | Submit natural-language requirement; returns the recorded interpretation and any ambiguities *before* tasks exist | FR-020, FR-028 |
| Get run | `GET /v1/runs/{id}` | Run state, what it waits on, ceilings, timings | FR-025, FR-049 |
| Get graph | `GET /v1/runs/{id}/graph` | Nodes with state, staleness, execution mode; edges; sync nodes | FR-021–FR-024, FR-042 |
| List gates | `GET /v1/runs/{id}/gates` | Every entry/exit evaluation with outcome and reason | FR-026 |
| List pending requests | `GET /v1/runs/{id}/pending` | Open approval and clarification requests | FR-029, FR-046 |
| Record approval | `POST /v1/runs/{id}/approvals` | Approve or reject a checkpoint, with rationale | FR-029, FR-043, FR-046, FR-050 |
| Answer clarification | `POST /v1/runs/{id}/clarifications` | Human answer that resumes planning | FR-028, FR-046 |
| Decision lineage | `GET /v1/runs/{id}/decisions` | Alternatives, selection, rationale, actor | FR-027 |
| Audit trail | `GET /v1/runs/{id}/audit` | Append-only event stream for the run | FR-036 |
| Traceability | `GET /v1/trace?requirement=…` / `?change=…` | Both directions of the trace | FR-034 |
| Metrics | `GET /v1/metrics` | Success rate, retry frequency, rollback frequency, MTTR, end-to-end latency — per run and across runs | FR-037, FR-047 |
| Console assets | static build | React + TypeScript SPA consuming exactly the routes above | FR-045 |

## Contract rules

1. **Approval authority**: an approval is accepted only from a holder of the approver role,
   and that identity must be one no agent can act under. An attempt from an agent-available
   identity is rejected *and audited* (FR-029, FR-050). An agent can never write an approval.
2. **Approve before apply**: a checkpoint-crossing change halts for approval before it is
   applied. The approval endpoint gates the change; it does not ratify one already made
   (FR-043).
3. **Waiting is a state, not a process**: while a run is `WAITING_FOR_HUMAN`, no agent loop,
   retry timer, or polling cycle is active, the state survives restart, and it never expires
   into autonomous execution (FR-049). Clients poll the API; the run does not poll anything.
4. **Console parity — four rules** (R5). The console is a view, not a source of truth:
   (a) every field it renders is present in a response above — a view with no API counterpart
   is a defect; (b) it keeps no durable client-side workflow store, and any query cache is
   ephemeral view state discarded on reload; (c) graph *layout* may be computed client-side
   as presentation, but graph *content* — nodes, edges, states, staleness, execution mode —
   comes from `GET /v1/runs/{id}/graph` and is never inferred locally; (d) every console test
   assertion has an API-level counterpart, so any run is verifiable headlessly (FR-048,
   SC-020).
7. **No optimistic writes**: approval and clarification submissions are confirmed by
   re-reading the run, never by locally assuming success. An approval that appears in the UI
   but not in `audit` would be a second source of truth.
5. **Audit immutability**: the audit endpoint is read-only and append-only at the store
   layer; there is no update or delete route (FR-036).
6. **No secrets**: audit, decision, and metric payloads exclude secrets and personal data
   (FR-038, SC-015).
