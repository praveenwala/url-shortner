# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo currently contains **no application code** — only GitHub Spec Kit scaffolding (`.specify/`) and its generated Claude skills (`.claude/skills/speckit-*`). There are no commits on `master` yet, and no build/test tooling, package manifest, or `.gitignore`. The intended subject (per the repo name) is an agentic URL shortener; the stack has not been chosen. Expect to establish tooling as part of the first feature's plan, and record the chosen build/test commands here once they exist.

## Spec-Driven Development workflow

Work flows through Spec Kit skills in a fixed order. Each stage writes artifacts under `specs/<NNN>-<slug>/` and the next stage refuses to run without its predecessor's output:

```
/speckit-constitution → /speckit-specify → /speckit-clarify → /speckit-plan → /speckit-tasks → /speckit-implement
```

- `/speckit-specify` creates `specs/<NNN>-<slug>/spec.md` from `.specify/templates/spec-template.md`.
- `/speckit-plan` adds `research.md`, `data-model.md`, `quickstart.md`, and `contracts/`.
- `/speckit-tasks` produces `tasks.md`; `/speckit-implement` executes it.
- `/speckit-analyze` cross-checks spec/plan/tasks for drift; `/speckit-converge` reconciles the codebase back into `tasks.md`; `/speckit-checklist` generates feature checklists.

The bundled `speckit` workflow (`.specify/workflows/speckit/workflow.yml`) chains specify → plan → tasks → implement with human approval gates after spec and plan; rejecting a gate aborts the run.

## How the active feature is resolved

Feature context is **not** derived from the git branch here (no git extension is installed, so `create-new-feature.sh` creates the directory but no branch). Resolution order in `.specify/scripts/bash/common.sh`:

1. `SPECIFY_FEATURE_DIRECTORY` env var
2. `.specify/feature.json` (`feature_directory` key, written by `/speckit-specify`)
3. Otherwise the scripts hard-error

`SPECIFY_FEATURE` supplies the branch-like name only. If a Spec Kit script reports "Feature directory not found", set one of the above rather than switching branches.

## Scripts

Skills call these directly; run them manually when debugging a stuck workflow. All accept `--json` for machine-readable output.

```bash
.specify/scripts/bash/create-new-feature.sh --json "<description>"   # also: --short-name, --number N, --timestamp, --dry-run
.specify/scripts/bash/check-prerequisites.sh --json                  # plan.md required
.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
.specify/scripts/bash/check-prerequisites.sh --paths-only            # just REPO_ROOT/BRANCH/FEATURE_DIR
.specify/scripts/bash/setup-plan.sh --json
.specify/scripts/bash/setup-tasks.sh --json
```

Feature numbering is `sequential` (`.specify/init-options.json`): the next number is `max(existing specs/ dirs) + 1`, zero-padded to three digits. Use `--number` to override; re-running against an existing directory fails unless `--allow-existing-branch`.

## Constitution

`.specify/memory/constitution.md` (**v1.0.0**, ratified 2026-08-18) is the governing document — read it before planning or implementing. Twelve principles, all binding:

I. Specification-First · II. Controlled Agent Autonomy · III. Requirement Traceability · IV. Test-First Quality (NON-NEGOTIABLE) · V. Security by Design · VI. Stateful Orchestration · VII. Resilience and Bounded Autonomy · VIII. Observability and Auditability · IX. Dynamic Replanning · X. Production Engineering Quality · XI. Simplicity over Unnecessary Complexity · XII. Human Ownership

Consequences that change day-to-day behavior here:

- **Tests are not optional.** `tasks-template.md` was amended accordingly: unit, integration, workflow, and failure-path tests are required for critical and orchestration behavior, written before implementation and observed failing first.
- **Every task carries a `[REQ]` requirement ID.** Work with no upstream requirement is out of scope — promote it into the spec first.
- **Stop and ask** before architecture, security, destructive, or release actions (Principle II). Record the approval in the feature artifacts, not just in chat.
- **Every automated operation declares** timeout, bounded retry, fallback, rollback, and safe-stop (Principle VII). No unbounded retries or open-ended agent loops.
- **New technology needs a demonstrated requirement** (Principle XI) plus the rejected simpler alternative in the plan's Complexity Tracking table.

The Constitution Check in `.specify/templates/plan-template.md` is now a concrete 12-gate checklist. Amendments require human ratification and must update `.specify/templates/*` and this file in the same change.

## Other agent configs

A `~/.codex` config exists on this machine. To import its user-level items (MCP servers, slash commands, subagents, skills, instructions) into Claude Code, reply `/import` to scan and list what's importable, then `/import --yes=<digest>` using the digest the scan prints. If `/import` is unavailable on this surface, run `claude import` from a terminal.
