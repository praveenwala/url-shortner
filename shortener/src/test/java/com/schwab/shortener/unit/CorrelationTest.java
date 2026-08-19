package com.schwab.shortener.unit;

import static org.assertj.core.api.Assertions.assertThat;

import com.schwab.shortener.trace.Correlation;
import java.util.Set;
import org.junit.jupiter.api.Test;

/** T008 — the shortener's own correlation helper honours contracts/correlation.md. */
class CorrelationTest {

    @Test
    void fieldNamesMatchTheContract() {
        assertThat(Correlation.FIELD_NAMES)
                .containsExactlyInAnyOrderElementsOf(
                        Set.of("trace_id", "span_id", "run_id", "actor", "occurred_at"));
    }

    @Test
    void childKeepsTheTraceAndStartsANewSpan() {
        Correlation parent = Correlation.start("system");
        Correlation child = parent.child("human:reviewer");

        assertThat(child.traceId()).isEqualTo(parent.traceId());
        assertThat(child.spanId()).isNotEqualTo(parent.spanId());
        assertThat(child.actor()).isEqualTo("human:reviewer");
    }

    @Test
    void serialisesUsingContractFieldNames() {
        assertThat(Correlation.start("system").asMap()).containsKeys(
                "trace_id", "span_id", "run_id", "actor", "occurred_at");
    }
}
