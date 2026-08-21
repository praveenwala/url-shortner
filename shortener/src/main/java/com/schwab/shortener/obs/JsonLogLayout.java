package com.schwab.shortener.obs;

import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.LayoutBase;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Minimal JSON layout for operational logs.
 *
 * <p>Hand-written rather than pulling in a logging encoder dependency: Jackson is already on the
 * classpath via {@code spring-boot-starter-web}, and the requirement was structured output without
 * a heavy observability stack. Roughly forty lines is a fair trade for one fewer supply-chain edge.
 *
 * <p>MDC entries are promoted to top-level fields so a log query can filter on
 * {@code correlation_id} directly. The message is emitted verbatim — callers are responsible for
 * not putting a secret in it, and {@link Events} exists so they rarely have to compose one.
 *
 * <p>Operational logs are not the audit trail. Nothing here writes to a database.
 */
public class JsonLogLayout extends LayoutBase<ILoggingEvent> {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public String doLayout(ILoggingEvent event) {
        Map<String, Object> record = new LinkedHashMap<>();
        record.put("timestamp", Instant.ofEpochMilli(event.getTimeStamp()).toString());
        record.put("level", event.getLevel().toString());
        record.put("service", "shortener");
        record.put("logger", event.getLoggerName());
        record.put("message", event.getFormattedMessage());

        // Correlation and per-request context, promoted so queries can filter on them.
        Map<String, String> mdc = event.getMDCPropertyMap();
        if (mdc != null) {
            mdc.forEach((k, v) -> {
                if (v != null && !v.isBlank()) {
                    record.put(k, v);
                }
            });
        }

        // Type only. A stack trace can carry a connection string; the type plus the message is
        // what an operator needs to classify the failure.
        if (event.getThrowableProxy() != null) {
            record.put("error_type", event.getThrowableProxy().getClassName());
        }

        try {
            return MAPPER.writeValueAsString(record) + System.lineSeparator();
        } catch (JsonProcessingException e) {
            // Logging must never break a request. Fall back to a parseable minimum.
            return "{\"level\":\"ERROR\",\"service\":\"shortener\","
                    + "\"message\":\"log serialisation failed\"}" + System.lineSeparator();
        }
    }
}
