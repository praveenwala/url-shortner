package com.schwab.shortener.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import com.schwab.shortener.obs.Events;
import java.io.IOException;
import java.time.Instant;
import java.util.UUID;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Per-request correlation identity (production-hardening).
 *
 * <p>An inbound {@code X-Correlation-Id} is honoured so a caller can stitch a request to its own
 * traces — but only after validation. The value is echoed in a response header and written into
 * every log line for the request, so an unvalidated one would be a log-injection and
 * response-splitting vector. Anything that is not a short, safe token is replaced rather than
 * rejected: a malformed correlation id is not worth failing a redirect over.
 *
 * <p>MDC is cleared in a {@code finally} block. Servlet threads are pooled, and a leaked MDC entry
 * would attribute one caller's identifier to the next caller's logs.
 */
@Component
public class CorrelationFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Correlation-Id";
    public static final String MDC_KEY = "correlation_id";
    /** UTC wall-clock arrival, carried in MDC so downstream events can report it. */
    public static final String MDC_RECEIVED_AT = "request_received_at";

    private static final Logger LOG = LoggerFactory.getLogger(CorrelationFilter.class);

    /** Conservative on purpose: what a trace id looks like, and nothing that could break a log line. */
    private static final Pattern SAFE = Pattern.compile("[A-Za-z0-9_.:-]{8,64}");

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String incoming = request.getHeader(HEADER);
        String correlationId = (incoming != null && SAFE.matcher(incoming).matches())
                ? incoming
                : UUID.randomUUID().toString();

        // Wall clock for the human-readable field; monotonic for the duration. Instant is subject
        // to clock adjustment and must never be subtracted to measure elapsed time.
        String receivedAt = Instant.now().toString();
        long startNanos = System.nanoTime();

        MDC.put(MDC_KEY, correlationId);
        MDC.put(MDC_RECEIVED_AT, receivedAt);
        response.setHeader(HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            double durationMs = (System.nanoTime() - startNanos) / 1_000_000.0;
            // Emitted in `finally` so it is recorded whether the request succeeded, failed, or
            // threw. Path is the request URI, which for this API contains no user content beyond
            // a short code — no query string is logged.
            LOG.info("{} method={} path={} status={} request_duration_ms={} outcome={}",
                    Events.HTTP_REQUEST_COMPLETED, request.getMethod(), request.getRequestURI(),
                    response.getStatus(), String.format("%.3f", durationMs),
                    response.getStatus() < 400 ? "success" : "failed");

            // Pooled threads: never leave one request's identity visible to the next.
            MDC.remove(MDC_KEY);
            MDC.remove(MDC_RECEIVED_AT);
        }
    }
}
