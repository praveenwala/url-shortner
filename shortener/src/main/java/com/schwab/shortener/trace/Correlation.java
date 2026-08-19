package com.schwab.shortener.trace;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Correlation fields for the shortener.
 *
 * <p>Implements {@code contracts/correlation.md} for this service only. The Python
 * orchestrator implements the same contract independently — there is deliberately no shared
 * runtime module across the language boundary (plan.md, Structure Decision).
 */
public record Correlation(String traceId, String spanId, String runId, String actor,
                          Instant occurredAt) {

    public static final String TRACE_ID = "trace_id";
    public static final String SPAN_ID = "span_id";
    public static final String RUN_ID = "run_id";
    public static final String ACTOR = "actor";
    public static final String OCCURRED_AT = "occurred_at";

    public static final Set<String> FIELD_NAMES =
            Set.of(TRACE_ID, SPAN_ID, RUN_ID, ACTOR, OCCURRED_AT);

    public static String newId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    public static Correlation start(String actor) {
        return new Correlation(newId(), newId(), null, actor, Instant.now());
    }

    /** Keeps the trace, starts a new span — same semantics as the orchestrator helper. */
    public Correlation child(String childActor) {
        return new Correlation(traceId, newId(), runId,
                childActor == null ? actor : childActor, Instant.now());
    }

    public Map<String, Object> asMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(TRACE_ID, traceId);
        m.put(SPAN_ID, spanId);
        m.put(RUN_ID, runId);
        m.put(ACTOR, actor);
        m.put(OCCURRED_AT, occurredAt.toString());
        return m;
    }
}
