# Contract: Bounded-Task Agent Runtime

**Component**: `orchestrator/src/agent` | **Feature**: 001-agentic-url-shortener

This is an internal contract, not a network surface. It defines what an agent may do when
the orchestrator hands it a task — the boundary that makes FR-041's "bounded task" an
enforced property rather than a prompt instruction.

## Precondition: is the task bounded?

A task may be dispatched to an agent only when **all four** are already approved:

1. Interface — the shape it implements
2. Acceptance criteria — how it will be judged
3. Dependencies — what it may rely on
4. Security constraints — what it may touch

Missing any one, the task is not bounded and must not be agent-authored (FR-041). The
runtime refuses dispatch rather than degrading to a guess.

**Surface scoping** (polyglot, R6): every task declares exactly one surface — `shortener`
(Java), `orchestrator` (Python), or `console` (TypeScript) — and its path allow-list is
derived from that surface. A task spanning two surfaces is an architectural change and
requires an approval checkpoint; it is never dispatched to an agent as a bounded task.

## Permitted task categories

Component implementation · work against approved API contracts · persistence mappings ·
tests · documentation · refactoring within an established boundary.

## Prohibited without human approval

Introducing a service or datastore · altering architecture · altering security policy ·
modifying governance artifacts · release or deployment (FR-041, FR-040, FR-029).

## Capability model — narrow, and mechanically enforced

Agents receive **no shell, no arbitrary command execution, and no general filesystem
authority**. The entire tool surface is:

| Tool | Authority | Bounded by |
|------|-----------|------------|
| `read_file` | Read a file | The task's path allow-list, derived from its approved interface and surface |
| `write_file` | Write a file | The same allow-list, and only paths the task declares as outputs |
| `run_tests` | Execute the project's test target for the task's surface | A fixed command per surface — not an arbitrary one, and not parameterised by the agent |
| `report` | Return findings or completion to the orchestrator | — |

There is no `bash`, no `exec`, no package installation, no network tool, no git tool, and no
path outside the per-task allow-list. This is why the prohibitions above hold: they are
**unreachable**, not discouraged.

### Network boundary

Two different things, and the distinction is load-bearing:

| Actor | Network authority |
|-------|-------------------|
| The **orchestrator process** | Exactly one configured egress: the Claude API endpoint required for agent execution. Process egress is restricted to that host |
| The **agent** | **None.** No tool takes a URL, host, or port. No HTTP tool, no fetch tool, no MCP connector, no package installation |

**Server-side model tools are not declared.** Web search, web fetch, and code execution are
deliberately absent from every request. Without this, an agent could cause arbitrary outbound
requests *through the model provider* — turning the one permitted egress into a general-purpose
proxy and making the Claude channel a bypass of the whole boundary. The Claude call is a
channel for reasoning, never a channel for reaching the network.

Consequently the agent boundary cannot be used to circumvent FR-018. SC-017's "zero outbound
requests to caller-supplied destinations" is verified across the whole system, orchestrator
included; the only egress that should ever appear is the configured Claude endpoint.

## Runtime rules

1. **Tool surface is the boundary.** The agent gets exactly the four tools above and nothing
   more. An agent cannot introduce a datastore because it has no tool that installs, connects
   to, or configures one; it cannot release because it has no tool that builds or deploys.
2. **Approval hooks intercept before apply.** A tool call that would cross a checkpoint is
   halted at the per-turn hook, the run enters `WAITING_FOR_HUMAN`, and the call proceeds
   only after a recorded approval (FR-043, FR-049).
3. **Execution mode is fixed at planning time.** The runtime refuses a task whose mode was
   changed from `human_executed` after planning; a mode change requires replanning and
   approval (FR-042).
4. **Every change is revertible.** Prior artifact state is captured in a `ChangeRecord`
   before the change is applied, so rollback restores exactly (FR-044, FR-032).
5. **Bounded by construction.** Each dispatch declares a timeout, a maximum attempt count,
   and a backoff; each run declares a token ceiling (task budget) and a wall-clock ceiling.
   Exhaustion takes the declared fallback or safe-stops — never an unbounded loop (FR-030,
   FR-031, NFR-009).
6. **Every dispatch is audited.** Task, requirement reference, model, effort, attempt number,
   outcome, and tokens consumed — with no secrets in the record (FR-036, FR-038).
7. **Stubbable.** The runtime is injectable so workflow and failure-path tests can force
   retry exhaustion, rollback, and safe-stop deterministically (R10, Principle IV).
