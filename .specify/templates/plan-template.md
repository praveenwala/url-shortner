# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]

**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]

**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]

**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]

**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]

**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]

**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]

**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]

**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Mark each gate PASS / FAIL / N-A with a one-line justification. Any FAIL must either be
resolved or recorded in Complexity Tracking below with human approval.

- [ ] **I. Specification-First**: Spec has requirements, acceptance criteria, assumptions;
      no unresolved `[NEEDS CLARIFICATION]` markers remain.
- [ ] **II. Controlled Agent Autonomy**: Architecture, security, destructive, and release
      decisions in this plan are flagged for explicit human approval.
- [ ] **III. Traceability**: Every planned component traces to a requirement ID.
- [ ] **IV. Test-First**: Test strategy names unit, integration, workflow, and
      failure-path coverage for critical and orchestration behavior.
- [ ] **V. Security by Design (all features)**: Input validation, secret handling, least
      privilege, and — for any feature accepting a URL — scheme allow-listing,
      canonicalization, and open-redirect prevention are addressed in the design.
- [ ] **V-a. Unsafe-target prevention (conditional)**: Applies ONLY if this feature
      dereferences a URL server-side (outbound fetch, liveness/reachability check,
      metadata or preview extraction, fetch-based validation). If so, the design rejects
      internal/loopback/link-local/private/cloud-metadata targets (SSRF) and bounds the
      redirect chain it follows. Mark N-A for store-and-redirect-only features.
- [ ] **VI. Stateful Orchestration**: Workflow modeled as an explicit dependency graph
      with persisted state, sync points, and entry/exit gates.
- [ ] **VII. Resilience**: Timeout, bounded retry, fallback, rollback, and safe-stop
      defined per automated operation.
- [ ] **VIII. Observability**: Structured, correlated records for actions/decisions/
      approvals/failures; success rate, retries, rollbacks, MTTR, latency tracked.
- [ ] **IX. Dynamic Replanning**: Downstream impact of upstream change is derivable from
      the dependency graph; stale artifacts are markable.
- [ ] **X. Production Quality**: Modular, testable boundaries; no hidden global state.
- [ ] **XI. Simplicity**: Every added technology (Redis, broker, extra service) maps to a
      demonstrated requirement; simpler alternative recorded as rejected.
- [ ] **XII. Human Ownership**: No gate in this plan is self-approved by an agent.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
