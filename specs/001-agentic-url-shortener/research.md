# Phase 0 Research: Agentic URL Shortener

**Feature**: 001-agentic-url-shortener | **Date**: 2026-08-18 (revised) | **Spec**: [spec.md](./spec.md)

**Status: approved.** The requirement owner approved this architecture on 2026-08-18 under
Constitution Principle II; the decision, approver, and rationale are recorded in the
Architecture Approval Record in [plan.md](./plan.md), where **Gate II is cleared**. Future
changes to any decision below require their own approval checkpoint (FR-029).

**Revision note**: R1, R3, R4, R5, and R10 were replaced after the requirement owner
rejected the first architecture. R13 is new. R2, R6–R9, R11, and R12 carry forward with the
adjustments noted in each. **Revision 3** simplifies R4 (single persistence model, virtual
threads demoted to optional configuration), sharpens R6's network boundary, and adds R14
(analytics recording versus NFR-002). **R3a** records the orchestrator's database access
layer (SQLAlchemy Core) as an implementation-level dependency — it changes no approved
architecture decision.

---

## R1 — Language boundary (polyglot)

**Decision**: Java 21 + Spring Boot 3 for the shortener workload. Python for the
orchestration service. TypeScript + React for the console. The boundary between Java and
Python falls exactly on the service boundary NFR-002 already requires.

**Rationale**: The two halves of this deliverable are being judged for different things.

The **workload** is the production artifact — it must demonstrate Java/Spring engineering:
layered services, bean validation at the boundary, JPA/JDBC persistence, Actuator
observability, and the JUnit 5 + Testcontainers testing idiom. Writing it in Python would
satisfy every functional requirement while failing the exercise's actual purpose.

The **orchestration service** is where AI-specific tooling lands, and that tooling is
Python-centric in practice: the `anthropic` SDK's beta tool runner with per-turn hooks
(which FR-043's approve-before-apply requirement leans on directly), task budgets for
NFR-009, and the surrounding evaluation and prompt-iteration ecosystem. Graph and state
manipulation for the DAG is also more concise here, which matters because the orchestrator
is the part most likely to be read closely.

**Why polyglot beats either single-language option**:

- *All Java* is genuinely feasible — the Anthropic Java SDK supports the tool runner, so
  nothing in FR-041–FR-044 is blocked. It is rejected because the AI-side iteration loop
  (prompt tuning, eval harnesses, stub construction for the workflow test layer) is slower
  and less idiomatic in Java, for no gain: the orchestrator is not the artifact whose Java
  engineering is being assessed.
- *All Python* is rejected outright: it would leave the exercise with no Java/Spring
  workload, which is the one thing the brief asks the production half to demonstrate.

**Why the polyglot cost is bounded**: the usual objection to two languages is a shared
codebase with two toolchains and a fractured dependency story. That does not arise here,
because the seam already exists for an unrelated reason. NFR-002 requires the shortener and
orchestrator to be independently runnable with no runtime dependency between them, so they
were never going to share code — only contracts. The polyglot boundary lands on a seam the
requirements already forced, rather than cutting a new one through the middle of a component.
The costs that remain are real and accepted: two CI paths, two dependency ecosystems, two
sets of reviewer expectations, and an agent capability model that must be scoped per
language (R6).

**Alternatives considered**: Kotlin for the workload (same JVM ecosystem, but Java is what
the exercise names); Java orchestrator with a Python sidecar for agent calls only (rejected —
a network hop and a serialisation boundary inside one logical component, which is worse than
either clean option).

---

## R2 — Service topology

**Decision**: Two independently runnable backend services — `shortener` (Java) and
`orchestrator` (Python) — plus the console as a separately built static frontend served
against the orchestrator API. No runtime dependency from `shortener` to `orchestrator`.

**Rationale**: Unchanged and reaffirmed by the requirement owner. NFR-002 requires the
redirect path to survive degradation or outage of the analytics and orchestration surfaces.
A single process can assert that; only separate processes can demonstrate it, by the direct
test of stopping the orchestrator and observing redirects continue (quickstart scenario 3).
This is the demonstrated requirement Principle XI demands before an additional service is
introduced.

**Adjustment from the previous revision**: the console is now a third build artifact rather
than a set of routes inside the orchestrator (R5). It is not a third *service* — it is
static assets with no server of its own and no state of its own.

**Alternatives considered**: single process with modular internals (cannot demonstrate
NFR-002); three backend services with the console as its own server (rejected — the console
holds no state, so a server for it would exist only to proxy).

---

## R3 — Persistence

**Decision**: PostgreSQL, with **separate databases and separate credentials** for the two
services — `shortener` owns its data, `orchestrator` owns its own, and no foreign key,
join, or query crosses the boundary. Neither service's credential can read the other's data.

**Rationale**:

**Write concurrency** is the deciding factor. The redirect path increments a per-link
counter on every successful resolution (FR-013) at the NFR-005 operating point of 100
redirects/second, concurrently with link creation. Separately, FR-025 requires the
orchestrator to persist state at *every* transition, and FR-023/FR-024 mean several task
nodes are executing — and therefore writing — at once. Both workloads are concurrent-write
shaped. PostgreSQL gives row-level locking and true concurrent writers; MVCC means the
counter increments do not serialise against unrelated writes.

**Durability** (NFR-003) requires that nothing acknowledged is lost across restart.
PostgreSQL's WAL with synchronous commit makes that a configuration guarantee rather than a
hope, and it leaves a credible path to replication if this ever ran for real.

**Ownership boundaries** (NFR-006, least privilege): separate databases with separate roles
mean the orchestrator physically cannot read link data and the shortener physically cannot
read audit records. This also keeps the NFR-002 independence honest — orchestrator write
load and lock contention cannot reach the redirect path, because they are not in the same
database.

**Alternatives considered**:

- *SQLite (the previously proposed simpler alternative)* — **rejected.** It is the right
  choice for a single-writer embedded workload, and it would have satisfied NFR-003 in the
  narrow sense. Two concurrency properties defeat it here. First, SQLite serialises writers
  at the database level: even in WAL mode, exactly one write transaction proceeds at a time,
  so concurrent redirect-counter increments and concurrent workflow-state transitions
  queue behind each other and surface as `SQLITE_BUSY` under contention rather than as
  throughput. Second, its durability story depends on filesystem `fsync` behaviour that
  varies by platform, which is a weak foundation for a requirement stated as absolutely as
  NFR-003. A spec that calls itself production-oriented and commits to 100 writes/second
  should not be defended by a store whose answer to concurrent writers is a retry loop.
- *MySQL/MariaDB* — comparable; PostgreSQL chosen for stricter default isolation semantics
  and better JSON handling for audit payloads.
- *One PostgreSQL database with two schemas* — simpler to operate, rejected because a single
  credential spanning both schemas weakens the least-privilege boundary and re-introduces
  shared lock and connection-pool pressure across the NFR-002 seam.

---

## R3a — Orchestrator database access layer (SQLAlchemy Core)

**Recorded 2026-08-18, after implementation of checkpoints 2a–2c surfaced the dependency.**

**Decision**: The Python orchestrator accesses PostgreSQL through **SQLAlchemy Core** — the
expression/connection layer only — over `psycopg` as the driver. The Java shortener continues
to use Spring Data JPA (R4). Both target the same approved datastore.

**Scope of this record — what it is, and what it is not**:

- **SQLAlchemy Core only, not the ORM.** No declarative models, no mapped classes, no session
  or identity map, no lazy loading, no ORM-managed unit of work. The store layer issues
  explicit SQL through `text()` against an engine; migrations remain hand-written SQL. Core is
  used for connection and transaction management and for parameter binding, nothing more.
- **PostgreSQL remains the approved datastore.** R3 is unchanged: two databases, two
  credentials, no cross-database reference, and the concurrency and durability reasoning that
  selected PostgreSQL over SQLite stands exactly as written.
- **`psycopg` remains the underlying driver.** SQLAlchemy Core sits above it; it does not
  replace it, and the DSN, driver behaviour, and connection semantics are unchanged.
- **No new service and no new persistence boundary.** Nothing is added to the topology, no
  data moves, no ownership boundary shifts, and the shortener/orchestrator seam that NFR-002
  depends on is untouched.
- **Implementation-level dependency; Gate II architecture is unchanged.** This is a library
  choice inside an already-approved component, not an architecture decision. It introduces no
  service, no datastore, no external dependency, and no security boundary — the four
  categories the Architecture Approval Record covers. **No new approval is recorded and none
  is required.** Should the ORM ever be adopted, or the datastore or driver change, that would
  be a different decision and would require its own checkpoint (FR-029).

**Rationale**: transaction scoping, connection pooling, and safe parameter binding are the
parts of database access most likely to be got subtly wrong by hand, and Core supplies them
without the ORM's mapping layer. Keeping to Core also preserves the property the store layer
depends on for FR-036: every statement is visible at the call site, so the absence of an audit
update or delete path is verifiable by reading the module rather than by reasoning about what
an ORM might emit.

**Alternatives considered**:

- *Raw `psycopg` with hand-rolled connection and transaction handling* — fewest dependencies,
  and entirely viable. Rejected because the hand-rolled pooling and transaction scoping it
  requires are exactly the code most worth not writing, for no gain in transparency: Core
  keeps the SQL explicit either way.
- *SQLAlchemy ORM* — rejected. The mapping layer would obscure which statements actually reach
  the database, which weakens the FR-036 argument above, and none of the orchestrator's access
  patterns need identity mapping or lazy loading.

---

## R4 — Shortener HTTP surface and persistence (Java)

**Decision**: Spring Boot 3 on Java 21, Spring Web MVC, Bean Validation at the request
boundary, **Spring Data JPA as the single persistence model for every query including the
redirect path**, `springdoc-openapi` to generate the contract, and Actuator for health and
metrics. Virtual threads are **not** a foundational design choice — see below.

**Rationale**: FR-016 requires a documented, versioned, machine-readable contract;
`springdoc-openapi` generates it from the same annotated types that validate requests, so the
published contract and the running service cannot silently diverge. Bean Validation puts
FR-002/FR-003's scheme allow-listing and length limits at the boundary as declarative
constraints, which is what NFR-006 asks for.

**One persistence model, not two.** The previous revision proposed JPA for the management
surface and hand-written JDBC for the redirect hot path. That is rejected: no measurement
justifies it. The redirect query is a single primary-key lookup plus a counter update, and
NFR-001's 150 ms p95 budget has substantial headroom at the NFR-005 operating point of 100
requests/second — a load at which ORM overhead is not plausibly the limiting factor. Carrying
two persistence idioms would mean two sets of mapping code, two testing approaches, and two
places for a schema change to land, bought with a performance claim nobody has measured. That
is exactly the speculative complexity Principle XI prohibits.

**JDBC remains a brownfield lever.** If load verification shows the redirect path missing
NFR-001, and profiling attributes the gap to persistence overhead rather than to connection
acquisition, index shape, or network time, then dropping to JDBC for that one query is a
legitimate, narrowly-scoped optimisation — decided from measurement in the brownfield
scenario, through an approval checkpoint (R13).

**Virtual threads: optional configuration, not architecture.** Java 21 offers them, and
Spring Boot enables them with a single property. The greenfield architecture does **not**
depend on them: the design must be correct and meet NFR-001 on the platform default thread
model. They are recorded as a runtime configuration switch that may be turned on if
concurrency measurement justifies it, and nothing in the code is written to assume either
model. Making them foundational would bake a scaling assumption into the design before any
evidence exists that the requirements need it.

**Alternatives considered**: Spring WebFlux (reactive throughput the requirements do not
need, at a large readability cost); JDBC everywhere (loses JPA's mapping and migration
ergonomics across the management surface for a benefit measured nowhere); hand-written
OpenAPI (drifts from the implementation).

## R5 — Console (React + TypeScript)

**Decision**: React + TypeScript single-page application, built as static assets, consuming
the orchestrator's `/v1` API. **Stateless with respect to workflow truth**: the console
holds no workflow state of its own, persists nothing, and derives every displayed value from
an API response.

**Rationale**: The requirement owner selected a real frontend, which also demonstrates the
full-stack half of the exercise. FR-048's constraint survives intact provided statelessness
is enforced rather than assumed, so the decision carries four explicit rules:

1. Every field the console displays must be present in an orchestrator API response. A
   console view with no API counterpart is a defect, not a feature.
2. The console keeps no durable client-side workflow store. React state and any query cache
   are ephemeral view state, discarded on reload; the server is re-read, never reconciled
   against.
3. Graph *layout* may be computed client-side — that is presentation. Graph *content* —
   nodes, edges, states, staleness, execution mode — comes from `GET /v1/runs/{id}/graph`
   and is never inferred locally.
4. Every console assertion in the test suite has an equivalent API-level assertion, so a
   reviewer can verify any run headlessly (FR-048, SC-020).

**Rationale for the constraint being worth stating**: an SPA is exactly the kind of surface
that accretes local truth — optimistic updates, derived status, cached approvals — and each
of those would make the console a second source of state. Rules 1–4 are what keep it a view.

**Alternatives considered**: server-rendered HTML (the previous proposal — simpler and
trivially headless-testable, but does not demonstrate frontend engineering and was rejected
by the owner); React with a client-side state library holding run state (rejected — directly
violates FR-048); Next.js/SSR (rejected — adds a server for a client that needs none).

---

## R6 — Agent runtime for bounded tasks

**Decision**: Python orchestrator using the official `anthropic` SDK, default model
`claude-opus-5`, adaptive thinking (`thinking: {type: "adaptive"}`), `output_config.effort`
tuned per task class, the SDK's beta tool runner so per-turn hooks own approval
interception, and a declared `task_budget` per run alongside a wall-clock ceiling.

**Capability model — narrow, and mechanically enforced.** Agents receive **no shell and no
general filesystem authority**. The tool surface is a small set of purpose-built tools:

| Tool | Authority |
|------|-----------|
| `read_file` | Read within an explicitly declared path allow-list for the task |
| `write_file` | Write within that same allow-list, and only to paths the task declares as outputs |
| `run_tests` | Execute the project's test target — a fixed command, not an arbitrary one |
| `report` | Return findings/completion to the orchestrator |

There is no `bash`, no `exec`, no package installation, no network tool, and no path outside
the per-task allow-list. Prohibited acts under FR-041 — introducing a service or datastore,
altering architecture or security policy, modifying governance artifacts, releasing — are
unreachable because **no tool reaches them**, not because a prompt discourages them.

**Rationale**: three requirements map onto specific mechanisms rather than instructions.
FR-043's approve-*before*-apply is served by the per-turn hook refusing a tool call, so no
change is made and then undone. FR-030 and NFR-009 are served by the per-operation timeout
and attempt cap the orchestrator enforces, plus the advisory token budget the model paces
against. FR-041's four preconditions are checked before dispatch, and the path allow-list is
derived from the approved interface — so "bounded" is enforced at the tool layer.
FR-042's no-escalation rule is enforced because the runtime constructs the tool set from the
task's planning-time execution mode.

**Network boundary — the orchestrator may call Claude; the agent may not call anything.**
These are two different things and the distinction is load-bearing:

- The **orchestrator process** makes exactly one class of outbound request: the configured
  Claude API endpoint, required for agent execution. Process egress is restricted to that
  host; nothing else is reachable from the orchestrator at runtime.
- The **agent** receives no network capability whatsoever. None of the four tools takes a
  URL, a host, or a port. There is no HTTP tool, no fetch tool, no MCP connector, and no
  package installation (which would be network egress by another name).
- **Anthropic server-side tools are disabled.** Web search, web fetch, and code execution are
  explicitly *not* declared in the request. This matters more than it first appears: those
  tools would let an agent cause arbitrary outbound requests *through the model provider*,
  turning the one permitted egress into a general-purpose proxy. The Claude call must be a
  channel for reasoning, never a channel for reaching the network.
- Consequently, the agent boundary cannot become a bypass of FR-018. SC-017's "zero outbound
  requests to caller-supplied destinations" is verified across the whole system, orchestrator
  included, and the only egress that should ever appear is the configured Claude endpoint.

**Polyglot adjustment**: the path allow-list is scoped per language surface. A bounded task
in the Java workload receives paths under `shortener/`, one in the orchestrator receives
paths under `orchestrator/`, and one in the console receives paths under `console/`. No task
receives paths spanning two surfaces without an approval checkpoint, because a cross-surface
change is an architectural change.

**Alternatives considered**: manual tool-use loop (hand-writing what the SDK provides, with
the approval hook ours to get right); **Claude Agent SDK** (rejected — its built-in
Read/Write/Edit/Bash tool set is precisely the unrestricted shell and filesystem authority
this decision excludes; bounding it would mean fighting the harness); Managed Agents
(rejected — the orchestrator *is* the deliverable, so delegating the loop hollows out what
is being demonstrated); local/open-weight model (no requirement calls for it).

---

## R7 — Workflow and node state model

**Decision**: Carried forward unchanged. Resolves the `WorkflowRun` state gap deferred from
`/speckit-clarify`.

Run states: `PLANNING` → `AWAITING_PLAN_APPROVAL` → `EXECUTING` ⇄ `WAITING_FOR_HUMAN`, with
`REPLANNING` enterable from `EXECUTING`, terminating in `COMPLETED`, `FAILED`,
`SAFE_STOPPED`, or `ABANDONED`.

Node states: `PENDING` → `READY` → `RUNNING` → `SUCCEEDED` | `FAILED` | `ROLLED_BACK` |
`SKIPPED`, with `STALE` as a flag orthogonal to state (FR-033 marks completed work stale
without erasing its result).

**Correction, US3 (2026-08-19).** `SAFE_STOPPED` is now reachable from *every* non-terminal
run state, not only from `PLANNING` and `EXECUTING`. A clarification budget exhausted while
`WAITING_FOR_HUMAN` had nowhere to go, which would have meant a run that could not stop safely
because of where it happened to be — precisely the failure Principle VII prohibits. Added to
`AWAITING_PLAN_APPROVAL`, `WAITING_FOR_HUMAN`, and `REPLANNING`.

**Rationale**: FR-025 persists state at every transition and FR-036 audits every transition,
so the set must be closed and named before either is testable. Staleness is a flag rather
than a state because a stale-but-succeeded node retains a result replanning may consult.

---

## R8 — Rate-limit thresholds

**Decision**: Carried forward unchanged. 60 link creations per minute per client credential,
burst 10, sliding window. The redirect path is not rate limited.

**Rationale**: FR-015 needs a number to be testable. Redirects are deliberately unlimited —
throttling them would damage NFR-001 and NFR-002 directly, and redirect abuse is a content
problem, not a rate problem.

**Adjustment**: the counter is held in PostgreSQL alongside link data, not in a separate
store. This is a deliberate consequence of R13 — no Redis in greenfield.

---

## R9 — Contract versioning

**Decision**: Carried forward unchanged. URL-path major versioning (`/v1/...`) for
programmatic surfaces; the redirect route is unversioned and permanent. Error identifiers
are stable strings, additive-only within a major version.

**Rationale**: FR-016 requires a versioned contract with stable error identifiers, and
FR-017 requires it to support a later frontend without change. The redirect route cannot be
versioned — short links are handed to third parties and must never change shape.

---

## R10 — Test strategy (polyglot)

**Decision**: Four layers per Constitution Principle IV, realised in each stack's idiom, and
separately runnable.

| Surface | Unit | Integration | Workflow | Failure-path |
|---------|------|-------------|----------|--------------|
| Shortener (Java) | JUnit 5 | `@SpringBootTest` + **Testcontainers** PostgreSQL | — | JUnit 5 with induced faults |
| Orchestrator (Python) | `pytest` | `pytest` + `httpx` ASGI transport + Testcontainers PostgreSQL | Full runs against a **stubbed agent runtime** | Forced timeout, retry exhaustion, rollback, safe-stop |
| Console (TS) | Vitest | React Testing Library against a mocked API | — | Error/empty/loading states |

**Rationale**: Principle IV names unit, integration, workflow, and failure-path as *distinct*
obligations, so each must be separately runnable and separately reportable. Testcontainers
rather than an in-memory substitute matters specifically because R3 chose PostgreSQL for its
concurrency semantics — testing against H2 or SQLite would validate against a store with
different locking behaviour than production, which is how concurrency bugs survive to
release. The agent runtime is stubbed by default so retry exhaustion, rollback, and
safe-stop are deterministically reproducible; a small opt-in suite exercises the real
provider.

**Console parity rule** (from R5): every console test assertion has an API-level counterpart,
keeping FR-048 verifiable headlessly.

**Alternatives considered**: H2/in-memory for Java integration tests (fast, but wrong
concurrency semantics); recording and replaying real model responses (brittle, slow, and
unable to force failure paths); live model calls in CI (nondeterministic and costly).

---

## R11 — Metric definitions

**Decision**: Carried forward unchanged. Resolves FR-037's terms so they are computable.

| Metric | Definition |
|--------|------------|
| Success rate | Runs reaching `COMPLETED` ÷ runs reaching any terminal state |
| Retry frequency | Retry attempts ÷ operations executed |
| Rollback frequency | Rollbacks executed ÷ changes applied |
| MTTR | Mean wall-clock from a node entering `FAILED` to the run leaving the failure — via retry success, fallback, or rollback. Time in `WAITING_FOR_HUMAN` excluded and reported separately |
| End-to-end latency | Run creation to terminal state, minus time in `WAITING_FOR_HUMAN` |

**Rationale**: both time-based metrics would otherwise measure how fast a human answered
their messages. FR-049 makes waiting a zero-compute persisted state, so excluding it is
consistent with what the system actually did. Human wait time is still reported separately.

---

## R12 — Short code generation

**Decision**: Carried forward. Cryptographically random 7-character codes over the 62-symbol
alphabet, uniqueness enforced by a PostgreSQL unique constraint, bounded retry (3 attempts)
on collision, then a distinct failure outcome rather than a loop.

**Rationale**: FR-004 requires uniqueness across all codes ever issued; a database
constraint makes that a property of the store rather than of application logic under
concurrency — which is what the "two concurrent requests race for the same alias" edge case
demands. Random rather than sequential avoids enumerable codes and avoids leaking one
client's link volume. The retry is bounded because Principle VII prohibits unbounded retry
anywhere.

**Adjustment**: under PostgreSQL the collision path surfaces as a unique-violation on insert,
handled as a bounded retry — genuinely concurrent, unlike SQLite's serialised writer where
the same race would have queued.

---

## R13 — No Redis in the greenfield architecture

**Decision**: The greenfield redirect path reads and writes PostgreSQL only. No Redis, no
cache tier, no message broker. Redis remains a **candidate optimisation for the brownfield
scenario** (User Story 4), to be adopted only if measurement demonstrates the need, and only
through an approval checkpoint.

**Rationale**: Constitution Principle XI names Redis explicitly as something requiring a
demonstrated requirement, and no requirement in the spec demonstrates one today. The
redirect path is a single indexed primary-key lookup plus a counter update; at the NFR-005
operating point of 100 redirects/second, that is an unremarkable load for PostgreSQL, and
NFR-001's 150 ms p95 budget has substantial headroom. Adding a cache now would buy latency
nobody has asked for while adding an invalidation problem that interacts badly with
requirements already fixed: a cached redirect must not outlive a revocation (FR-012) or an
expiry (FR-008), and cached counters must not drift from the exact totals SC-006 demands.

**Why this is the right shape for the deliverable, not just the cheap answer**: User Story 4
requires a brownfield enhancement targeting redirect responsiveness or reliability, and
requires the system to plan against an existing implementation. Starting without a cache
gives that scenario something real to do — measure the current path, identify the actual
bottleneck, and propose a change through an architecture approval checkpoint (FR-029). A
greenfield that pre-emptively includes Redis would leave the brownfield demonstration
performing a change nobody could justify from data.

**Conditions under which Redis becomes justified** (all three, measured, not assumed): p95
redirect latency exceeds the NFR-001 budget at the NFR-005 operating point; profiling
attributes the excess to datastore access rather than application or network time; and a
cache design exists that preserves FR-008, FR-012, and SC-006 exactness. Absent all three,
the brownfield enhancement should target the measured bottleneck instead — connection
pooling, index shape, or the counter write pattern.

**Brownfield levers, cheapest first.** If the load verification baseline shows NFR-001 at
risk, these are the candidates in ascending order of cost and risk — and the brownfield run
must measure before selecting, not select and then justify:

1. Connection pool sizing and index shape (configuration; no code change)
2. Enabling virtual threads (one property; R4)
3. Counter write batching or a materialised aggregate (contained code change)
4. Dropping the single redirect query to JDBC (contained code change; R4)
5. A Redis cache tier (new datastore — architecture approval required, three conditions above)

**Alternatives considered**: Redis read-through cache from day one (rejected — undemonstrated
requirement, invalidation risk against revocation and expiry, and it pre-empts the brownfield
scenario); in-process caching (same invalidation problems, plus incorrectness across two
instances); materialised counter batching from day one (a legitimate future option, cheaper
than Redis, but equally unjustified before measurement).

---

## R14 — Analytics recording versus redirect availability (NFR-002)

**Decision**: The counter increment and the redirect-event insert happen in the **same
database transaction as the redirect resolution**, inside `shortener_db`, and that
transaction **commits before the redirect response is issued**. The analytics *serving*
surface runs on a **separate connection pool** from the redirect path. Event retention uses a
**simple indexed event table**, with the retention behaviour documented rather than engineered
into the schema. No queue, no outbox, no broker.

**Retention mechanism — simplified for the delivery budget.** An earlier revision specified
monthly range partitions dropped whole. That was removed: partitioning is the right answer at
production scale, where a bulk `DELETE` would take long locks on the hot write path, but at
the demonstration scale of 100,000 links it is schema ceremony bought with a migration nobody
can justify from measurement. The greenfield implementation uses an ordinary indexed table;
when the retention sweep is built it runs as a chunked, off-peak delete, and the residual lock
risk is **documented** rather than designed away. Partitioning stays available as a brownfield
migration if measurement ever demands it.

**Rationale**: The requirement pair looks contradictory — NFR-002 says an analytics failure
must not take redirects down, while FR-013/FR-014/SC-006 demand exact counts — so it is worth
separating what is actually coupled from what merely sounds coupled.

*Recording is not a surface.* NFR-002's independence is about the analytics and orchestration
**surfaces**: the reporting endpoints and the orchestrator service. The counter write is not a
separate surface; it is part of resolving a redirect, in the same database the redirect must
already read from. There is no distributed transaction here to solve, which is precisely why
no broker is warranted — Kafka solves cross-service durability, and both writes are in one
database.

*Exactness is preserved by ordering, not by luck.* Commit precedes the response. A redirect
whose count cannot be durably recorded is therefore not served and not counted — the two
outcomes stay consistent by construction, with no window in which a visitor was redirected
but the count was lost. SC-006 holds without reconciliation logic.

*The real NFR-002 risks are the ones this design isolates.* A heavy or pathological history
query starving the connection pool the redirect path needs is a genuine way for analytics to
take redirects down — hence separate pools, which cost nothing. A long-running retention sweep
locking the hot table is the second; with partitioning removed, it is mitigated by chunked
off-peak deletes and recorded as a documented risk rather than eliminated structurally.

**Accepted risk — read-only datastore condition** (ruled on at approval, 2026-08-18): under
this design a redirect cannot outlive a `shortener_db` write outage. In most such scenarios
the redirect is already unavailable, because the same database serves the lookup and there is
no cache tier (R13). The narrow uncovered case is a database that can read but not write, in
which the redirect fails rather than serving uncounted.

The requirement owner accepted this as a **known availability trade-off**, and ruled that
NFR-002 means independence from the analytics-serving and orchestration surfaces — *not* from
the shortener's own durable datastore, which FR-013, FR-014, and SC-006 require. It is
therefore **not** an unresolved architecture question, and **not** grounds for introducing a
broker or a durable buffer.

**Retained measurable risk — per-link counter-write contention**: every successful redirect
updates one row, so a single very hot link serialises its own counter updates. This is a
performance risk to be *measured*, not pre-empted. Load verification must exercise skewed
traffic as well as uniform traffic; if measurement shows contention limiting NFR-001, it
becomes a brownfield candidate on R13's ladder — batching or a materialised aggregate before
any cache tier. Not to be pre-optimised.

**Alternatives considered**:

- *Fire-and-forget asynchronous recording* — keeps redirects alive through analytics write
  failures, but loses buffered events on crash and breaks SC-006's exactness. Rejected: the
  spec asks for exact counts, not approximately exact ones.
- *In-process queue with background flush* — same exactness failure, plus a buffer that
  vanishes on restart, contradicting NFR-003.
- *Transactional outbox with a relay* — the standard answer when writes span two systems.
  Rejected here because they do not: both writes are in one database, so the outbox adds a
  second write, a relay process, and eventual-consistency lag to solve a problem that does
  not exist.
- *Kafka or another broker* — rejected under Principle XI and the owner's explicit direction.
  Nothing in these requirements is cross-service, cross-datacenter, or fan-out shaped; the
  broker would be infrastructure serving a design that does not need it.
- *Separate analytics database* — would decouple recording from the link store, but then the
  count and the link are in different databases and exactness needs distributed coordination.
  Strictly worse on both axes.

## R15 — Ephemeral Docker test sandbox for agent-authored code

**Status: capability-boundary decisions HUMAN-APPROVED 2026-08-18.** The requirement owner
made the security decisions in this section; the implementation was agent-assisted under that
approved boundary. No architecture approval was recorded by an agent.

**Decision**: `run_tests` never executes agent-authored code in the orchestrator process or
against the authoritative repository. Every invocation runs inside an ephemeral Docker
container against a **disposable task-scoped copy** of the single approved surface, discarded
afterwards.

**Why the previous design was insufficient**: R6 bounded the agent's *tool surface*, which
stops an agent from asking for a shell. It did not bound what the agent's own **test code**
could do once `run_tests` executed it — and an agent that can write a test file can put
arbitrary code in it. The Python socket allow-list (R6, T015) does not help here either: it
guards the orchestrator process, not a child process running project tests. The sandbox is the
control that actually bounds agent-authored code; the socket guard is **defense in depth for
the orchestrator process only** and must not be described as the primary sandbox.

### Approved controls

**Copy-on-run, never mount the authoritative repository writable.**

1. Create a disposable task-scoped copy of the approved surface.
2. Execute tests against that copy.
3. Discard it after execution.
4. Unexpected filesystem mutations never propagate back to the authoritative repository —
   structurally, because the authoritative tree is never mounted into the container at all.

**Unit / workflow / failure-path containers**: network disabled (`--network none`), no Docker
socket, no host home directory, no secrets in the environment, no `.git`, no `ops/`, no access
to any other project surface, non-privileged (`--user`, `--cap-drop ALL`), `no-new-privileges`,
and bounded CPU, memory, PIDs, output size, and wall-clock time.

**Integration tests**: the Docker socket is *not* exposed to the test runner. The orchestrator
provisions a disposable PostgreSQL dependency externally and joins both containers to a
dedicated isolated Docker network with no general internet egress. Credentials are test-only
and scoped to that disposable database.

**Model-visible tools remain exactly four**: `read_file`, `write_file`, `run_tests`, `report`.
The sandbox is an implementation detail of `run_tests`; no container, image, command, mount, or
network argument is expressible by the agent.

### Alternatives considered

- *Run tests in-process or as a plain subprocess on the host* — the prior design. Rejected: an
  agent-written test file would execute with the orchestrator's own privileges, its network
  access, its environment, and write access to the real repository.
- *Host subprocess with a restricted user and `ulimit`* — better, but does not remove `.git`,
  `ops/`, other surfaces, or host secrets from the filesystem view, and offers no credible
  network boundary.
- *Mount the repository read-only into the container* — rejected: tests legitimately write
  (caches, build output, temp files), and a read-only mount either breaks them or invites a
  writable exception that reopens the hole. A disposable copy is simpler and strictly safer.
- *gVisor / Firecracker / rootless VM isolation* — stronger, and the right answer for hostile
  code. Out of scope for this deliverable, and recorded as such: the threat model here is a
  capable model making mistakes or over-reaching, not a dedicated attacker with a kernel
  exploit.

### Accepted residual risk

Docker containers share the host kernel. A container escape via a kernel or runtime
vulnerability is not defended against by this design. Accepted for a take-home whose threat
model is agent over-reach rather than adversarial exploitation; noted here so the limit is
recorded rather than implied.

## Unresolved

None. The three specification-level ambiguities were resolved before planning (spec §
Resolved Clarifications); the four items deferred from `/speckit-clarify` are resolved at
R7, R8, R9, and R11.
