package com.schwab.shortener.obs;

import com.schwab.shortener.web.errors.ApiException;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.util.concurrent.TimeUnit;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Component;

/**
 * Aggregate behaviour for link creation.
 *
 * <p>Micrometer is already on the classpath through {@code spring-boot-starter-actuator}, so this
 * adds no dependency. Nothing is scraped — the meters live in the auto-configured registry and are
 * available for an exporter later.
 *
 * <p><strong>Cardinality is the whole design constraint.</strong> Logs answer "what happened to
 * this one request"; metrics answer "how is the system behaving". Tagging a metric with a
 * correlation id, short code, destination host or client id would create an unbounded series per
 * value and eventually take down the metrics backend rather than the service. So the only tags
 * here are {@code outcome} (two values) and {@code reason} (five), and failure classification maps
 * arbitrary exceptions into that fixed set rather than using the class name.
 */
@Component
public class CreationMetrics {

    public static final String TIMER = "shortener.link.creation.duration";
    public static final String COUNTER = "shortener.link.creation.total";

    /** The closed failure vocabulary. Any exception maps into one of these. */
    public enum Reason {
        VALIDATION, AUTHORIZATION, CONFLICT, DATABASE, INTERNAL;

        String tag() {
            return name().toLowerCase();
        }
    }

    private final MeterRegistry registry;

    public CreationMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public void recordSuccess(long durationNanos) {
        registry.timer(TIMER, "outcome", "success").record(durationNanos, TimeUnit.NANOSECONDS);
        registry.counter(COUNTER, "outcome", "success").increment();
    }

    public void recordFailure(long durationNanos, Reason reason) {
        registry.timer(TIMER, "outcome", "failure", "reason", reason.tag())
                .record(durationNanos, TimeUnit.NANOSECONDS);
        registry.counter(COUNTER, "outcome", "failure", "reason", reason.tag()).increment();
    }

    /**
     * Map an exception into the bounded vocabulary.
     *
     * <p>Uses the stable {@link com.schwab.shortener.web.errors.ErrorCode} rather than the
     * exception class, so adding an exception type cannot silently add a metric series.
     */
    public static Reason classify(Throwable failure) {
        if (failure instanceof DataAccessException) {
            return Reason.DATABASE;
        }
        if (failure instanceof ApiException api) {
            return switch (api.code()) {
                case INVALID_SCHEME, MALFORMED_URL, URL_TOO_LONG, ALIAS_MALFORMED -> Reason.VALIDATION;
                case FORBIDDEN, RATE_LIMITED -> Reason.AUTHORIZATION;
                case ALIAS_CONFLICT, ALIAS_RESERVED -> Reason.CONFLICT;
                case REDIRECT_NOT_RECORDED -> Reason.DATABASE;
                default -> Reason.INTERNAL;
            };
        }
        return Reason.INTERNAL;
    }

    /** Timer for the counter of a given outcome — used by tests to assert increments. */
    public Timer timer(String outcome) {
        return registry.find(TIMER).tag("outcome", outcome).timer();
    }

    public Counter counter(String outcome) {
        return registry.find(COUNTER).tag("outcome", outcome).counter();
    }
}
