# Quickstart: Validating the Agentic URL Shortener

**Feature**: 001-agentic-url-shortener | **Date**: 2026-08-18 (revised)

How to run the deliverable and prove it satisfies the spec. Each scenario names the
requirements and success criteria it validates. Contracts are in
[contracts/](./contracts/); entity detail is in [data-model.md](./data-model.md).

> Nothing here exists yet — this is the validation guide the implementation must satisfy,
> written before the code per Constitution Principle IV. The architecture it assumes was
> **approved on 2026-08-18** (plan.md, Architecture Approval Record; Gate II cleared).
>
> Implementation is scoped to a 2–3 day budget (tasks.md § Deferred Capabilities). Steps for
> deferred capabilities — custom aliases, rate limiting, paginated event history, the retention
> sweep — have been removed from the scenarios below or marked **(DEFERRED)** inline. What
> remains is what the implementation is actually expected to demonstrate.

## Prerequisites

- **Java 21** and a JDK toolchain (shortener)
- **Python 3.13** (orchestrator)
- **Node 20+** (console build)
- **PostgreSQL 16** with two databases and two roles: `shortener_db` / `orchestrator_db`,
  each reachable only by its own service's credential (R3). The orchestrator's role holds
  `INSERT`/`SELECT` but not `UPDATE`/`DELETE` on `audit_event` — audit immutability is a
  database privilege, not only application code
- **Docker** for Testcontainers-backed integration tests (R10)
- An Anthropic API credential in the environment for scenarios 4–7 — never in source, never
  in a fixture (NFR-006). Scenarios 1–3 need no credential
- Orchestrator process egress restricted to the configured Claude endpoint, so scenario 7's
  network-confinement checks are meaningful (R6)
- An identity holding the **approver role**, distinct from any identity agents run under
  (FR-050)

## Setup

Apply migrations to both databases, start the two backend services as separate processes,
and serve the console's static build against the orchestrator API. The services share
nothing at runtime and hold different database credentials — that separation is what
scenario 3 tests.

## Test layers

Four separately-runnable obligations per Principle IV, in each stack's idiom (R10):

| Surface | Unit | Integration | Workflow | Failure-path |
|---------|------|-------------|----------|--------------|
| Shortener (Java) | JUnit 5 | `@SpringBootTest` + Testcontainers PostgreSQL | — | Induced faults |
| Orchestrator (Python) | `pytest` | `pytest` + `httpx` + Testcontainers PostgreSQL | Full runs, stubbed agent runtime | Timeout, retry exhaustion, rollback, safe-stop |
| Console (TS) | Vitest | RTL against a mocked API | — | Error/empty/loading states |

Integration tests run against **real PostgreSQL via Testcontainers**, never an in-memory
substitute — the store was chosen for its locking semantics (R3), and testing against a
different engine is how concurrency bugs survive to release.

The full suite must pass before any scenario below counts as demonstrated.

---

## Scenario 1 — Shorten and follow a link

Create a link from an `https` destination, follow it in a browser, land on the destination.
Then confirm each refusal is distinct: a `javascript:` destination, a malformed URL, an
over-long URL, an unknown code, an expired code, a revoked code. *(Custom-alias conflict is
**DEFERRED** — FR-005 is designed, not built.)*

**Validates**: FR-001–FR-012, FR-016 · SC-001, SC-003, SC-004

**Watch for**: the redirect must be temporary and non-cacheable. If a second follow does not
reach the service, the count drifts and SC-006 fails.

---

## Scenario 2 — Analytics and retention

Follow one link several times. Confirm the summary reports total redirects, first redirect
timestamp, and most recent redirect timestamp, and that the counts match exactly what was
performed. Request analytics as a different client and confirm refusal.

*(**DEFERRED**: paginated event-history validation and aged-out retention verification — the
history half of FR-014 and the retention half of FR-013 are designed, not built. The counters
are denormalised onto the link precisely so retention cannot alter them, which is what the
deferred test would have confirmed.)*

**Validates**: FR-013 (counters), FR-014 (summary) · SC-006

---

## Scenario 3 — Redirect independence

With everything running, stop the orchestrator. Confirm redirects continue to resolve and
counts continue to increment. Restart it and confirm no redirect data was lost.

Then the stronger form the two-database split enables: confirm the shortener's credential
cannot read `orchestrator_db` and the orchestrator's cannot read `shortener_db`.

**Validates**: NFR-002, NFR-003, NFR-006

Then verify analytics cannot take redirects down (R14, NFR-002) — three checks:

1. **Serving isolation**: issue a deliberately heavy event-history query (large page count
   against a link with many events) while redirects run. Redirect latency must stay inside
   NFR-001; the separate connection pool is what makes this hold.
2. **Retention sweep isolation** — *(**DEFERRED**)*: the sweep is not built in this scope.
   When it is, run it under redirect load as a chunked off-peak delete and confirm redirects do
   not degrade. Range partitioning was removed from the design, so this risk is mitigated by
   chunking and documented rather than eliminated structurally (R14).
3. **Recording coupling — the approved trade-off**: force the analytics write to fail while
   reads still succeed. The redirect returns a failure rather than an uncounted redirect. This
   is the deliberate, **approved** consequence of committing the count before serving (R14):
   exact accounting is part of successful redirect processing. Confirm the counter and the
   served-redirect count agree exactly — no redirect served uncounted, no count recorded for
   an unserved redirect. Per the approver's NFR-002 ruling, this failure mode is a recorded
   availability trade-off, not a defect.

**Why it matters**: scenario 3 is the single test justifying the two-service, two-database
split in the plan's Complexity Tracking. If it cannot be demonstrated, that complexity is
unjustified under Principle XI. Checks 1 and 2 are what NFR-002 means under the approved
interpretation — independence from the analytics-serving and orchestration surfaces. Check 3
documents the accepted trade-off at the other edge.

---

## Scenario 4 — Greenfield run (demonstration 1)

Submit "provide short-link creation and resolution" to the orchestrator. Before any task
exists, confirm a written interpretation with scope, actors, constraints, and ambiguities.
In the console, inspect the graph: acyclic, declared dependencies, an execution mode and a
surface on every node. Watch two independent tasks run concurrently and a synchronisation
node wait for both. Approve the architecture checkpoint when it halts. On completion, trace
any change back to its requirement and forward to its validating test.

**Validates**: FR-020–FR-027, FR-034, FR-041–FR-048 · SC-007, SC-008, SC-009, SC-020

**Also test**: interrupt mid-execution and resume. No completed task may re-run and no
transition may be lost (SC-012).

**Console parity check**: for every panel the console shows, assert the same values from the
API directly. They must agree, and the run must be fully reviewable with the console closed.

---

## Scenario 5 — Ambiguous requirement (demonstration 3)

Submit a requirement whose scope is genuinely undetermined — "make the links smarter".
Confirm **zero** implementation tasks and **zero** code changes, that recorded ambiguities
are specific answerable questions, and that the run sits in `WAITING_FOR_HUMAN`. Leave it
waiting across a process restart: state and pending request must survive, and no compute may
be attributable to the run while it waits. Answer through the console and confirm planning
resumes with your answer in the decision lineage, attributed to you.

**Validates**: FR-028, FR-046, FR-049 · SC-010, SC-021

**This is the safety demonstration.** A system that guesses here has failed regardless of how
well it performs elsewhere.

---

## Scenario 6 — Brownfield enhancement and replanning (demonstration 2)

With the shortener in place, submit an enhancement targeting redirect responsiveness or
reliability. Confirm the plan references existing components rather than rebuilding. Partway
through, change an upstream decision. Confirm the system reports the blast radius, marks only
downstream artifacts stale, re-plans that subgraph alone, and leaves unaffected completed
nodes with their results intact. Confirm the replan and its blast radius appear in the audit
trail.

**Validates**: FR-033, FR-044 · SC-011, SC-018

**Also test**: revert an agent-authored change and confirm the prior state is restored
exactly.

**The measurement discipline this scenario is built to exercise** (R13): the greenfield
architecture deliberately ships **without a cache**, so this enhancement has real work to do.
The run must *measure* the current redirect path before proposing a change, and any proposal
to introduce Redis must clear three conditions — p95 exceeds the NFR-001 budget at the
NFR-005 operating point; profiling attributes the excess to datastore access rather than
application or network time; and the cache design preserves FR-008 expiry, FR-012 revocation,
and SC-006 exact counts. Introducing a datastore is an architecture decision, so it halts for
human approval (FR-029) regardless of what the measurements say. If the conditions are not
met, the correct outcome is a different enhancement — connection pooling, index shape, or the
counter write pattern — and demonstrating *that* judgement is worth more than demonstrating a
cache.

---

## Scenario 7 — Reliability, audit, egress, and agent confinement

After several runs including at least one failure and one rollback, request the metrics and
confirm each agrees with the observed runs — human wait time excluded from MTTR and
end-to-end latency, and reported separately. Reconstruct any completed run from its audit
trail alone. Confirm the console and the API report identical state. Grep the audit trail,
logs, and metrics for secrets and personal data — there must be none. Attempt an `UPDATE` on
`audit_event` with the orchestrator's own credential and confirm the database refuses it.

Then confirm the agent capability model holds (R6, FR-041–FR-044):

- An agent task attempting to write outside its declared path allow-list is refused.
- An agent task on the `shortener` surface cannot write under `orchestrator/` or `console/`.
- There is no tool by which an agent can run a shell command, install a package, or touch git.
- **Network confinement** (R6): no agent tool accepts a URL, host, or port; server-side web
  search, web fetch, and code execution are not declared in any request; and process egress
  from the orchestrator reaches only the configured Claude endpoint. Confirm by inspecting the
  declared tool set and by monitoring egress during an agent-executing run — the Claude
  endpoint should be the only destination that appears.
- A change crossing an approval checkpoint halts **before** it is applied, not after.

Finally, monitor network egress across the entire corpus and confirm **zero** outbound
requests to caller-supplied destinations.

**Validates**: FR-018, FR-036–FR-038, FR-041–FR-044, FR-048 · SC-013, SC-014, SC-015, SC-017,
SC-018, SC-019

---

## Load verification

Separately invoked, not part of the default suite: 100 redirects/second sustained against
100,000 stored links, PostgreSQL only, no cache, one persistence model, platform-default
thread model. 95% within 150 ms, 99% within 400 ms.

**Run two traffic shapes, not one.** Uniform traffic across the corpus exercises the general
path; **skewed traffic concentrated on a few very hot links** exercises per-link counter-write
contention, which is a recorded measurable risk (plan § Recorded risks). Report both. If the
skewed profile misses NFR-001 while the uniform one passes, contention is the finding — and it
becomes a brownfield candidate on R13's ladder rather than something to have pre-optimised.

**Validates**: NFR-001, NFR-005 · SC-002

This run also produces the baseline that scenario 6's brownfield enhancement measures against.
Run it on the greenfield configuration deliberately — no virtual threads, no JDBC
specialisation, no cache — because each of those is a brownfield lever that must be justified
by *this* measurement rather than assumed in advance (R4, R13). If the baseline meets NFR-001,
the correct brownfield outcome may be reliability work rather than performance work.
