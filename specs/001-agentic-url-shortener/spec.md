# Feature Specification: Agentic URL Shortener

**Feature Branch**: `001-agentic-url-shortener` (spec directory; no git branch created — the git extension is not installed)

**Created**: 2026-08-18

**Status**: Approved & Planned — clarifications resolved 2026-08-18 (see Resolved Clarifications); architecture approved and Constitution Gate II cleared 2026-08-18 (plan.md § Architecture Approval Record); tasks generated and scoped to a 2–3 day budget (tasks.md § Deferred Capabilities). Requirements are unchanged by that scoping.

**Input**: User description: "Build a production-oriented URL shortener that also serves as the workload for demonstrating an agentic software-engineering orchestration system." (full description retained in the conversation record; functional scope reproduced below)

## Overview

This feature has two halves that must be specified together because each is the other's evidence:

1. **The workload** — a production-oriented URL shortener (create, resolve, expire, analyse, protect).
2. **The orchestration system** — an agentic software-engineering workflow that plans, executes, gates, and audits the delivery of that workload.

The shortener is what gets built. The orchestration system is what does the building, and its behaviour under three conditions — greenfield, brownfield, and ambiguous requirement — is the primary thing being demonstrated. A shortener delivered without a traceable, gated, auditable workflow does not satisfy this specification, and a workflow with no real workload to act on does not either.

## Clarifications

### Session 2026-08-18

- Q: Should the redirect be permanent or temporary? → A: Temporary and explicitly non-cacheable, so every follow reaches the service
- Q: Who is authorized to approve a checkpoint? → A: Holders of an explicit approver role, using an identity no agent can act under
- Q: What is the "nominal load" the redirect latency budget is measured at? → A: 100 redirects/second sustained against a 100,000-link corpus, matching NFR-005
- Q: How long are individual redirect events retained? → A: 90 days for individual events; summary counters and first/last timestamps persist for the life of the link
- Q: What is the short code's length and character set? → A: 7 characters, case-sensitive alphanumeric (62-symbol alphabet)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Shorten a link and follow it (Priority: P1)

A person or automated client submits a long HTTP/HTTPS destination and receives a short link. Anyone who follows that short link arrives at the original destination. The creator can set an optional expiry at creation time, and can revoke the link later.

**Why this priority**: This is the product. Without it there is no workload for the orchestration system to build, and no user-visible value at all. It is the smallest slice that is independently demonstrable and shippable.

**Independent Test**: Submit a valid destination, receive a short link, follow it in a browser, and land on the destination. Submit an invalid or non-HTTP(S) destination and receive a specific refusal without a link being created. Requires none of the orchestration system to be present.

**Acceptance Scenarios**:

1. **Given** a valid `https` destination, **When** a client requests a short link, **Then** the system returns a short link whose code is unique and not previously issued.
2. **Given** an existing unexpired short code, **When** a visitor follows it, **Then** the visitor is redirected to the exact destination recorded at creation.
3. **Given** a destination using a non-HTTP(S) scheme (`javascript:`, `data:`, `file:`, `ftp:`), **When** a client requests a short link, **Then** creation is refused with a specific reason and no link is stored.
4. **Given** a short code created with an expiry that has now passed, **When** a visitor follows it, **Then** the visitor is not redirected and receives an "expired" outcome distinct from "unknown".
5. **Given** a short code that was revoked by its creator, **When** a visitor follows it, **Then** the visitor is not redirected and receives a revoked/unavailable outcome.
6. **Given** a caller requesting a custom alias that is already taken or reserved, **When** creation is attempted, **Then** it fails with a conflict outcome and the existing link is left untouched.

---

### User Story 2 - Greenfield delivery through the orchestrated workflow (Priority: P1)

An engineering lead submits the requirement "provide short-link creation and resolution" to the orchestration system. The system states its interpretation, decomposes the requirement into tasks with explicit dependencies, executes independent tasks in parallel and dependent ones in order, pauses at defined gates, requests human approval for architecture and security decisions, and produces both the working capability and a complete audit trail linking every change back to the requirement.

**Why this priority**: This is demonstration scenario 1 and the core claim of the deliverable. It exercises decomposition, the dependency graph, parallelism with synchronisation, gates, approvals, persistence, and traceability in a single run.

**Independent Test**: Submit the greenfield requirement, observe the produced dependency graph before execution, watch parallel branches converge at a synchronisation point, approve the architecture checkpoint when prompted, and afterwards ask the system to trace any produced change back to its originating requirement and forward to its validating test. Testable independently of the brownfield and ambiguous scenarios.

**Acceptance Scenarios**:

1. **Given** a requirement statement, **When** it is submitted, **Then** the system records a written interpretation (scope, actors, constraints, identified ambiguities) before creating any implementation task.
2. **Given** an accepted requirement, **When** planning completes, **Then** the system produces a directed acyclic task graph with declared dependencies, and rejects the plan if a cycle exists.
3. **Given** a plan containing two tasks with no dependency between them, **When** execution runs, **Then** both are executed concurrently and a downstream synchronisation node does not begin until both reach a terminal state.
4. **Given** a stage with an entry gate whose criteria are unmet, **When** execution reaches it, **Then** the stage does not start and the gate failure is recorded with a reason.
5. **Given** an architecture decision point, **When** execution reaches it, **Then** the workflow pauses, surfaces the pending approval in the console, and does not proceed until a human decision with rationale is recorded against that checkpoint.
6. **Given** a completed run, **When** any produced change is selected, **Then** the system reports the requirement it satisfies and the test artifact that validates it.
7. **Given** a run interrupted mid-execution, **When** it is resumed, **Then** completed tasks are not re-executed and the recorded state matches the pre-interruption state.

---

### User Story 3 - Ambiguous requirement stops for human clarification (Priority: P2)

An engineering lead submits a deliberately unclear requirement (for example, "make the links smarter"). The system does not guess and does not implement. It records the specific ambiguities, states what it would need to know, and escalates to a human. Only after a human resolves the ambiguity does planning proceed.

**Why this priority**: This is demonstration scenario 3, and it is the safety claim of the whole system — bounded autonomy is only credible if refusal to act is observable. It ranks above brownfield because an agent that silently guesses is more dangerous than one that cannot yet enhance.

**Independent Test**: Submit the ambiguous requirement and confirm that no implementation task is created, that the recorded ambiguities name the specific unknowns, and that the workflow is in a halted state awaiting human input. Then supply a clarification and confirm planning resumes from the clarified requirement.

**Acceptance Scenarios**:

1. **Given** a requirement with an ambiguity that would change scope, security posture, or user-visible behaviour, **When** it is submitted, **Then** the system records the ambiguity explicitly and creates no implementation task.
2. **Given** a halted ambiguous requirement, **When** a human inspects the run, **Then** each ambiguity is stated as a specific answerable question, not a general complaint.
3. **Given** a halted ambiguous requirement, **When** no human responds, **Then** the run stays in `WAITING_FOR_HUMAN` with state preserved, no agent loop or retry timer remains active, and it does not time out into autonomous implementation.
4. **Given** a human-supplied clarification submitted through the console, **When** it is recorded, **Then** planning resumes and the clarification is captured in the decision lineage attributed to its human actor.

---

### User Story 4 - Brownfield enhancement with selective replanning (Priority: P2)

An engineering lead requests an enhancement to the already-delivered shortener — for example, improving redirect responsiveness or reliability. The system plans against the existing implementation rather than from scratch. When an upstream decision changes mid-run, it identifies only the affected downstream work, marks those artifacts stale, re-plans that subgraph, and preserves everything unaffected.

**Why this priority**: This is demonstration scenario 2 plus the dynamic-replanning claim. It depends on User Story 1 having produced something to enhance, which is why it sits below the greenfield run.

**Independent Test**: With the shortener in place, submit an enhancement requirement, then change an upstream decision partway through the run. Confirm the system reports the blast radius, marks only downstream artifacts stale, re-executes only those, and leaves unaffected completed tasks untouched.

**Acceptance Scenarios**:

1. **Given** an existing implementation, **When** an enhancement requirement is submitted, **Then** the plan references existing components and does not re-create capability that already exists.
2. **Given** a run in progress, **When** an upstream requirement or architecture decision changes, **Then** the system computes the affected downstream set from the dependency graph and reports it before acting.
3. **Given** a computed blast radius, **When** replanning executes, **Then** only affected nodes are marked stale and re-planned, and unaffected completed nodes retain their results.
4. **Given** a replan, **When** it completes, **Then** the replan event, its trigger, and its blast radius are recorded in the audit trail.
5. **Given** an enhancement that degrades a previously passing behaviour, **When** the exit gate evaluates, **Then** the stage is not marked complete and the regression is reported.

---

### User Story 5 - Link owner reviews click analytics (Priority: P3)

The client that created a link reviews how often it has been followed and when.

**Why this priority**: Valuable and explicitly requested, but the shortener is useful without it. It is additive to User Story 1 and independently deliverable.

**Independent Test**: Create a link, follow it several times, then request its analytics and confirm the count and timestamps reflect exactly the redirects performed.

**Acceptance Scenarios**:

1. **Given** a link followed three times, **When** its creator requests analytics, **Then** the cumulative redirect count is 3 with timestamps for each redirect.
2. **Given** a link never followed, **When** its creator requests analytics, **Then** a zero count is returned rather than an error.
3. **Given** a link created by another client, **When** analytics are requested, **Then** access is refused.
4. **Given** a redirect that failed because the link expired, **When** analytics are requested, **Then** that attempt is not counted as a successful redirect.
5. **Given** a link with more redirect events than one page holds, **When** its creator requests the event history, **Then** a bounded page is returned with a means to retrieve the next, and no single response returns the entire unbounded series.

---

### User Story 6 - Engineering lead reviews workflow reliability and audit trail (Priority: P3)

An engineering lead reviews how the orchestration system itself is performing: how often runs succeed, how often operations retry or roll back, how quickly failures are recovered, and how long runs take end to end — and can reconstruct any past run from its audit trail.

**Why this priority**: Required by the deliverable and by governance, but it reports on runs that must exist first. Independently deliverable once any run has completed.

**Independent Test**: Execute several runs including at least one failure and one rollback, then request the reliability report and confirm each metric matches the observed runs. Select any completed run and reconstruct its sequence of actions, decisions, approvals, and transitions from the audit trail alone — first through the console, then programmatically, confirming the two agree.

**Acceptance Scenarios**:

1. **Given** a set of completed runs, **When** the reliability report is requested, **Then** it reports success rate, retry frequency, rollback frequency, MTTR, and end-to-end latency.
2. **Given** any completed run, **When** its audit trail is retrieved, **Then** every agent action, decision, gate evaluation, approval, retry, failure, rollback, replan, and state transition appears with actor and timestamp, correlated by run identifier.
3. **Given** an audit trail, **When** it is inspected, **Then** it contains no secrets or personal data.
4. **Given** an audit record, **When** modification is attempted, **Then** the trail is append-only and prior records remain intact.
5. **Given** a run displayed in the console, **When** the same run is retrieved programmatically, **Then** the graph state, gate outcomes, decisions, approvals, and metrics are identical — the console adds no state of its own.

---

### Edge Cases

**Shortener**

- A destination is syntactically valid but absurdly long, or contains credentials, fragments, or unusual encodings.
- Two concurrent creation requests race for the same custom alias — exactly one must win, with no silent overwrite.
- Generated code collides with an existing code, or with a reserved path such as a health or administrative route.
- A short code is submitted with wrong case, padding, or characters outside the code alphabet.
- A link expires between the moment resolution begins and the moment the redirect is issued.
- A revoked link is followed by a caller holding a cached redirect.
- The same destination is submitted many times — does each submission yield a distinct code? (See Assumptions.)
- A destination's own server issues further redirects after the visitor arrives — outside this system's control, but must not be mistaken for this system redirecting.
- A client exceeds the creation rate limit mid-batch; already-created links must remain valid.
- Analytics are requested for a link that was created and then revoked.
- Event history is requested for a link whose redirects all predate the retention window — the summary still reports the true total while the history page is empty.

**Orchestration**

- The task graph as planned contains a cycle, or a task declares a dependency that does not exist.
- A parallel branch fails while its sibling succeeds — the synchronisation node must record both and apply the declared policy rather than hanging.
- Execution is interrupted between persisting a task result and persisting the state transition.
- A retry budget is exhausted and no fallback is declared.
- A rollback itself fails partway.
- A human approval is requested and never given.
- An upstream change invalidates work that is currently executing, not merely completed.
- A replan's blast radius is computed as the entire graph — the system must say so rather than silently restarting.
- An agent proposes a change with no traceable originating requirement.
- Two runs attempt to modify the same artifact concurrently.

## Requirements *(mandatory)*

### Functional Requirements — URL Shortener

- **FR-001**: System MUST create a short link when given a syntactically valid absolute destination URL using the `http` or `https` scheme.
- **FR-002**: System MUST refuse any destination that is not `http`/`https` — including `javascript:`, `data:`, `file:`, `ftp:`, relative, and scheme-relative URLs — MUST NOT store a link, and MUST return a distinct machine-readable reason.
- **FR-003**: System MUST refuse malformed destinations and destinations exceeding a published maximum length, each with a distinct machine-readable reason.
- **FR-004**: System MUST assign every new link a short code of 7 characters drawn from a case-sensitive alphanumeric alphabet of 62 symbols, unique across all codes ever issued, and MUST NOT reassign or overwrite a code already in use.
- **FR-005**: System MUST allow a caller to request a custom alias. An alias MUST use the same 62-symbol alphabet as generated codes and fall within a documented length range; an alias outside the alphabet or range MUST be refused as malformed. If the alias is already taken or reserved, creation MUST fail with a conflict outcome and MUST leave the existing link unmodified.
- **FR-006**: System MUST maintain a documented set of reserved paths (health, API, administrative routes) that can never be issued or claimed as short codes.
- **FR-007**: On resolution of a known, unexpired, unrevoked code, the system MUST redirect the caller to the exact destination recorded at creation. The redirect MUST be temporary and MUST be marked non-cacheable, so that every follow reaches the service, every follow is counted (FR-013), and revocation (FR-012) and expiry (FR-008) take effect on the next follow with no stale-cache window.
- **FR-008**: System MUST accept an optional expiry at creation. After expiry, resolution MUST NOT redirect.
- **FR-009**: System MUST return distinct machine-readable outcomes for each of: unknown code, expired code, malformed code, and revoked link.
- **FR-010**: System MUST NOT redirect to any destination supplied at resolution time (for example via query parameter). The only redirect target is the validated destination stored at creation.
- **FR-011**: System MUST canonicalise destinations for storage and comparison without altering the destination used for the redirect.
- **FR-012**: System MUST allow the creating client to revoke a link, after which resolution MUST NOT redirect.
- **FR-013**: System MUST record a timestamp for every successful redirect and maintain a cumulative redirect count per link. Individual redirect events MUST be retained for at least 90 days from the redirect; the cumulative count and the first and most recent redirect timestamps MUST persist for the life of the link and MUST NOT be reduced when older events age out.
- **FR-014**: System MUST expose per-link analytics to the client that created the link, and MUST refuse the request from any other client. The analytics **summary** MUST report total redirect count, first redirect timestamp, and most recent redirect timestamp. The redirect **event history** MUST be exposed through a paginated contract with a bounded maximum page size and a stable ordering, never as an unbounded response, and MUST state the retention window so a caller can tell an empty page from an aged-out one.
- **FR-015**: System MUST rate-limit link creation per identified client and MUST return a distinct throttling outcome when the limit is exceeded, without creating a link.
- **FR-016**: All shortener operations other than the redirect itself MUST be available to automated clients through a documented, versioned contract with machine-readable request and response shapes and stable error identifiers. The redirect itself MUST work in a standard browser with no client-side scripting.
- **FR-017**: The shortener MUST NOT include a web frontend as a deliverable. Link creators interact with it programmatically; visitors interact with it only by following a redirect. The contract required by FR-016 MUST nonetheless be sufficient for a frontend to be built against it later without contract changes.
- **FR-018**: The system MUST NOT issue any outbound network request to a caller-supplied destination URL — not at creation, not at resolution, not during analytics. Destinations are validated syntactically, stored, and returned to the client; they are never fetched by the server. Any future capability requiring dereferencing is a new requirement subject to Constitution gate V-a and MUST NOT be introduced silently.

### Functional Requirements — Agentic Orchestration

- **FR-020**: System MUST accept a natural-language requirement and record a written interpretation — scope, actors, constraints, and identified ambiguities — before creating any implementation task.
- **FR-021**: System MUST decompose an accepted requirement into discrete tasks, each with declared inputs, outputs, responsible actor (agent or human), and explicit dependencies.
- **FR-022**: System MUST represent the plan as a directed acyclic graph, and MUST detect and reject cycles before execution begins.
- **FR-023**: System MUST execute tasks whose dependencies are satisfied concurrently, and MUST NOT start any task while a predecessor is unfinished.
- **FR-024**: System MUST support synchronisation nodes where parallel branches rejoin. A synchronisation node MUST NOT release downstream work until every inbound branch reaches a terminal state, and MUST record the outcome of each branch.
- **FR-025**: System MUST persist workflow state — graph, node states, decisions, approvals, artifacts — at every transition, such that an interrupted run is inspectable while stopped and resumable without repeating completed work.
- **FR-026**: Every stage MUST declare an entry gate and an exit gate with evaluable criteria. A stage MUST NOT start until its entry gate passes and MUST NOT be reported complete until its exit gate passes. Every gate evaluation MUST be recorded with outcome and reason.
- **FR-027**: System MUST record decision lineage for every material decision: alternatives considered, the selection, the rationale, the deciding actor, the timestamp, and the requirement or task it serves.
- **FR-028**: System MUST identify ambiguities in a submitted requirement and record each explicitly. Where an ambiguity would change scope, security posture, or user-visible behaviour, the workflow MUST halt and request human clarification rather than implement a guess.
- **FR-029**: System MUST pause and obtain recorded human approval before high-impact architecture decisions, security-sensitive changes, destructive operations, and release actions. Approval MUST come from a holder of an explicit **approver role**; an approval recorded by any identity lacking that role MUST be rejected. The system MUST NOT proceed without a valid approval and MUST NOT permit an agent to record approval on a human's behalf.
- **FR-030**: Every automated operation MUST declare a timeout, a maximum retry count, and a backoff policy before it runs. Unbounded retries and open-ended execution are prohibited.
- **FR-031**: On timeout or retry exhaustion, the system MUST take the operation's declared fallback or perform a safe-stop. A safe-stop MUST halt further execution, preserve state, and escalate to a human with the reason.
- **FR-032**: Reversible operations MUST declare a rollback that restores the prior state; rollback attempts and their outcomes MUST be recorded. Irreversible operations MUST be declared as such and are subject to the approval requirement in FR-029.
- **FR-033**: When an upstream requirement or decision changes, the system MUST compute the affected downstream set from the dependency graph, report that blast radius, mark only those artifacts stale, re-plan only that subgraph, and preserve unaffected completed work. A full restart MUST NOT be the default response.
- **FR-034**: System MUST maintain bidirectional traceability: for any requirement it MUST report the tasks, changes, and validating tests that serve it; for any change it MUST report the requirement that motivated it.
- **FR-035**: System MUST refuse or flag any task that has no traceable originating requirement.
- **FR-036**: System MUST append an audit record for every agent action, decision, gate evaluation, approval, retry, failure, rollback, replan, and workflow transition, correlated by run identifier and carrying actor and timestamp. Audit records MUST be append-only.
- **FR-037**: System MUST compute and report, per run and across runs: success rate, retry frequency, rollback frequency, mean time to recovery, and end-to-end workflow latency.
- **FR-038**: Audit records, logs, and metrics MUST exclude secrets and personal data.
- **FR-039**: System MUST block work that falls outside the approved scope of the current run and surface it for human decision rather than absorbing it silently.
- **FR-040**: System MUST NOT modify governance artifacts — the constitution, approval policy, or gate definitions — without explicit human approval.
- **FR-041**: An agent MAY implement a **bounded task** — one whose interface, acceptance criteria, dependencies, and security constraints are all already approved. Bounded tasks include component implementation, work against approved API contracts, persistence mappings, tests, documentation, and refactoring within an established boundary. An agent MUST NOT autonomously introduce a new service or datastore, alter architecture or security policy, modify governance artifacts, or perform a release or deployment; each of those remains a human decision reached through an approval checkpoint (FR-029, FR-040). A task missing any of the four approved preconditions is not bounded and MUST NOT be agent-authored.
- **FR-042**: Every task node MUST declare its execution mode — agent-authored or human-executed — at planning time. The mode MUST NOT be escalated from human-executed to agent-authored during execution; a change of mode requires replanning and human approval.
- **FR-043**: An agent-authored change that would cross an approval checkpoint (architecture, security-sensitive, destructive, or release) MUST halt for human approval *before* the change is applied, not after.
- **FR-044**: Every agent-authored change MUST be revertible: the system records the prior state of each modified artifact and can restore it under FR-032.
- **FR-045**: The orchestration system MUST provide a human-facing console that displays, for any run: the dependency graph with per-node state, gate evaluations with outcomes, pending approval requests, pending clarification requests, decision lineage, and the audit trail.
- **FR-046**: The console MUST let a human record an approval or rejection with rationale and submit an answer to a clarification request. Every such action MUST be attributed to the identified human actor in the audit trail.
- **FR-047**: The console MUST display the reliability metrics required by FR-037, per run and across runs.
- **FR-048**: The console MUST be a view over recorded state, never the sole location of it. Everything the console displays MUST also be retrievable programmatically, so that runs remain verifiable headlessly.
- **FR-049**: When a run requires human clarification (FR-028) or human approval (FR-029, FR-043), automated execution MUST stop. The run MUST persist in a `WAITING_FOR_HUMAN` state that survives process restart, and while in that state no agent loop, retry timer, polling cycle, or other compute attributable to the run MUST remain active. The state MUST NOT expire, time out, or otherwise resume into autonomous execution; only a recorded human response resumes the run.
- **FR-050**: The approver identity MUST be one that no agent can act under. The system MUST reject and audit any approval attempt originating from an identity available to agent execution, and MUST NOT allow the approver role to be granted to such an identity.

### Non-Functional Requirements

- **NFR-001** *(performance)*: At the nominal operating point defined in NFR-005 — 100 redirects per second sustained against a corpus of 100,000 stored links — 95% of redirects complete within 150 ms of request receipt, and 99% within 400 ms.
- **NFR-002** *(availability)*: The redirect path remains available independently of the analytics and orchestration surfaces; degradation or outage of analytics or orchestration MUST NOT prevent redirects.
- **NFR-003** *(durability)*: No acknowledged link creation and no recorded workflow transition is lost across process restart.
- **NFR-004** *(auditability)*: Audit records are append-only and retained for the life of the deliverable; any run can be reconstructed from its trail alone.
- **NFR-005** *(scale)*: The shortener sustains at least 100 redirects per second against at least 100,000 stored links without degradation beyond NFR-001. This is the nominal operating point; NFR-001 and NFR-005 are verified by the same load test.
- **NFR-006** *(security)*: All external input is validated and normalised at the boundary; secrets never appear in source, logs, or test fixtures; every component runs with least privilege. Scheme allow-listing and open-redirect prevention apply to all URL-accepting paths.
- **NFR-007** *(observability)*: Every orchestration action and every shortener error path emits a structured, correlated record sufficient to diagnose it without reproducing it.
- **NFR-008** *(maintainability)*: Components are independently testable with injectable dependencies and no hidden global state; public interfaces and non-obvious decisions carry documented rationale.
- **NFR-009** *(bounded cost)*: Every orchestration run declares a ceiling on wall-clock duration and on retry attempts, and stops safely rather than exceeding it.

### Key Entities

- **ShortLink**: A mapping from a short code to a destination. Attributes: code (7 characters, 62-symbol case-sensitive alphanumeric alphabet, or a custom alias within the documented length range), destination, creating client, creation time, optional expiry, revocation state.
- **RedirectEvent**: A single successful resolution of a short code, retained for 90 days. Attributes: link reference, timestamp.
- **Requirement**: A submitted statement of desired capability, with its recorded interpretation, identified ambiguities, and resolution state.
- **WorkflowRun**: One execution of the orchestration system against a requirement. Attributes: run identifier, requirement reference, current state (including `WAITING_FOR_HUMAN`), what it is waiting on, start and end times.
- **TaskNode**: A discrete unit of work in the graph. Attributes: inputs, outputs, responsible actor, dependencies, execution state, staleness.
- **Gate**: An entry or exit condition on a stage, with evaluable criteria and recorded outcomes.
- **ApprovalRecord**: A human decision on a checkpoint. Attributes: checkpoint, human actor, approver role held at the time, decision, rationale, timestamp.
- **DecisionRecord**: A material choice made during a run. Attributes: alternatives, selection, rationale, actor, timestamp, served requirement or task.
- **AuditEvent**: An append-only record of one action, decision, transition, or failure, correlated by run identifier.
- **ReplanEvent**: A recorded selective replan. Attributes: trigger, computed blast radius, artifacts marked stale, resulting graph change.
- **TraceLink**: The connection binding a requirement to its tasks, changes, and validating tests in both directions.
- **ChangeRecord**: One modification to a source artifact. Attributes: task reference, execution mode (agent-authored or human-executed), prior state for revert, applied time, approving human where required.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person can turn a long destination into a working short link and follow it to that destination in under 30 seconds, with no prior training.
- **SC-002**: With 100,000 links stored and 100 follows per second sustained, 95% of link follows deliver the visitor to the destination within 150 ms of the request being received; 99% within 400 ms.
- **SC-003**: 100% of submitted destinations using a non-HTTP(S) scheme are refused, with zero such links created across the test corpus.
- **SC-004**: Every distinct failure condition — unknown, expired, malformed, revoked, conflicting alias, rate-limited — is distinguishable by an automated client without parsing prose.
- **SC-005**: Across 10,000 link creations, zero code collisions result in an existing link being overwritten or reassigned.
- **SC-006**: Reported click counts match the number of successful redirects exactly, with no over- or under-count, across a test run of at least 1,000 redirects — including after events older than the retention window have aged out, when the cumulative count MUST remain unchanged.
- **SC-007**: The greenfield requirement is delivered end to end by the orchestration system, and 100% of resulting changes can be traced to an originating requirement and forward to a validating test.
- **SC-008**: A run containing at least two independent tasks demonstrably executes them concurrently, and the downstream synchronisation point begins only after both complete.
- **SC-009**: 100% of architecture, security, destructive, and release checkpoints in a run halt for human approval; zero proceed without a recorded decision from an approver-role holder, and an approval attempted from an agent-available identity is rejected and audited.
- **SC-010**: The deliberately ambiguous requirement produces zero implementation tasks and zero code changes, and yields at least one specific, answerable clarification question.
- **SC-011**: On an upstream change during the brownfield run, the system re-plans strictly the affected subgraph — unaffected completed tasks are not re-executed, and the reported blast radius matches the graph's actual dependency closure.
- **SC-012**: An interrupted run resumes with zero completed tasks re-executed and zero lost state transitions.
- **SC-013**: Any completed run can be fully reconstructed from its audit trail alone — actions, decisions, approvals, retries, failures, rollbacks, and transitions — by a reviewer who did not observe the run.
- **SC-014**: Success rate, retry frequency, rollback frequency, MTTR, and end-to-end latency are reported for every run and agree with independently observed run outcomes.
- **SC-015**: Zero secrets or personal data appear in audit records, logs, or metrics across all demonstration runs.
- **SC-016**: No automated operation in any demonstration run retries unboundedly; every failure terminates in a declared fallback, rollback, or safe-stop.
- **SC-017**: Zero outbound requests to caller-supplied destinations occur across all demonstration runs, observable by monitoring network egress during the full test corpus.
- **SC-018**: 100% of agent-authored changes are revertible, demonstrated by reverting at least one and confirming the prior state is restored exactly.
- **SC-019**: Zero task nodes change execution mode from human-executed to agent-authored during execution across all demonstration runs.
- **SC-020**: A reviewer who did not observe a run can, from the console alone, identify its current state, approve a pending checkpoint, and answer a pending clarification — and each action appears in the audit trail attributed to them.
- **SC-021**: A run left in `WAITING_FOR_HUMAN` consumes zero compute attributable to it, survives a process restart with its state and pending request intact, and resumes only on a recorded human response — verified over a wait spanning at least one restart.

## Assumptions

- **Actors**: Three roles interact with the system — a *link creator* (human or automated client) who creates and revokes links, a *visitor* who follows short links anonymously, and an *engineering lead* who submits requirements to the orchestration system and answers its clarification requests. The engineering lead holds the *approver role* required by FR-029; that identity is never one agents run under (FR-050).
- **Client identity**: Link creators are identified by an issued API credential rather than end-user accounts. This is what makes per-client rate limiting (FR-015) and owner-scoped analytics (FR-014) enforceable. No end-user registration, login, password reset, or profile management is in scope.
- **Visitor anonymity**: Following a short link requires no identity. Analytics therefore count redirects and record timestamps; they do not profile visitors. This keeps personal data out of the system entirely, satisfying NFR-006 and SC-015 by construction.
- **Duplicate destinations**: Each creation request yields a new distinct short code, even for a destination that has been shortened before. Deduplication is not performed, because two callers shortening the same destination legitimately need independently revocable and independently measurable links.
- **Expiry semantics**: Expiry is absolute (a point in time), not a countdown of uses. Links without an expiry live until revoked.
- **Code space**: A 7-character code over 62 symbols yields roughly 3.5 trillion possibilities, which keeps generated-code collisions vanishingly rare at the 100,000-link scale of NFR-005 and leaves room well beyond it. Codes are case-sensitive, so they are precise to transmit but poor to dictate aloud — acceptable because links are shared by copy, not by voice.
- **Analytics retention**: Individual redirect events age out after 90 days; the aggregate counters do not. This bounds storage growth — at the NFR-005 operating point the event series would otherwise grow by roughly 8.6 million rows per day of sustained traffic — while keeping the totals in FR-014 permanently exact.
- **Security posture** *(resolved, A3)*: The shortener stores a destination and redirects the client to it; the server never fetches the destination (FR-018). Under Constitution Principle V this means scheme allow-listing, canonicalisation, and open-redirect prevention apply and are mandatory, while SSRF and private-address controls are correctly out of scope — Constitution gate V-a is N-A for this feature. Introducing any server-side fetch would reverse this and requires a new requirement, not an implementation decision.
- **Agent authorship boundary** *(resolved, A1)*: An agent may implement any task whose interface, acceptance criteria, dependencies, and security constraints are already approved — components, approved contracts, persistence mappings, tests, documentation, refactoring (FR-041). What stays human is the act of *establishing* those things: introducing a service or datastore, changing architecture or security policy, changing governance, and releasing. This keeps autonomy on the reversible side of the blast-radius line drawn by Constitution Principle II.
- **Console scope** *(resolved, A2)*: The human-facing surface belongs to the orchestration system, not the shortener (FR-017, FR-045-FR-048). The shortener is exercised programmatically and through browser redirects. The console is a view over recorded state and adds none of its own, so every demonstration remains verifiable headlessly.
- **Ambiguous-requirement demonstration**: The deliberately unclear requirement for scenario 3 will be a capability request whose scope, not merely its wording, is undetermined — for example "make the links smarter" — so that no reasonable default exists and halting is the only correct behaviour.
- **Brownfield demonstration**: The enhancement for scenario 2 targets redirect responsiveness or reliability, operating on the implementation produced by the greenfield run rather than a separately seeded codebase.
- **Human availability**: A human is reachable to answer approval and clarification requests during demonstration runs. When no human responds, the run holds `WAITING_FOR_HUMAN` indefinitely and consumes nothing while it waits (FR-049) — waiting is always safe, guessing is not. Waiting is therefore a persisted state, not a blocked process.
- **Deployment scope**: "Production-oriented" describes engineering quality — modularity, testability, security, observability, documented behaviour — not a requirement to operate a publicly hosted, on-call production service. The deliverable must run and be demonstrable in a local or equivalent environment.
- **Persistence**: Workflow state and links survive process restart (NFR-003). The specification does not assume any particular storage technology; that is a planning decision.

## Out of Scope

- End-user accounts, registration, login, and password management.
- Visitor-level tracking, profiling, geolocation, device fingerprinting, or referrer analytics beyond redirect counts and timestamps.
- Custom or vanity domains for short links.
- Bulk import or export of links, and link editing after creation (links are created and revoked, not mutated).
- Malware, phishing, or content-reputation scanning of destinations — these would require the server to fetch or look up the destination, which FR-018 prohibits.
- Any web frontend for the shortener itself; the console covers the orchestration system only.
- Multi-tenant administration, billing, and quota management beyond the rate limiting in FR-015.
- Applying the orchestration system to workloads other than this shortener.
- Choice of languages, frameworks, storage engines, or hosting — deferred to `/speckit-plan` per the instruction not to select technologies at specification time.

## Resolved Clarifications

All three ambiguities identified at specification time were resolved by the requirement
owner on 2026-08-18. Recorded here as decision lineage (Constitution Principles III
and VIII); the resulting obligations are carried in the requirements above.

| ID | Requirement | Question | Decision |
|----|-------------|----------|----------|
| A1 | FR-041-FR-044 | Does the orchestration system author code, or only govern the workflow? | **Hybrid.** An agent may implement any bounded task — interface, acceptance criteria, dependencies, and security constraints already approved. Introducing services or datastores, changing architecture or security policy, changing governance, and releasing stay human. Execution mode is fixed at planning time and cannot be escalated mid-run. |
| A2 | FR-017, FR-045-FR-048 | Is a web frontend a deliverable, and for which half? | **Console for the orchestration system.** It shows the dependency graph, gates, approvals, clarifications, decision lineage, audit trail, and metrics. The shortener remains API-only, and its contract stays frontend-capable for later. |
| A3 | FR-018 | Does the service dereference destination URLs server-side? | **No.** Store and redirect only; no outbound request to a caller-supplied URL, ever. Constitution gate V-a is therefore N-A for this feature, and SSRF controls are out of scope by construction rather than by omission. |

**Consequence for planning**: A1 makes revertibility of agent-authored changes a
first-class requirement (FR-044) rather than a nice-to-have. A2 adds a delivery surface
but deliberately keeps it stateless with respect to the run record (FR-048), so it cannot
become a source of truth. A3 removes an entire class of security control from scope — the
plan's Constitution Check should mark gate V-a as N-A and cite FR-018.
