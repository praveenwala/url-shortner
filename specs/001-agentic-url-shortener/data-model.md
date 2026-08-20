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
`wall_clock_ceiling`, `retry_ceiling` (NFR-009), `approved_scope` (`jsonb` — the requirement
references this run is authorised to work within, FR-039), `started_at`, `ended_at`.

**`approved_scope` is the FR-039 boundary.** A task whose `requirement_ref` is absent from it
halts and surfaces for human decision rather than being absorbed into the run. See
*Scope-widening rule* below for how it may change.

**States** (R7): `PLANNING` → `AWAITING_PLAN_APPROVAL` → `EXECUTING` ⇄ `WAITING_FOR_HUMAN`,
with `REPLANNING` enterable from `EXECUTING`, terminating in `COMPLETED`, `FAILED`,
`SAFE_STOPPED`, or `ABANDONED`. `SAFE_STOPPED` is reachable from every non-terminal state
(research R7 correction): a run must always be able to stop safely. `WAITING_FOR_HUMAN` is a persisted state, not a blocked
process — nothing runs while a run sits in it (FR-049), and it never expires into autonomous
execution.

### task_node

`id`, `run_id`, `description`, `requirement_ref` (mandatory — a node without one is refused,
FR-035), `execution_mode` (`agent_authored` | `human_executed`, fixed at planning time and
never escalated, FR-042), `surface` (`shortener` | `orchestrator` | `console` — determines
the agent path allow-list, R6), `declared_inputs`, `declared_outputs` (`jsonb`; explicit
repo-relative artifact paths inside the task's own surface), `is_sync`, `state`, `is_stale`,
`attempt_count`, `timeout_seconds`, `max_attempts`, `backoff_seconds` (FR-030), `result`,
`supersedes` (nullable — the node this one replaces after a selective replan).

**`supersedes` is a link, never a deletion** (FR-033). A replanned node points back at the one
it replaces; the superseded node keeps its state and its result, so "what did we previously
conclude, and why are we redoing it" stays answerable. Combined with `is_stale`, this is what
makes replanning selective rather than destructive: the old node is flagged, not erased, and
the new node is added, not swapped in.

**`declared_outputs` is the agent write allow-list** (FR-041). It is fixed at planning time
and cannot be widened during execution; widening requires replanning, which replaces the node
rather than mutating it. A task may read a module it must not modify, so the read set is
never derived from this field.

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

`id`, `run_id`, `request_id` (the `approval_request` this decides), `checkpoint`,
`human_actor`, `approver_role_held`, `decision` (`approved` | `rejected`), `rationale`,
`decided_at`. An approval from an identity lacking the approver role is rejected and audited
(FR-029, FR-050). No agent-reachable code path writes this table — the agent tool surface
(R6) contains no tool that can, and an agent identity cannot be constructed holding the
approver role at all.

### decision_record

`id`, `run_id`, `alternatives` (`jsonb`), `selection`, `rationale`, `actor`, `decided_at`,
`serves_ref`. Captures decision lineage including human clarification answers (FR-027).

### change_record

`id`, `run_id`, `task_id`, `surface`, `artifact_path`, `execution_mode`, `existed` (whether
the artifact existed before the change — a revert deletes it if not), `prior_state` (what a
revert restores), `prior_sha256`, `new_sha256`, `applied_at`, `approving_human` (nullable;
required where the change crossed a checkpoint).

Every agent-authored change is revertible (FR-044); approval is captured *before* apply,
never after (FR-043). The two hashes are what make revert safe rather than hopeful:
`new_sha256` is compared against the artifact's current content before restoring, so a
rollback refuses to clobber an edit made after the record was written, and `prior_sha256`
verifies what was restored. `run_id` exists so rollback can find a run's changes after a
process restart, when nothing survives in memory.

### approval_request

`id`, `run_id`, `task_ref` (nullable — present when the checkpoint arose from a specific
task), `checkpoint` (`architecture` | `security` | `destructive` | `release` | `governance` |
`scope`), `action_type` (the tool or operation halted, e.g. `write_file`,
`task_out_of_scope`), `detail` (`jsonb` — the action's parameters, excluding proposed file
content), `action_fingerprint` (SHA-256 over the canonicalised detail), `requested_by`,
`state` (`pending` | `decided`), `requested_at`, and the deciding `approval_record`
(referenced by `approval_record.request_id`, resolved at read time rather than duplicated
here) with its `decided_at`.

**`action_fingerprint` is why an approval is not a standing permission.** An approval
authorises exactly the action whose fingerprint it carries. Approving a write to
`specs/…/plan.md` does not authorise a write to `.specify/memory/constitution.md`, and a
second attempt at a different action raises a fresh request. A request can be decided once;
a second decision on the same request is refused.

### rollback_event

`id`, `run_id`, `change_id` (FK → `change_record` — the change this reverses), `outcome`
(`succeeded` | `failed`), `reason` (nullable; populated on failure), `actor`, `occurred_at`.

A rollback is an event in its own right rather than a mutation of the change record, so the
history of an artifact remains readable: what was applied, what was reverted, and what failed
to revert. **A failed rollback is the dangerous case** — the artifact is in neither the prior
nor the intended state — so it safe-stops the run and is audited (`ROLLBACK_FAILED` and
`SAFE_STOP_ROLLBACK_FAILED`) rather than being retried (FR-031, FR-032, FR-044).

### audit_event

`id`, `run_id`, `event_type`, `actor`, `trace_id`, `span_id` (the correlation fields fixed in
`contracts/correlation.md`), `payload` (`jsonb`), `occurred_at`. **Append-only**:
the store layer exposes no update or delete path, and the service role holds `INSERT` and
`SELECT` but not `UPDATE`/`DELETE` on this table — immutability enforced by database
privilege, not only by code (FR-036). Payloads carry no secrets or personal data (FR-038).

### clarification_request

`id`, `run_id`, `requirement_id` (the requirement being clarified), `question`, `affects`
(`scope` | `security` | `user_visible_behaviour`), `rule` (which ambiguity rule fired),
`round`, `requested_by`, `requested_at`, `state` (`pending` | `answered`), `answer`,
`answered_by`, `answered_at`.

Kept separate from `approval_request` because the two decide different things: an approval
decides a proposed *action*, a clarification answers a *question*. Conflating them would make
"approve" mean two things.

**The answer is persisted before the run resumes** (FR-046, FR-049). Recording it and leaving
`WAITING_FOR_HUMAN` are separate steps, so a lost write cannot resume a run that was never
actually clarified. `round` bounds the loop: after three rounds the run safe-stops rather than
asking forever (Principle VII). `requirement_id` is what lets a later run see that a question
was already asked and answered.

### change_request

`id`, `run_id`, `prior_requirement_id` (FK → `requirement` — the requirement being changed),
`text` (the new or amended requirement), `reason` (**why replanning was triggered**),
`submitted_by`, `submitted_at`, `state` (`submitted` | `analysed` | `awaiting_approval` |
`replanned`).

Distinct from `requirement` on purpose: a change request is an *event against an existing
run*, carrying the trigger and the link to what came before. Recording `reason` separately
from `text` is what lets a reviewer see why a replan happened without inferring it from the
diff between two requirement texts.

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

## Scope-widening rule (FR-039)

Recorded here because `approved_scope` is a column whose *mutation path* is the control, not
the value itself.

1. **Scope may be widened only through an approved `SCOPE` approval request.** An out-of-scope
   task raises a `SCOPE` checkpoint, the run halts, and a human decides.
2. **A rejected scope request does not modify `approved_scope`.** Attempting to widen from a
   rejected request is refused.
3. **Direct or operator mutation of `approved_scope` outside the approval flow is
   prohibited.** The column is written by the approval path and by initial run setup; nothing
   else may edit it. A run must never widen its own scope.
4. **Repeated out-of-scope attempts stay blocked** until a new approved scope decision exists.
   Raising the checkpoint again is the correct behaviour, not an error to suppress — silently
   absorbing the work is exactly the FR-039 failure.

## Console state

None. The console persists nothing and derives every displayed value from an orchestrator API
response (FR-048, R5). Any client-side cache is ephemeral view state discarded on reload; the
server is re-read, never reconciled against.
