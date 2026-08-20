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
| Submit requirement | `POST /v1/requirements` **(deferred)** | Submit natural-language requirement; returns the recorded interpretation and any ambiguities *before* tasks exist | FR-020, FR-028 |
| Get run | `GET /v1/runs/{id}` | Run state, what it waits on, ceilings, timings | FR-025, FR-049 |
| Get graph | `GET /v1/runs/{id}/graph` | Nodes with state, staleness, execution mode; edges; sync nodes | FR-021–FR-024, FR-042 |
| List gates | `GET /v1/runs/{id}/gates` | Every entry/exit evaluation with outcome and reason | FR-026 |
| List pending requests | `GET /v1/runs/{id}/pending` | Open approval and clarification requests | FR-029, FR-046 |
| Record approval | `POST /v1/runs/{id}/approvals/{request_id}` | Approve or reject a checkpoint, with rationale | FR-029, FR-043, FR-046, FR-050 |
| Answer clarification | `POST /v1/runs/{id}/clarifications/{request_id}` | Human answer that resumes planning | FR-028, FR-046 |
| Decision lineage | `GET /v1/runs/{id}/decisions` | Alternatives, selection, rationale, actor | FR-027 |
| Audit trail | `GET /v1/runs/{id}/audit` | Append-only event stream for the run | FR-036 |
| Traceability | `GET /v1/trace?requirement=…` / `?change=…` | Both directions of the trace | FR-034 |
| Metrics | *(no separate route — served inside `GET /v1/runs/{id}`)* | Success rate, retry frequency, rollback frequency, MTTR, end-to-end latency — per run and across runs | FR-037, FR-047 |
| List runs | `GET /v1/runs` | Runs with state and requirement summary | FR-045 |
| Health | `GET /health` | Liveness; carries no run data | NFR-007 |
| Console assets | static build | React + TypeScript SPA consuming exactly the routes above | FR-045 |

## Reconciliation with the generated OpenAPI (T030, 2026-08-20)

The document generated from the running application is
[`docs/contracts/orchestrator-openapi.json`](../../../docs/contracts/orchestrator-openapi.json),
produced by `orchestrator/scripts/generate_openapi.py`. Every difference found against this
contract is recorded below with the reason it was resolved the way it was. The table above has
been amended where the contract was behind the approved implementation — annotated here rather
than changed silently.

| Difference | Category | Resolution |
|-----------|----------|-----------|
| `POST /v1/requirements` declared, not implemented | **intentionally deferred** | Checkpoint 2f scoped the API to what the two console views need; requirements are submitted through the orchestration services, not HTTP. Marked *(deferred)* above rather than removed |
| `GET /v1/metrics` declared; metrics served inside `GET /v1/runs/{id}` | **contract drift** | The US6 instruction was to expose metrics through the existing run API and add no screen. The implementation is correct; the contract predated the decision and is corrected above |
| Approval and clarification routes carry `{request_id}` in the path | **contract drift** | The 2f implementation binds a decision to one request in the path, which is what makes "an approval covers exactly one action" enforceable at the route. Reviewed and accepted at 2f; the contract is corrected above |
| `GET /v1/trace?requirement=…` declared; implemented as `GET /v1/runs/{id}/trace` | **implementation bug** | **Fixed.** The route now lives at `/v1/trace` and accepts `requirement`, `change`, or `run`, as the approved contract says. Nothing called the old path |
| Generated document described no error envelope — only FastAPI's 422 | **implementation bug** | **Fixed.** `ApiErrorBody` is declared as the response model for 400/401/403/404/409 on every fallible route, so the published document states the stable `{error, message}` envelope a client branches on |
| `GET /v1/runs` and `GET /health` implemented, undeclared | **additive compatible** | Documented above. Neither changes an existing shape |
| Path parameter named `{run_id}` where the contract writes `{id}` | **cosmetic** | Not changed. The parity check normalises parameter names, comparing structure rather than spelling |

**Parity is enforced automatically.** `orchestrator/tests/contract/test_openapi_parity.py`
regenerates the document from the live application and fails if it drifts from either this
contract or the committed artifact, so the next divergence breaks the build rather than being
discovered by a reader.

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
