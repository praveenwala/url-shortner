# Constitution re-evaluation — evidence package (T104)

**Prepared:** 2026-08-20 · **Task:** T104 `[HUMAN]` · **Status: RE-EVALUATED AND PASSED by the human reviewer, 2026-08-20 — release-ready for the take-home prototype.** See §5.

> **Evidence assembled by an agent; every gate decision and the release decision made by a human.**
> §1–§3 were prepared by an agent to make the re-evaluation efficient. The thirteen gate decisions
> in §4 and the release decision in §5 were made by the human reviewer on 2026-08-20.
> **No agent made, influenced, or recorded any of them.** Release readiness is a human judgement
> under Principle XII, and it was exercised as one.

Every status below was **re-verified during this review**, not carried forward from an earlier
run. Where a control is asserted only by inspection rather than execution, that is stated.

---

## 1. Gate II delta review

### 1.1 What actually changed

The only baseline that matters is: has anything outside documentation moved since Gate II was
approved on 2026-08-18?

```
runtime source modified (orchestrator/src, shortener/src/main, console/src) : 0
contracts / OpenAPI artifacts modified                                       : 0
plan.md modified                                                             : 0  (tracked, clean)
```

Working tree at review time — documentation, tests-for-documentation, and task bookkeeping only:

| Path | Nature |
|---|---|
| `README.md` | **new** (T101), edited six times during T103 |
| `docs/HLD.md`, `docs/LLD.md` | **new** (T101) |
| `docs/security/security-review.md` | **new** (T102) |
| `docs/validation/` | **new** (T103, T104) |
| `specs/…/baseline.md` | **new** (T022, human-authored result) |
| `ops/smoke/` | **new** — a read-only pre-flight script; not runtime code |
| `docs/traceability/requirements-traceability.md` | updated — SC-001 and NFR-008 closed |
| `orchestrator/tests/contract/test_traceability_matrix.py` | updated — `DECLARED_GAPS` emptied |
| `specs/…/tasks.md` | updated — task completion records |

**Note on the diff baseline:** `README.md` is untracked, so there is no in-repo diff against Gate
II. It did not exist at Gate II — it was created by T101 *after* approval. The six T103 changes are
therefore edits within a post-approval document, which strengthens rather than weakens the
conclusion below: no artifact that Gate II ruled on has been altered.

### 1.2 The six T103 changes, assessed individually

| # | Change | Alters architecture? | Widens scope? | Changes security posture? | Changes a public contract? | Weakens a gate? |
|---|---|---|---|---|---|---|
| 1 | Disposable-container reset (`docker rm -f …`) before §6a | No | No | No — scoped explicitly to throwaway quickstart containers, with a warning not to force-remove a database that matters | No | No |
| 2 | Host-side credential verification via `psycopg` | No | No | **Strengthens** — proves the documented credentials authenticate over the path the application uses | No | No |
| 3 | Liveness (`/health`) vs readiness (`/v1/runs`) distinction | No | No | No | No — describes existing endpoint behaviour | No |
| 4 | Deterministic `until … pg_isready` readiness loop | No | No | No | No | No |
| 5 | Unknown-run 404 negative control in §11 | No | No | No | No — asserts behaviour that already existed and is CI-gated | No |
| 6 | Documented unknown-parent collection-endpoint limitation in §20 | No | No | No — explicitly recorded as API semantic debt, not a security defect | **No** — records existing behaviour; nothing in `routes.py` or either OpenAPI artifact changed | No |

Change 6 is the only one that touches how the API is *described*. It documents behaviour that was
already shipped and CI-gated: `GET /v1/runs/{id}` returns 404 for an unknown run, while `/graph`,
`/gates`, `/audit`, `/decisions` and `/pending` return 200 with empty results. Confirmed by
observation during T103 §G5 and by the contract layer passing unchanged (**28 passed**). The human
reviewer ruled during T103 that this behaviour stays as-is.

### 1.3 Conclusion

**All six changes are documentation-only. None alters architecture, widens scope, changes security
posture, changes a public contract, or weakens a gate.**

> **Gate II remains valid. No re-approval is required.**

The Gate II record in `plan.md` is intact, including the Architecture Approval Record, the
authoritative NFR-002 interpretation, and the Docker addendum scoping the daemon to `run_tests`.

---

## 2. Principle-by-principle re-evaluation

### I. Specification-First Development — **PASS**

**Evidence.** 79 requirements in `spec.md`, all classified: 77 COVERED, 2 DEFERRED_APPROVED, 0 GAP.
Every requirement is cited by at least one task. Approved deferrals — FR-005 custom aliases, FR-015
rate limiting — remain explicit in `tasks.md § Deferred Capabilities`, in the traceability matrix,
and in README §20, and are proven absent by `OpenApiParityTest#approvedDeferralsRemainAbsent`
(the document contains no `alias`, no `rate_limit`).

**Deviation.** No undocumented feature creep found. Partial deferrals (FR-013 retention half,
FR-014 history half, FR-026 regression scenario, FR-033 plan-against-existing scenario, FR-045 /
FR-047 console screens) are registered rather than silent.

**Human action required:** none.

### II. Controlled Agent Autonomy — **PASS**

**Evidence, re-executed this review.**

| Control | Result |
|---|---|
| Agent cannot self-approve; `agent:` identity can never hold the approver role | `test_approval_integrity.py` — **9 passed** |
| Governance artifacts unreadable and unwritable by an agent | `test_governance_protection.py` — **15 passed** |
| Out-of-scope work halts and surfaces; scope widens only by approved decision | `test_guardrails.py` — **14 passed** |
| Exactly four model-visible tools; no shell, git, package, network, or MCP | `test_capability_boundary.py` — **14 passed** |
| Execution mode never escalated human → agent | `test_mode_escalation.py` — **9 passed** |

Architecture, security and governance decisions remain human-controlled: `tasks.md` records
checkpoint 2d as *"capability-boundary decisions HUMAN-APPROVED; implementation agent-assisted
under that approved boundary — no architecture approval was recorded by an agent."*

**Deviation.** None. **Human action required:** none.

### III. Requirement Traceability — **PASS**

**Evidence.** `test_traceability_matrix.py` — **11 passed**, enforcing that no requirement
disappears from the matrix, no cited task id stops existing, no new GAP appears, and no deferred
capability ships without the register being updated. Bidirectional traceability is a live
capability (`TraceStore.for_requirement`, `requirement_for_change`, `untraceable_changes`), not
only a document. Counts: **79 / 77 / 2 / 0**.

**Deviation — disclosed, not Constitution-violating.** The T100 audit found ten completed tasks
citing research decisions or Constitution principles instead of an FR/NFR/SC id, contrary to
`tasks.md`'s own `(REQ)` rule, and twelve stale file paths in completed tasks where the work exists
under a different filename. **No completed task was found whose behaviour is unimplemented or
untested.** Recorded in the traceability audit §5.1–5.2.

**Human action required:** a decision on whether the ten `(REQ)`-less tasks are corrected before
release or accepted as bookkeeping debt.

### IV. Test-First Quality (NON-NEGOTIABLE) — **PASS with a disclosed gap**

**Evidence.** Five layers across three stacks. Orchestrator 316 tests (failure layer 157);
shortener 27 unit + 44 contract + integration/failure via `verify`; console 49. Integration runs
against real PostgreSQL via Testcontainers, never an in-memory substitute.

Human validations are correctly attributed: **T022** (SC-001 timing, human-executed and
human-timed), **T102** (security review, human decision), **T103** (quickstart validation, human
observations). No agent made any of those decisions.

**Failed and invalidated evidence was preserved rather than rewritten as success** — the specific
discipline this principle depends on:

- T103's original E4 500 is retained as a FAIL with full root-cause analysis; neither earlier
  attempt was retroactively marked PASS.
- Evidence gathered against stale containers was reclassified **INVALID**, not quietly kept.
- Five H-section test counts and A5 are recorded as **"not captured"** rather than reconstructed
  from README expectations.
- The agent-caused side effect that polluted `shortener_db` mid-validation is disclosed in the
  record, along with the remediation.

**Deviation.** The orchestrator `unit` marker selects **one** test, and that test is an endpoint
test filed under `tests/integration/`. Orchestrator logic is covered at the workflow and failure
layers; what is missing is the layer Principle IV names separately. Disclosed in README §12,
traceability §6.2 and HLD §18.

**Human action required:** accept the thin unit layer as prototype-appropriate, or require backfill
before release.

### V. Security by Design — **PASS (T102 APPROVED WITH CONDITIONS)**

**Evidence.** `docs/security/security-review.md`: 51 controls — **47 PASS, 4 ACCEPT-RISK, 0 FAIL**;
ten accepted risks with the reviewer's stated basis; **no new security defect found**. Database
isolation, audit immutability by privilege, the four-tool boundary, sandbox controls and egress
controls were verified by execution against a throwaway provisioned cluster.

**All six binding conditions re-verified against the current, post-T103 documentation:**

| Condition | Status |
|---|---|
| 1. `X-Actor-Id` documented as demo identity only, never production auth | **HOLDS** — 2 explicit statements in README; **0** contradicting claims |
| 2. No shared/production deployment without real auth, TLS, console access control | **HOLDS** — stated in README §8 and §20 |
| 3. Egress guard described as defense-in-depth; container networking is the boundary | **HOLDS** — present in README, HLD (×2), LLD, egress-verification, security-review (×4) |
| 4. Rate limiting remains an explicitly approved deferral | **HOLDS** — README ×2, traceability FR-015 `DEFERRED_APPROVED` |
| 5. Local credentials not presented as production practice | **HOLDS** — 14 labelled mentions; `provision.sh` steers to a different production mechanism |
| 6. No accepted risk silently removed | **HOLDS** — all **10** J-risks and all **6** §5 entries still present |

**Gate V-a (unsafe-target prevention): N-A, unchanged.** FR-018 prohibits any outbound request to a
caller-supplied URL. Verified in T099 by a real HTTP listener recording **zero** requests across
creation, resolution, analytics, revocation and rejection. Any future dereferencing capability
re-triggers this gate.

**Deviation.** Four ACCEPT-RISK controls (B7, E7, G7, I6) and ten accepted risks, all documented.

**Human action required:** confirm the T102 approval and its conditions still stand at release.

### VI. Stateful Orchestration — **PASS**

**Evidence, re-executed.** Entry/exit gates recorded pass or fail (`test_gates.py` — **5 passed**);
state persists at every transition and resume re-executes nothing (`test_resume.py` — **5 passed**).
Durable across 18 tables in two PostgreSQL databases: gates, approvals, clarifications, replan
events, audit and lineage all have their own tables. Run and node state sets are closed, with
validated transitions.

**Deviation.** None. **Human action required:** none.

### VII. Resilience and Bounded Autonomy — **PASS**

**Evidence, re-executed.**

| Control | Result |
|---|---|
| Timeout, max attempts, capped backoff, declared fallback; policy frozen and never handed to the operation | `test_bounds.py` — **16 passed** |
| Missing Docker or image never causes unsandboxed fallback | `test_fail_closed_real.py` — **5 passed**, against a genuinely unreachable daemon |
| Human wait consumes no compute — no thread, timer or background worker | `test_waiting_quiescence.py` — **5 passed** |

`run_tests` fails closed with `SandboxUnavailable`, safe-stops, preserves state, audits the reason,
and never runs on the host — confirmed by a `subprocess.run` interceptor showing no non-`docker`
process executed. HUMAN-verified independently at T103 §C3.

**Deviation.** Risk G7: a thread-based timeout bounds the caller's wait, not the runaway thread.
Accepted at T102 because untrusted agent-authored work runs in a container whose wall-clock limit
is enforced by `docker kill`.

**Human action required:** none beyond the standing G7 acceptance.

### VIII. Observability and Auditability — **PASS**

**Evidence, re-executed.** `test_lineage_and_rollback.py` — **8 passed**: decision lineage persists
every required field; the repository exposes no update or delete path; the runtime role cannot
`UPDATE`, `DELETE` or `TRUNCATE` audit records; change records carry run and task linkage; rollback
links to the original change; a failed rollback safe-stops and is audited; requirement → task →
change → test round-trips; a change with no requirement is reported as untraceable.

Audit immutability is enforced **at the database** — `orchestrator_app` holds INSERT and SELECT
only, verified live during T102 (`update=f delete=f truncate=f`, and a self-`GRANT` proven to be a
no-op). Five metrics computed per run and across runs, with `null` (unknown) rendered distinctly
from `0` (measured zero), and human wait excluded from MTTR and latency.

**Deviation.** None. **Human action required:** none.

### IX. Dynamic Replanning — **PASS**

**Evidence, re-executed.** `test_selective_replan.py` — **18 passed**: closure-only invalidation;
the whole DAG is not rebuilt; unaffected successful nodes stay `SUCCEEDED`; stale nodes keep their
state **and their result**; replacements link via `supersedes` and prior results stay queryable;
execution mode is recalculated but never silently escalated; a replan introducing a cycle is
rejected; a change adding a component halts for architecture approval and implements nothing.

**Deviation.** None. **Human action required:** none.

### X. Production Engineering Quality — **PASS**

**Evidence.** Stable flat error contracts on both services (`{"error","message"}`), additive-only
within a major version, CI-gated for OpenAPI parity on both surfaces (**28 passed** this review).
Database ownership boundaries: two databases, four roles, no credential spanning both, verified
live at T102. Public interfaces documented with rationale in **LLD §17** — why each exists, who
calls it, why the boundary is shaped that way, and why alternatives were rejected — covering all
six named interfaces. HLD, LLD and README complete; T103 confirmed the README takes a reviewer from
a clean clone to a working system.

Known limitations are disclosed rather than buried: HLD §18, README §20, traceability §5–6,
security-review §5, quickstart-validation §10.

**Deviation.** None material. **Human action required:** none.

### XI. Simplicity over Unnecessary Complexity — **PASS**

**Evidence, re-verified.** Redis appears in **zero** dependency manifests (`pom.xml`,
`pyproject.toml`, `package.json`) and **zero** times in either OpenAPI artifact. Three services and
two PostgreSQL databases — no component added since Gate II.

The exclusion is evidence-based, not preference: T098 measured p95 **6.82 ms** against a 150 ms
budget (~22× headroom) and p99 ~11 ms against 400 ms, at 100 rps over 100,000 links with zero
errors. Research R13 permits a cache tier only on a **measured** budget breach attributed to
datastore access with cheaper rungs exhausted — the first condition is not met, so the ladder does
not begin.

The brownfield path can still introduce one if evidence changes, and the mechanism is enforced:
`CACHE_TIER` sits in `NEW_COMPONENT_OPTIONS`, so proposing it halts for architecture approval and
implements nothing (`test_a_new_component_halts_for_approval_and_implements_nothing`,
`test_default_choice_is_the_cheapest_rung_not_redis`, `test_redis_is_only_reachable_when_every_cheaper_rung_is_exhausted`).

**Deviation.** None. **Human action required:** none.

### XII. Human Ownership — **PASS**

**Evidence.** T006, T007, T022, T102 and T103 all carry `[HUMAN]` and human-attributed completion
notes. **Zero** occurrences of an agent recorded as approver across `tasks.md`, `plan.md` and the
security review. Specifically:

- **T022** — timing human-observed and human-provided; an agent verified the resulting link
  technically, after the fact, and recorded the elapsed time in the participant's own words.
- **T102** — 51 control decisions, 10 risk acceptances and 6 conditions all decided by the
  reviewer; the agent assembled evidence only.
- **T103** — every PASS/FAIL/N/A observed by the reviewer; the agent presented the checklist,
  diagnosed reported failures, and edited documentation under direction.

Enforced in the runtime as well as the record: no `agent:` identity can hold the approver role.

**T104 itself remains human-owned** — this document is evidence, and §4 is blank.

**Deviation.** One disclosed process incident: during T103 an agent diagnostic booted the
application and let Flyway migrate the reviewer's fresh database. It was disclosed immediately and
remediated before the human rerun. Recorded in quickstart-validation §5.

**Human action required:** the T104 decision itself.

### XIII. Release readiness — **PASS on evidence; decision reserved**

**Evidence.** All approved requirements satisfied or formally deferred: **0 GAP**. Two
DEFERRED_APPROVED (FR-005, FR-015), both registered with re-entry cost and proven absent by test.
No blocker exists for the final T100 audit — T100 is held open only because it was sequenced to
close after this gate.

Remaining accepted risks are appropriate for a **local take-home prototype** and are explicitly
scoped that way by the T102 conditions: demo identity, no TLS, no rate limiting, no
supply-chain review, Docker daemon as an infrastructure trust boundary, unauthenticated console.
Condition 2 forbids shared or production deployment without real authentication, transport
security and console access control.

**Deviation.** Three disclosed items carried into this gate: the thin orchestrator unit layer, the
ten tasks missing `(REQ)` identifiers, and the unknown-parent collection-endpoint semantics.

**Human action required: the release decision.**

---

## 3. Summary

| # | Principle / gate | Status | Human action required |
|---|---|---|---|
| I | Specification-First | **PASS** | No |
| II | Controlled Agent Autonomy | **PASS** | No |
| III | Requirement Traceability | **PASS** | Decide on ten `(REQ)`-less tasks |
| IV | Test-First Quality | **PASS** (disclosed gap) | Accept or backfill the unit layer |
| V | Security by Design | **PASS** (T102 approved w/ conditions) | Confirm conditions stand |
| V-a | Unsafe-target prevention | **N-A** (unchanged) | No |
| VI | Stateful Orchestration | **PASS** | No |
| VII | Resilience and Bounded Autonomy | **PASS** | No (G7 already accepted) |
| VIII | Observability and Auditability | **PASS** | No |
| IX | Dynamic Replanning | **PASS** | No |
| X | Production Engineering Quality | **PASS** | No |
| XI | Simplicity | **PASS** | No |
| XII | Human Ownership | **PASS** | The T104 decision |
| XIII | Release readiness | **PASS on evidence** | **The release decision** |

**Gate II: valid, no re-approval required.** **No Constitution violation was found, and no runtime
change was made during this review.**

---

## 4. HUMAN REVIEW CHECKLIST

**Completed by the human reviewer on 2026-08-20.** Thirteen gates re-evaluated:
**12 PASS · 1 N-A (V-a) · 0 FAIL.** The agent assessment in §3 was a recommendation; the marks
below are the record.

```
                                                        agent assessed
☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   I.    Specification-First             [PASS]
        implemented behaviour maps to approved spec/tasks · deferrals explicit
        · no undocumented feature creep

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   II.   Controlled Agent Autonomy       [PASS]
        agent cannot self-approve (9) · governance protected (15) · scope
        enforced (14) · four tools (14) · no mode escalation (9)

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   III.  Requirement Traceability        [PASS]
        79 / 77 / 2 / 0 · matrix check 11 passed
        ⚠ DECISION NEEDED: ten completed tasks cite research decisions, not (REQ) ids
        ☑ ACCEPT — supporting/research tasks, not single-requirement implementation.
          Do NOT attach arbitrary requirement ids for cosmetic traceability.

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   IV.   Test-First Quality              [PASS, disclosed gap]
        five layers · T022/T102/T103 correctly attributed · invalidated evidence preserved
        ⚠ DECISION NEEDED: orchestrator `unit` marker selects one misfiled test
        ☑ ACCEPT — a test-ORGANIZATION limitation, not a validation gap. Preserve it in
          documentation; do NOT manufacture unit-test counts for appearance.

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   V.    Security by Design              [PASS w/ conditions]
        T102: 47 PASS / 4 ACCEPT-RISK / 0 FAIL · all six conditions re-verified
        ⚠ CONFIRM: does the T102 approval and its six conditions still stand at release?
        ☑ CONFIRMED — T102 remains APPROVED WITH CONDITIONS. All ten accepted risks and
          all six binding conditions remain in force at release. Approval covers the LOCAL
          TAKE-HOME PROTOTYPE ONLY and is NOT approval for shared or production deployment.

☐ PASS  ☐ FAIL  ☑ N-A            V-a.  Unsafe-target prevention        [N-A, unchanged]
        FR-018 prohibits server-side fetch · zero requests observed in T099

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   VI.   Stateful Orchestration          [PASS]
        gates recorded (5) · state persists, resume re-executes nothing (5) · 18 tables

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   VII.  Resilience / Bounded Autonomy   [PASS]
        bounds (16) · no unsandboxed fallback, real dead daemon (5) · human wait
        consumes no compute (5) · G7 thread-timeout risk already accepted at T102

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   VIII. Observability / Auditability    [PASS]
        audit append-only by DB privilege · lineage, change, rollback, replan (8)
        · five metrics, null ≠ 0, human wait excluded

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   IX.   Dynamic Replanning              [PASS]
        closure-only invalidation · unaffected work preserved · supersedes queryable
        · new component halts for approval (18)

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   X.    Production Engineering Quality  [PASS]
        flat error contracts CI-gated (28) · four DB roles, two databases
        · LLD §17 rationale for all six public interfaces · limitations disclosed

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   XI.   Simplicity / Evidence-Based     [PASS]
        Redis in zero manifests and zero OpenAPI artifacts · p95 6.82 ms vs 150 ms
        · cache tier reachable only via approval-gated brownfield ladder

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   XII.  Human Ownership                 [PASS]
        T006/T007/T022/T102/T103 human-attributed · zero agent-as-approver records
        · one disclosed process incident (agent diagnostic touched the DB during T103)

☑ PASS  ☐ FAIL  ☐ ACCEPT-RISK   XIII. Release readiness               [PASS on evidence]
        0 GAP · 2 registered deferrals · no blocker for T100
        ☑ PASS — release-ready for submission as a take-home prototype (see §5)
```

### Gate II delta

```
☑ Gate II REMAINS VALID, no re-approval required
☐ Gate II requires re-approval — reason: ______________________________

    runtime source modified : 0        contracts / OpenAPI modified : 0
    plan.md modified        : 0        all six T103 changes         : documentation-only
```

## 5. Human decision

**Completed by the human reviewer on 2026-08-20. No agent participated in this decision.**

| Field | |
|---|---|
| Date | **2026-08-20** |
| Gate II re-approval required? | ☑ **No** — Gate II remains valid |
| **Release decision** | ☑ **PASS — release-ready for the take-home prototype** ☐ Release-ready with conditions ☐ Not release-ready |

### 5.1 The four open items — reviewer's decisions

**1. Principle III — ten completed tasks cite research decisions instead of `(REQ)` ids: ACCEPT.**
These are architecture, research and supporting tasks rather than direct implementation of a single
requirement. **Arbitrary requirement ids must not be attached merely to improve cosmetic
traceability.** The requirement matrix itself remains complete at 79 total / 77 COVERED /
2 DEFERRED_APPROVED / 0 GAP.

**2. Principle IV — the orchestrator `unit` marker selects one test, and that test is misfiled:
ACCEPT.** This is a **test-organization limitation, not a validation gap**. Core orchestrator
behaviour is covered extensively at the workflow, failure, contract, integration and security
layers. **Preserve the limitation in documentation; do not manufacture unit-test counts for
appearance.**

**3. Principle V — T102 security approval: CONFIRMED.** The T102 decision remains **APPROVED WITH
CONDITIONS**. All ten accepted risks and all six binding conditions remain in force at release.
**This approval is for the local take-home prototype only and is not approval for deployment to a
shared or production environment.**

**4. Principle XIII — release readiness: PASS.** The system is release-ready for submission as a
take-home prototype.

### 5.2 Reviewer's confirmations at close

- Thirteen Constitution gates were re-evaluated: **12 PASS**, **0 FAIL**
- **Gate V-a remains N-A** because the shortener performs no server-side URL fetch
- **Gate II remains valid and requires no re-approval**
- The six T103 README corrections are **documentation-only**
- **No runtime architecture changed** during T103 / T104
- **No OpenAPI or public contract changed**
- Traceability remains **79 total · 77 COVERED · 2 DEFERRED_APPROVED · 0 GAP**
- **Failed and invalidated evidence remains preserved** in the record
- **T102 accepted risks and conditions remain visible**
- **No blocking Constitution violation exists**

> **Standing constraints carried out of this gate.** Decisions 1 and 2 are prohibitions as much as
> acceptances: no requirement id may be back-fitted to a supporting task for appearance, and no
> unit-test count may be manufactured. Decision 3 keeps the T102 conditions binding — in particular
> that this system must not be deployed to a shared or production environment without real
> authentication, transport security and console access controls. A change that weakens any of
> these invalidates this approval and requires a fresh human review.

Recording this decision completes T104.
