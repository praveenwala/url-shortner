<!--
SYNC IMPACT REPORT
Version change: none (template placeholders) → 1.0.0
Bump rationale: Initial ratification. The prior file was the unfilled Spec Kit
template with no defined principles, so this is the first governing version
rather than an amendment (MINOR/PATCH would imply an existing baseline).

Principles defined (12; template shipped 5 placeholder slots):
  - [PRINCIPLE_1_NAME] → I. Specification-First Development
  - [PRINCIPLE_2_NAME] → II. Controlled Agent Autonomy
  - [PRINCIPLE_3_NAME] → III. Requirement Traceability
  - [PRINCIPLE_4_NAME] → IV. Test-First Quality (NON-NEGOTIABLE)
  - [PRINCIPLE_5_NAME] → V. Security by Design
  - (added) VI. Stateful Orchestration
  - (added) VII. Resilience and Bounded Autonomy
  - (added) VIII. Observability and Auditability
  - (added) IX. Dynamic Replanning
  - (added) X. Production Engineering Quality
  - (added) XI. Simplicity over Unnecessary Complexity
  - (added) XII. Human Ownership

Sections:
  - [SECTION_2_NAME] → Security and Operational Constraints
  - [SECTION_3_NAME] → Development Workflow and Quality Gates
  - Removed: none

Templates requiring updates:
  ✅ .specify/templates/plan-template.md (Constitution Check gates made concrete)
  ✅ .specify/templates/tasks-template.md (tests promoted from OPTIONAL to
     required for critical/orchestration behavior; traceability + observability
     task categories added)
  ✅ .specify/templates/spec-template.md (Assumptions/ambiguity capture made
     mandatory per Principle I)
  ✅ CLAUDE.md (constitution status updated from "unfilled template")
  ⚠ .specify/templates/checklist-template.md — reviewed, no principle-driven
     change required (structure is generic)

Deferred TODOs: none. RATIFICATION_DATE set to the project initialization date
recorded in .specify/workflows/workflow-registry.json (2026-08-18).

Same-session corrections to the 1.0.0 draft (no version bump; v1.0.0 was never
consumed by a downstream artifact):
  - Principle V and the Unsafe-target constraint split URL obligations by
    capability: scheme allow-listing, canonicalization, and open-redirect
    prevention apply to all URL-accepting features; SSRF/private-address
    rejection and redirect-chain bounds apply only to features that dereference
    a URL server-side. The base store-and-redirect flow does not dereference.
-->

# Schwab Agentic URL Shortener Constitution

## Core Principles

### I. Specification-First Development

No implementation begins before requirements, acceptance criteria, assumptions, and open
ambiguities are documented in the feature's `spec.md`. Every ambiguity MUST be recorded
explicitly (`[NEEDS CLARIFICATION: ...]`) and either resolved or converted into a stated
assumption before planning proceeds. A plan MUST NOT be generated from an ambiguous spec,
and code MUST NOT be written ahead of an approved plan.

**Rationale**: Agentic execution amplifies whatever it is pointed at. An unstated
assumption becomes a silently wrong implementation across many files before a human sees
it, so the cost of ambiguity scales with autonomy.

### II. Controlled Agent Autonomy

Agents MAY analyze, plan, implement, test, refactor, and propose changes without
per-step approval. Agents MUST obtain explicit human approval before:

- High-impact architecture decisions (new service, new datastore, new external dependency,
  cross-cutting redesign)
- Security-sensitive changes (authentication, authorization, secret handling, input
  validation policy, URL fetch/redirect policy)
- Destructive operations (data deletion, schema drop, history rewrite, force-push)
- Release actions (production deploy, tagging, publishing)

Approval MUST be recorded in the feature artifacts, not only in chat. When an agent is
uncertain whether a change crosses one of these lines, it MUST treat it as requiring
approval and stop.

**Rationale**: Autonomy is valuable in the reversible middle of the workflow and dangerous
at its irreversible edges. The boundary is drawn by blast radius, not by task difficulty.

### III. Requirement Traceability

Every implementation task MUST trace to a requirement ID from `spec.md`, and every
requirement MUST trace forward to a design decision, a code change, and a validating test
artifact. Tasks in `tasks.md` MUST carry their requirement/user-story label. A change with
no upstream requirement is out of scope and MUST be rejected or promoted into the spec
first; a requirement with no validating artifact is not complete.

**Rationale**: Traceability is what makes agent-produced work reviewable at speed — a
reviewer checks the chain rather than re-deriving intent from the diff.

### IV. Test-First Quality (NON-NEGOTIABLE)

Tests are written before the implementation they cover and MUST fail first. Automated
coverage is REQUIRED for:

- Critical business behavior (URL creation, resolution, expiry, collision, idempotency)
- Orchestration behavior (workflow transitions, gate evaluation, state persistence)
- Failure paths (timeout, bounded-retry exhaustion, fallback, rollback, safe-stop)
- Contract boundaries (public APIs and inter-component schemas)

Unit, integration, workflow, and failure-path tests are distinct obligations; passing unit
tests alone never satisfies this principle. Tests are OPTIONAL only for throwaway spikes
that are deleted before merge.

**Rationale**: A failing-first test is the only cheap evidence that a test actually
exercises the behavior it names — and under agentic authorship, tests written after the
code tend to encode the bug.

### V. Security by Design

All external input MUST be validated and normalized at the boundary before use. Secrets
MUST NOT appear in source, logs, specs, or test fixtures; they are supplied via
environment or a secret store. Every component runs with least privilege. URL handling
MUST prevent unsafe usage explicitly. Scheme allow-listing, canonicalization, and
open-redirect prevention apply to every feature that accepts a URL. Additionally, any
feature that dereferences a URL server-side — outbound fetch, liveness or reachability
checking, metadata/preview extraction, or fetch-based validation — MUST also reject
internal, loopback, link-local, private, and cloud-metadata targets (SSRF) and MUST bound
redirect chains it follows. Storing a destination and issuing a client-side redirect does
not by itself dereference the URL and does not trigger those obligations.
Security-sensitive changes require explicit human review per Principle II.

**Rationale**: A URL shortener is, by construction, a request-forwarding primitive, so
its safety rules must be stated as product behavior rather than left to reviewer
vigilance. The obligations are split by capability because they answer different threats:
open-redirect abuse follows from handing a destination to a client, while SSRF requires
the server itself to make the request. Imposing fetch-time controls on a service that
never fetches would be unenforceable ceremony.

### VI. Stateful Orchestration

SDLC workflows MUST be modeled as an explicit dependency graph, not implicit ordering.
The orchestrator MUST persist execution state so a run can be inspected, resumed, and
audited after interruption. The model MUST support sequential and parallel execution,
explicit synchronization points where parallel branches rejoin, and entry/exit gates on
each stage. A stage MUST NOT start until its entry gate passes, and MUST NOT be reported
complete until its exit gate passes.

**Rationale**: Durable, inspectable state is what separates an orchestrator from a script
that happens to call agents in order — and it is the precondition for both replanning
(IX) and audit (VIII).

### VII. Resilience and Bounded Autonomy

Every automated operation MUST define, before it runs: a timeout, a bounded retry policy
(finite attempts with backoff), a fallback behavior, a rollback path where the operation
is reversible, and a safe-stop that halts and escalates to a human. Unbounded retries,
unbounded loops, and open-ended agent execution are prohibited. Non-reversible operations
MUST declare that they have no rollback and are therefore gated by Principle II.

**Rationale**: An agent that cannot fail fast will fail expensively. Bounds convert an
unpredictable failure into a predictable, escalatable one.

### VIII. Observability and Auditability

Every agent action, decision, approval, retry, failure, rollback, and workflow transition
MUST emit a structured, correlated record sufficient to reconstruct what happened and why.
Records MUST be linkable to the originating requirement (Principle III). The system MUST
track, at minimum: success rate, retry count, rollback count, MTTR, and end-to-end
latency. Logs MUST be free of secrets and personal data.

**Rationale**: When a human is accountable for work an agent performed (Principle XII),
the audit trail is the only basis on which that accountability can be exercised.

### IX. Dynamic Replanning

When an upstream requirement or architecture decision changes, the workflow MUST identify
the affected downstream artifacts and tasks via the dependency graph and selectively
re-plan only those. Full-workflow restarts are prohibited as the default response to
change. Invalidated artifacts MUST be marked stale rather than silently retained, and the
replanning decision and its blast radius MUST be recorded.

**Rationale**: Requirements change mid-flight; if the only recovery is to start over, the
workflow will be abandoned under exactly the conditions it was built for.

### X. Production Engineering Quality

Code MUST be modular (clear boundaries, single responsibility, dependency direction
inward), maintainable (consistent style, no dead code, no copy-paste divergence),
testable (dependencies injectable, no hidden global state), secure (Principle V),
observable (Principle VIII), and documented (public interfaces and non-obvious decisions
carry rationale). Take-home scope is not a license for throwaway quality.

**Rationale**: The deliverable is evidence of engineering judgment, so the code is the
argument.

### XI. Simplicity over Unnecessary Complexity

Start with the simplest design that satisfies the stated requirements. Additional
technologies — Redis, message brokers, extra services, extra datastores, new frameworks —
MUST be justified against a demonstrated requirement recorded in the spec or plan, with
the simpler rejected alternative documented in the plan's Complexity Tracking table.
Anticipated future need is not justification (YAGNI).

**Rationale**: Every added component multiplies the failure paths that Principles IV, VII,
and VIII then obligate the project to cover. Complexity is paid for four times over.

### XII. Human Ownership

AI assists execution; humans remain accountable for architecture decisions, approvals,
release readiness, and final quality. Agent output is a proposal until a human accepts it.
No agent may approve its own gate, self-certify release readiness, or record an approval
on a human's behalf. Reviewers MUST understand a change well enough to defend it before
accepting it.

**Rationale**: Accountability cannot be delegated to a system that cannot be held
accountable.

## Security and Operational Constraints

- **Input boundary**: URL inputs are validated for scheme (HTTP/HTTPS allow-list only),
  length, and structure, and are normalized before storage or comparison. Rejected input
  produces a typed error, never a partially-processed request.
- **Open-redirect prevention** (all URL-accepting features): destinations are stored
  and returned as validated absolute URLs; user input never selects a redirect target
  outside the allow-listed schemes. Short codes MUST NOT be user-controllable in a way
  that permits impersonation of reserved paths.
- **Unsafe-target prevention** (features that fetch server-side only): any component that
  issues an outbound request to a user-supplied URL — availability checks, previews,
  metadata extraction, fetch-based validation — MUST resolve and reject loopback, private,
  link-local, and cloud-metadata addresses before connecting, and MUST bound the redirect
  chain it follows. A feature that only stores a destination and redirects the client is
  out of scope for this bullet.
- **Secrets**: Supplied via environment or secret store; never committed, never logged,
  never placed in specs, fixtures, or test data. Any accidental exposure is treated as an
  incident requiring rotation.
- **Least privilege**: Each component, credential, and agent tool grant is scoped to the
  minimum required. Broad or wildcard grants require the approval path in Principle II.
- **Operational bounds**: Timeout, bounded retry, fallback, rollback, and safe-stop are
  declared per operation (Principle VII) and are visible in the orchestration definition,
  not buried in call sites.
- **Data hygiene**: Logs, metrics, and traces exclude secrets and personal data;
  correlation identifiers are used in place of raw sensitive values.

## Development Workflow and Quality Gates

Work proceeds through the Spec Kit pipeline: `/speckit-constitution` →
`/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-implement`, with `/speckit-analyze` used to detect drift between artifacts.

Gates, each blocking:

1. **Spec gate** — Requirements, acceptance criteria, assumptions, and ambiguities are
   documented; no unresolved `[NEEDS CLARIFICATION]` markers remain unaddressed. (I)
2. **Plan gate** — Constitution Check passes; any violation is recorded in Complexity
   Tracking with the rejected simpler alternative. Human approval required for
   architecture and security decisions. (II, XI)
3. **Tasks gate** — Every task carries a requirement/user-story label and names its
   validating test artifact. (III)
4. **Implementation gate** — Tests written first and observed failing; unit, integration,
   workflow, and failure-path coverage present for critical and orchestration behavior. (IV)
5. **Review gate** — Security-sensitive and high-impact changes carry explicit human
   approval, recorded in the feature artifacts. (II, V, XII)
6. **Release gate** — Human confirmation of release readiness; observability signals
   (success rate, retries, rollbacks, MTTR, latency) are in place and reporting. (VIII, XII)

Change handling: when an upstream artifact changes, run the replanning path in Principle
IX — mark stale artifacts, re-plan the affected subgraph, and record the blast radius.
Do not restart the workflow.

## Governance

This constitution supersedes other practices, conventions, and agent defaults for this
project. Where guidance conflicts, the constitution wins; where it is silent, the stricter
of the two candidate practices applies.

**Amendment procedure**: Amendments are proposed as a written change to this file stating
the principle affected, the rationale, and the migration impact on in-flight features.
A human owner MUST approve the amendment (Principle XII); an agent may draft but not
ratify. On ratification, dependent templates and guidance files
(`.specify/templates/*`, `CLAUDE.md`) MUST be updated in the same change, and the Sync
Impact Report at the top of this file MUST be refreshed.

**Versioning policy**: Semantic versioning.

- **MAJOR** — a principle is removed or redefined in a backward-incompatible way, or a
  governance rule changes such that previously compliant work becomes non-compliant.
- **MINOR** — a new principle or section is added, or existing guidance is materially
  expanded.
- **PATCH** — clarification, wording, or typo fixes that do not change obligations.

**Compliance review**: The Constitution Check in `plan-template.md` is evaluated before
Phase 0 research and re-evaluated after Phase 1 design. Every review and merge verifies
compliance; violations block progression unless justified in Complexity Tracking and
approved by a human. `/speckit-analyze` is run before implementation to detect drift
between spec, plan, and tasks. Runtime development guidance lives in `CLAUDE.md`, which
MUST remain consistent with this document.

**Version**: 1.0.0 | **Ratified**: 2026-08-18 | **Last Amended**: 2026-08-18
