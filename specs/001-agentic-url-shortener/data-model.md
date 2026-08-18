# Phase 1 Data Model: Agentic URL Shortener

**Feature**: 001-agentic-url-shortener | **Date**: 2026-08-18 (revised)

**PostgreSQL, two databases, two credentials** (R3). `shortener_db` is owned by the Java
service; `orchestrator_db` is owned by the Python service. No foreign key, join, view, or
query crosses the boundary, and neither service's credential can read the other's database.
Correlation across the boundary, where ever needed, is by opaque identifier carried in an
audit payload — never by a database reference.

---

## `shortener_db` — owned by the Java shortener

### short_link

| Column | Type | Rules |
|--------|------|-------|
| `code` | `text` PK | 7 chars from the 62-symbol alphabet (FR-004). Unique across all codes ever issued — enforced by the primary key, not by application logic; collisions surface as unique violations and are bounded-retried (R12). *Custom aliases (FR-005) are a `DEFERRED_APPROVED` design extension — the column accommodates them, but alias validation and conflict handling are not part of the 2–3 day baseline* |
| `destination` | `text` | Absolute `http`/`https` URL, length-bounded (FR-001, FR-003). Stored exactly as it will be redirected to (FR-007) |
| `destination_canonical` | `text` | Normalised form, for comparison only — never the redirect target (FR-011) |
| `client_id` | `text` | Creating client credential; scopes analytics access (FR-014) and rate limiting (FR-015) |
| `created_at` | `timestamptz` | |
| `expires_at` | `timestamptz` NULL | Absolute point in time; null means "until revoked" (FR-008) |
| `revoked_at` | `timestamptz` NULL | Non-null means resolution must refuse (FR-012) |
| `redirect_count` | `bigint` | Cumulative; never decremented when events age out (FR-013) |
| `first_redirect_at` | `timestamptz` NULL | Life-of-link; survives event expiry (FR-014) |
| `last_redirect_at` | `timestamptz` NULL | Life-of-link; survives event expiry (FR-014) |

**Validation** (Bean Validation at the Spring boundary): scheme allow-list `http`/`https`
only, rejecting `javascript:`, `data:`, `file:`, `ftp:`, relative and scheme-relative forms
(FR-002). Reserved paths cannot be claimed as codes (FR-006). Alias characters outside the
alphabet are refused as malformed (FR-005).

**Lifecycle**: `active` → `expired` (when `expires_at` passes) or `revoked` (when
`revoked_at` is set). Both are terminal for resolution; neither deletes the row, because
analytics outlive resolvability. Resolution outcomes are distinct per state (FR-009).

**Counters vs. events**: `redirect_count`, `first_redirect_at`, and `last_redirect_at` are
denormalised onto the link precisely so 90-day event retention cannot alter reported totals.
This is the mechanism behind SC-006's "count unchanged after events age out".

**Concurrency**: the redirect path is one indexed primary-key lookup plus a counter update,
expressed through the single Spring Data JPA persistence model (R4). PostgreSQL row-level
locking means concurrent increments on *different* links never serialise against each other —
the property R3 selected the store for, and the reason Testcontainers rather than an
in-memory database is used in tests (R10).

**Transaction boundary** (R14): the counter update and the redirect-event insert commit in the
**same transaction as the redirect resolution**, and that transaction commits **before** the
redirect response is issued. Exactness (SC-006) follows from ordering rather than from
reconciliation: a redirect whose count cannot be durably recorded is not served and not
counted, so the two can never disagree.

### redirect_event

| Column | Type | Rules |
|--------|------|-------|
| `id` | `bigserial` PK | Stable ordering key for the paginated contract (FR-014) |
| `code` | `text` FK → `short_link` | |
| `occurred_at` | `timestamptz` | Only successful redirects are recorded; refused resolutions are not (US5 scenario 4) |

**Retention**: 90 days, after which rows are removed while counters persist (FR-013). A
history request whose events have all aged out returns an empty page alongside a truthful
non-zero summary.

**Retention mechanism** (R14, simplified): a **simple indexed table**, with ageing out
performed as a chunked, off-peak `DELETE`. Range partitioning was removed as schema ceremony at
this scale; the residual risk — a long sweep taking locks on the hot write path — is documented
rather than designed away, and partitioning remains available as a brownfield migration if
measurement demands it.

**Indexes**: `(code, id)` for stable-ordered pagination and for the retention sweep;
`(expires_at)` on `short_link` for expiry sweeps.

**Connection pools** (R14): the redirect path and the analytics *serving* endpoints draw from
**separate pools**. A heavy or pathological history query is then unable to starve the pool
the redirect path depends on — the second concrete way analytics could otherwise take
redirects down.

### rate_limit_window — `DEFERRED_APPROVED`

**Not part of the 2–3 day implementation baseline.** This is a documented design extension,
retained so FR-015 can be built without redesign; no migration and no task exist for it (plan
§ Delivery Scope, tasks.md § Deferred Capabilities).

Per-credential sliding window counters (R8: 60 creations/minute, burst 10). Held here rather
than in a cache because R13 excludes Redis from the greenfield architecture; the row is small,
the access pattern is per-request on the *creation* path only, and the redirect path never
touches it.

---

## `orchestrator_db` — owned by the Python orchestrator

### requirement

`id`, `submitted_text`, `interpretation` (`jsonb` — scope, actors, constraints, recorded
before any task exists, FR-020), `ambiguities` (`jsonb`, each a specific answerable
question, FR-028), `resolution_state`, `submitted_by`, `submitted_at`.

### workflow_run

`id`, `requirement_id`, `state`, `waiting_on` (nullable — which approval or clarification),
`wall_clock_ceiling`, `retry_ceiling` (NFR-009), `started_at`, `ended_at`.

**States** (R7): `PLANNING` → `AWAITING_PLAN_APPROVAL` → `EXECUTING` ⇄ `WAITING_FOR_HUMAN`,
with `REPLANNING` enterable from `EXECUTING`, terminating in `COMPLETED`, `FAILED`,
`SAFE_STOPPED`, or `ABANDONED`. `WAITING_FOR_HUMAN` is a persisted state, not a blocked
process — nothing runs while a run sits in it (FR-049), and it never expires into autonomous
execution.

### task_node

`id`, `run_id`, `description`, `requirement_ref` (mandatory — a node without one is refused,
FR-035), `execution_mode` (`agent_authored` | `human_executed`, fixed at planning time and
never escalated, FR-042), `surface` (`shortener` | `orchestrator` | `console` — determines
the agent path allow-list, R6), `inputs`, `outputs`, `state`, `is_stale`, `attempt_count`,
`timeout`, `max_attempts`, `backoff` (FR-030), `fallback`, `rollback_ref`.

**States** (R7): `PENDING` → `READY` → `RUNNING` → `SUCCEEDED` | `FAILED` | `ROLLED_BACK` |
`SKIPPED`. `is_stale` is a flag orthogonal to state, so a stale-but-succeeded node keeps the
result replanning may still consult (FR-033).

**`surface` is a security field, not a label**: it is what scopes the agent's write
allow-list to one language surface. A task spanning two surfaces is an architectural change
and requires an approval checkpoint (R6).

### task_dependency

`run_id`, `from_node`, `to_node`. The edge set is validated acyclic before execution starts;
a cycle rejects the plan rather than deadlocking at runtime (FR-022). Readiness is "all
predecessors terminal" (FR-023).

### sync_node

A `task_node` with `is_sync = true`. It records each inbound branch's terminal outcome and
releases downstream work only when every branch has reached one — including when a sibling
failed while another succeeded (FR-024, and the matching edge case).

### gate

`id`, `run_id`, `stage`, `kind` (`entry` | `exit`), `criteria`, `outcome`, `reason`,
`evaluated_at`. Every evaluation is recorded, pass or fail (FR-026).

### approval_record

`id`, `run_id`, `checkpoint`, `human_actor`, `approver_role_held`, `decision`, `rationale`,
`decided_at`. An approval from an identity lacking the approver role is rejected and audited
(FR-029, FR-050). No agent-reachable code path writes this table — the agent tool surface
(R6) contains no tool that can.

### decision_record

`id`, `run_id`, `alternatives` (`jsonb`), `selection`, `rationale`, `actor`, `decided_at`,
`serves_ref`. Captures decision lineage including human clarification answers (FR-027).

### change_record

`id`, `task_id`, `surface`, `artifact_path`, `execution_mode`, `prior_state` (what a revert
restores), `applied_at`, `approving_human` (nullable; required where the change crossed a
checkpoint). Every agent-authored change is revertible (FR-044); approval is captured
*before* apply, never after (FR-043).

### audit_event

`id`, `run_id`, `event_type`, `actor`, `payload` (`jsonb`), `occurred_at`. **Append-only**:
the store layer exposes no update or delete path, and the service role holds `INSERT` and
`SELECT` but not `UPDATE`/`DELETE` on this table — immutability enforced by database
privilege, not only by code (FR-036). Payloads carry no secrets or personal data (FR-038).

### replan_event

`id`, `run_id`, `trigger`, `blast_radius` (`jsonb` — the node set computed from the
dependency closure), `nodes_marked_stale`, `graph_delta`, `occurred_at` (FR-033).

### trace_link

`requirement_ref`, `task_ref`, `change_ref`, `test_ref`. Queried in both directions:
requirement → tasks/changes/tests, and change → originating requirement (FR-034).

---

## Derived metrics

Not stored; computed from the tables above per R11. Success rate and retry/rollback frequency
come from `workflow_run` and `task_node`; MTTR and end-to-end latency come from `audit_event`
timestamps with time in `WAITING_FOR_HUMAN` excluded and reported separately.

## Console state

None. The console persists nothing and derives every displayed value from an orchestrator API
response (FR-048, R5). Any client-side cache is ephemeral view state discarded on reload; the
server is re-read, never reconciled against.
