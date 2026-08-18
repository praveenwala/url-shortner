# Implementation Plan: Agentic URL Shortener

**Branch**: `001-agentic-url-shortener` | **Date**: 2026-08-18 (revised) | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-agentic-url-shortener/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

> **✅ Approval status: APPROVED — revision 3**, recorded 2026-08-18. Revision 1 was reviewed
> and rejected; revision 2 incorporated the owner's directed decisions; revision 3 applied five
> further refinements. The requirement owner has now approved the architecture as a whole under
> Constitution Principle II, with rationale recorded in the Architecture Approval Record below.
> **Gate II is cleared.** `/speckit-tasks` may proceed.

## Delivery Scope

**Budget: 2–3 days.** The approved architecture above is unchanged; the *implementation* is
scoped to that budget in [tasks.md](./tasks.md), which prioritises the orchestration system
over URL-shortener feature breadth and lists every deferred capability with its re-entry cost.
Deferred at implementation level: custom aliases (FR-005), creation rate limiting (FR-015),
paginated event history and the retention sweep (FR-013, FR-014 history half), four secondary
console screens, and range partitioning (removed from the design — see R14). Every governance
and safety requirement — FR-028, FR-029, FR-039, FR-040, FR-041–FR-044, FR-049, FR-050 — is
implemented and tested. Requirements themselves are unchanged.

## Summary

Deliver a production-oriented URL shortener (create, resolve, expire, revoke, analyse,
throttle) together with the agentic orchestration system that plans, executes, gates, and
audits its delivery — demonstrated across greenfield, brownfield, and ambiguous-requirement
scenarios.

The architecture is polyglot along a seam the requirements already forced. The **shortener**
is Java 21 + Spring Boot 3 — the production artifact, where Java engineering is what is
being assessed. The **orchestrator** is Python, where the agent tooling that FR-043 and
NFR-009 depend on is most direct. The **console** is React + TypeScript, stateless with
respect to workflow truth. Both services persist to PostgreSQL in **separate databases with
separate credentials**, so neither can read the other's data. No Redis: the greenfield
redirect path is PostgreSQL only, leaving cache adoption as a measured decision for the
brownfield scenario.

Agents author code only inside bounded tasks whose interface, acceptance criteria,
dependencies, and security constraints are already approved, through a **narrow tool surface
with no shell and no general filesystem authority** — approval interception happens before a
change is applied, not after.

## Technical Context

**Language/Version**: Java 21 (shortener) · Python 3.13 (orchestrator) · TypeScript 5.x +
React 18 (console)

**Primary Dependencies**: Spring Boot 3 (Web MVC, Bean Validation, Spring Data JPA as the
single persistence model, Actuator), `springdoc-openapi`; `anthropic` Python SDK
(`claude-opus-5`, adaptive thinking, beta tool runner, task budgets — server-side web
search/fetch/code-execution tools explicitly **not** declared), FastAPI; React + Vite

**Storage**: PostgreSQL — two databases, two credentials, no cross-database reference:
`shortener_db` and `orchestrator_db`. Redirect resolution and analytics recording share one
transaction; analytics *serving* uses a separate connection pool, and redirect events live in a
simple indexed table with documented retention behaviour (R14). Audit records are
`INSERT`/`SELECT` only for the orchestrator role — no `UPDATE`, no `DELETE`

**Testing**: JUnit 5 + Testcontainers (Java) · `pytest` + `httpx` + Testcontainers (Python)
· Vitest + React Testing Library (console) — four separately-runnable layers per Principle IV,
agent runtime stubbed by default

**Target Platform**: Linux/macOS; two backend processes plus static console assets and a
PostgreSQL instance, all locally runnable

**Project Type**: Polyglot multi-service backend with a single-page console

**Performance Goals**: 95% of redirects within 150 ms, 99% within 400 ms, at 100
redirects/second sustained against 100,000 stored links (NFR-001, NFR-005, SC-002)

**Constraints**: Redirect path must survive orchestrator outage (NFR-002); no outbound
request to any caller-supplied URL, ever (FR-018); workflow state durable across restart
(NFR-003); every run declares wall-clock and retry ceilings (NFR-009); waiting for a human
consumes zero compute (FR-049); no Redis in greenfield (owner direction, R13); agents get no
shell, general filesystem, or **network** authority, and server-side model tools that would
grant egress are disabled (R6); virtual threads are optional configuration, never a design
assumption (R4)

**Scale/Scope**: 100,000+ links, 100 redirects/second, 90-day redirect-event retention; **49**
functional requirements (FR-001–FR-050 with FR-019 unassigned), 9 non-functional, 21 success
criteria, 6 user stories, three demonstration scenarios

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Mark each gate PASS / FAIL / N-A with a one-line justification. Any FAIL must either be
resolved or recorded in Complexity Tracking below with human approval.

- [x] **I. Specification-First**: PASS — spec carries requirements, acceptance criteria,
      assumptions; zero `[NEEDS CLARIFICATION]` markers; three ambiguities resolved by the
      owner and recorded as decision lineage.
- [x] **II. Controlled Agent Autonomy**: **PASS** — the polyglot architecture, the datastore
      (PostgreSQL, two databases), the external dependency (Claude API), and the agent
      capability model were each approved by the requirement owner on 2026-08-18. Rationale,
      approver, and the seven approved decisions are in the Architecture Approval Record
      below. No agent recorded this approval (Principle XII, FR-029, FR-050).
- [x] **III. Traceability**: PASS — every component below names the requirements it serves;
      `tasks.md` will carry `[REQ]` labels per the amended tasks template.
- [x] **IV. Test-First**: PASS — R10 defines four separately-runnable layers across three
      stacks, with Testcontainers PostgreSQL (not an in-memory substitute) so tests exercise
      the locking semantics R3 selected, and a stubbed agent runtime so retry exhaustion,
      rollback, and safe-stop are deterministic.
- [x] **V. Security by Design (all features)**: PASS — Bean Validation at the Java boundary
      for scheme allow-listing and length limits (FR-002, FR-003); open-redirect prevention
      (FR-010); secrets from environment only; separate database credentials per service, and
      an orchestrator role that can `INSERT`/`SELECT` but not `UPDATE`/`DELETE` audit records
      (least privilege); approver identity separated from any agent-usable identity (FR-050);
      agents hold no shell, filesystem, or network authority, and the one permitted process
      egress — the configured Claude endpoint — cannot become a general proxy because
      server-side web search, web fetch, and code execution are not declared (R6).
- [x] **V-a. Unsafe-target prevention (conditional)**: **N-A** — FR-018 prohibits any
      outbound request to a caller-supplied URL at creation, resolution, or analytics. The
      service is store-and-redirect only, so SSRF and private-address controls do not apply.
      SC-017 verifies zero egress. Any future dereferencing capability re-triggers this gate.
- [x] **VI. Stateful Orchestration**: PASS — explicit DAG with cycle rejection (FR-022),
      state persisted at every transition (FR-025), synchronisation nodes (FR-024),
      entry/exit gates (FR-026); run and node state sets closed and named in R7.
- [x] **VII. Resilience**: PASS — timeout, bounded retry, fallback, rollback, and safe-stop
      declared per operation (FR-030–FR-032); bounded even on code generation (R12 retry cap,
      R6 task budget and wall-clock ceiling).
- [x] **VIII. Observability**: PASS — append-only audit of every action, decision, gate,
      approval, retry, failure, rollback, replan, transition (FR-036); the five required
      metrics given computable definitions in R11; Actuator on the Java side for the
      shortener's operational signals.
- [x] **IX. Dynamic Replanning**: PASS — blast radius computed from the graph, staleness
      modelled as a flag so completed results survive (R7), replan recorded (FR-033).
- [x] **X. Production Quality**: PASS — no runtime dependency from shortener to orchestrator;
      dependencies injectable for the stubbed-agent layer; console holds no workflow truth
      (R5 rules 1–4); no hidden global state.
- [x] **XI. Simplicity**: PASS with three additions justified in Complexity Tracking (second
      service, polyglot boundary, React console). Revision 3 removed two speculative choices:
      the JPA/JDBC persistence split (one model now, JDBC deferred to measured brownfield) and
      virtual threads as a foundational assumption (optional configuration now). Redis is
      explicitly **excluded** (R13); no broker is introduced for analytics because both writes
      live in one database and there is no distributed transaction to solve (R14); PostgreSQL
      serves both services; the console has no server.
- [x] **XII. Human Ownership**: PASS by construction — gate II is unresolved and this
      document says so rather than claiming approval, in a revision the owner explicitly
      asked to leave unapproved.

**Post-Phase-1 re-check**: gates I, III–XII re-evaluated after the data model, contracts, and
quickstart were revised for this architecture; all still PASS. V-a remains N-A — no contract
in `contracts/` contains an operation that fetches a destination. **Gate II is cleared** by the
approval recorded below. All 13 gates resolved: 12 PASS, 1 N-A.

## Architecture Approval Record

**Checkpoint**: Architecture — implementation plan revision 3
**Decision**: Approved
**Approver**: Requirement owner, holding the approver role (Constitution FR-029, FR-050)
**Date**: 2026-08-18
**Scope**: Constitution Gate II for this feature's architecture. Does not extend to future
architecture changes, which require their own checkpoint (FR-029).

**Approved decisions, with the approver's rationale**:

1. **Independently runnable Java 21 / Spring Boot shortener and Python orchestration service.**
   The service boundary is justified by NFR-002, and the polyglot choice follows that existing
   boundary rather than creating an additional architectural seam.
2. **React + TypeScript for the stateless orchestration console**, with persisted orchestration
   state remaining exclusively behind the orchestrator APIs.
3. **PostgreSQL as the durable datastore**, with separate shortener and orchestrator ownership
   boundaries and credentials.
4. **Spring Data JPA as the single greenfield persistence model.** JDBC, virtual threads,
   Redis, batching, connection-pool changes, and other optimisations remain measurement-driven
   brownfield candidates rather than greenfield architecture assumptions.
5. **The bounded agent-runtime capability model.** The orchestrator may communicate with the
   explicitly configured Claude endpoint; agent-exposed tools have no arbitrary network, shell,
   package-install, git, or unrestricted filesystem capability.
6. **Append-only audit enforcement by database privilege** — the orchestrator service role may
   `INSERT` and `SELECT` audit events but may not `UPDATE` or `DELETE` them.
7. **The redirect/analytics consistency decision in R14.** Exact redirect accounting is part of
   successful redirect processing. If the shortener datastore cannot durably record the
   successful redirect — including the narrow case where reads succeed but writes fail — the
   redirect may fail rather than create analytics drift.

**Authoritative interpretation of NFR-002** (approver ruling): independence from the
**analytics-serving and orchestration surfaces**, *not* independence from the shortener's own
durable datastore required to satisfy FR-013, FR-014, and SC-006. This interpretation governs
how NFR-002 is tested and how future changes are assessed against it.

## Project Structure

### Documentation (this feature)

```text
specs/001-agentic-url-shortener/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
shortener/                          # Java 21 + Spring Boot 3
├── src/main/java/.../shortener/
│   ├── domain/                     # ShortLink, RedirectEvent, code generation (R12)
│   ├── web/                        # /v1 controllers + the unversioned redirect controller
│   ├── validation/                 # scheme allow-list, length, alias, canonicalisation
│   ├── persistence/                # Spring Data JPA repositories — one model, all queries
│   └── ratelimit/                  # per-credential sliding window (R8, PostgreSQL-backed)
├── src/main/resources/
│   └── db/migration/               # schema migrations for shortener_db
└── src/test/java/
    ├── unit/
    ├── integration/                # @SpringBootTest + Testcontainers PostgreSQL
    └── failure/

orchestrator/                       # Python 3.13
├── src/
│   ├── models/                     # Requirement, WorkflowRun, TaskNode, Gate, ApprovalRecord,
│   │                               # DecisionRecord, AuditEvent, ReplanEvent, ChangeRecord, TraceLink
│   ├── graph/                      # DAG construction, cycle rejection, readiness, sync, blast radius
│   ├── engine/                     # scheduler, gates, retry/timeout/fallback, rollback, safe-stop
│   ├── agent/                      # bounded-task runtime: narrow tool surface, approval hooks, budgets
│   ├── audit/                      # append-only trail, metric computation (R11)
│   ├── api/                        # /v1 — everything the console displays
│   └── store/                      # orchestrator_db access, migrations
└── tests/
    ├── unit/
    ├── integration/
    ├── workflow/                   # full runs against a stubbed agent runtime
    └── failure/

ops/                                # operational scripts — not runtime code, imported by nothing
└── db/provision.sql                # databases, roles, audit privileges

console/                            # React + TypeScript (static build artifact)
├── src/
│   ├── api/                        # generated/typed client for the orchestrator /v1 surface
│   ├── views/                      # RunView, HumanActionView — the two approved views only
│   └── components/                 # graph rendering (layout only — content comes from the API)
└── tests/                          # Vitest + RTL against a mocked API
```

**Structure Decision**: Three top-level surfaces on two runtime services, plus `ops/` for
operational scripts. `shortener/` and `orchestrator/` are independently runnable and **share no
implementation code — only contracts**, which is what lets NFR-002 be demonstrated by stopping
the orchestrator and watching redirects continue. There is deliberately **no shared runtime
module**: each service owns its own correlation/trace helper, agreeing only on the field names
fixed in `contracts/correlation.md`. A change to those names is a contract change propagated to
two implementations on purpose, never a common library introduced across the language boundary.
`console/` builds to static assets with no server and no persistent client state; it is a
view over the orchestrator API, never a second source of truth (FR-048, R5 rules 1–4). The
polyglot boundary falls exactly on the existing service seam, so no component is split across
two languages.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Two services rather than one process | NFR-002 requires the redirect path to stay available when analytics and orchestration degrade or fail | A single process can assert independence but cannot demonstrate it; the acceptance test is "stop the orchestrator, redirects still work", which requires separate processes |
| Two databases and two credentials rather than one | Least privilege (NFR-006) plus NFR-002 — orchestrator write load and lock contention must not be able to reach the redirect path | One database with two schemas re-couples the services at the layer NFR-002 asks to decouple, and a credential spanning both weakens the privilege boundary |
| Polyglot: Java workload, Python orchestrator | The exercise assesses Java/Spring engineering in the production workload, while the agent tooling FR-043 and NFR-009 lean on is most direct in Python | All-Java is feasible but makes the AI iteration loop slower for no gain in the part being assessed; all-Python leaves the exercise with no Java workload. The boundary lands on the service seam NFR-002 already forced, so no component is split |
| React console rather than server-rendered HTML | Owner direction; demonstrates the full-stack half of the exercise | Server-rendered HTML is simpler and trivially headless-testable, but does not demonstrate frontend engineering. FR-048 is preserved by R5's four statelessness rules rather than by rendering location |
| External model-provider dependency | FR-041 requires agents to actually author bounded tasks; no requirement is satisfiable without a model | A scripted or simulated agent would make US2, US3, and US4 theatre rather than demonstration |
| **Not** a violation — recorded for review | Redis is **excluded** from greenfield (R13); the redirect path is PostgreSQL only | Adding a cache now would be the undemonstrated complexity Principle XI prohibits, would risk FR-008/FR-012/SC-006 correctness through stale entries, and would pre-empt the brownfield scenario that must justify it from measurement |
| **Not** a violation — recorded for review | No broker for analytics recording (R14) | Kafka solves cross-service durability; the counter and the event are written to one database in one transaction, so there is no distributed transaction for a broker to solve |
| **Removed in revision 3** | JPA/JDBC split, and virtual threads as a foundational choice | Both were performance optimisations chosen before any measurement existed. One persistence model and the default thread model are the simpler baseline the requirements permit; each remains available as a measured brownfield lever (R4, R13) |

## Recorded risks (accepted at approval)

Both were ruled on by the requirement owner at the Gate II approval and are recorded as
accepted trade-offs. Neither is an open architecture question.

**Read-only datastore condition.** Under R14 a redirect cannot outlive a `shortener_db`
**write** outage: the transaction recording the count commits before the redirect is served,
which is what makes SC-006 exact. In nearly every such outage the redirect is already
unavailable, because the same database serves the lookup and there is no cache. The narrow
uncovered case is a database that can read but not write, in which the redirect fails rather
than serving uncounted. **Accepted as a known availability trade-off.** Per the approver's
NFR-002 ruling, this is explicitly not an unresolved architecture question and not grounds for
introducing a broker or a durable buffer.

**Per-link counter-write contention.** Every successful redirect updates one row, so a single
very hot link serialises its own counter updates. Retained as a **measurable performance
risk**: load verification must exercise skewed traffic, not only uniform traffic. If
measurement shows it limiting NFR-001, it becomes a brownfield candidate on R13's ladder —
batching or a materialised aggregate before any cache tier. **Not to be pre-optimised.**
