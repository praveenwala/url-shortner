# Contract: Correlation and Trace Field Names

**Scope**: Both services | **Feature**: 001-agentic-url-shortener

The Java shortener and the Python orchestrator **share no implementation code**. Each owns its
own correlation helper. What they share is this contract — the field names and semantics below
— so that records from either service can be correlated without either importing the other.

This is the only mechanism by which the two services agree on anything at runtime.

## Fields

| Field | Meaning | Emitted by |
|-------|---------|-----------|
| `trace_id` | Identifies one end-to-end interaction. Generated at the entry boundary if absent | Both |
| `span_id` | Identifies one unit of work within a trace | Both |
| `run_id` | Identifies one orchestration run; correlates every audit record for that run (FR-036) | Orchestrator only |
| `actor` | Who performed the action — a human identity, an agent identity, or the system | Both |
| `occurred_at` | UTC timestamp, ISO 8601 | Both |

## Rules

1. **No shared runtime module.** Each service implements these fields in its own language and
   its own package. A change here is a contract change, propagated to two implementations
   deliberately — never by adding a common library.
2. **Same names, same semantics.** Field names are exact and case-sensitive. A service that
   renames one has broken the contract.
3. **No secrets or personal data** in any correlation field (FR-038, NFR-006).
4. **Generated, not accepted blindly.** A `trace_id` arriving from an external caller is
   recorded but never trusted for authorization decisions.
