package com.schwab.shortener.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import java.util.regex.Pattern;
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

    /** Conservative on purpose: what a trace id looks like, and nothing that could break a log line. */
    private static final Pattern SAFE = Pattern.compile("[A-Za-z0-9_.:-]{8,64}");

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String incoming = request.getHeader(HEADER);
        String correlationId = (incoming != null && SAFE.matcher(incoming).matches())
                ? incoming
                : UUID.randomUUID().toString();

        MDC.put(MDC_KEY, correlationId);
        response.setHeader(HEADER, correlationId);
        try {
            chain.doFilter(request, response);
        } finally {
            // Pooled threads: never leave one request's identity visible to the next.
            MDC.remove(MDC_KEY);
        }
    }
}
