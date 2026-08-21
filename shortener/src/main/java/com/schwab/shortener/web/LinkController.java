package com.schwab.shortener.web;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.schwab.shortener.obs.CreationMetrics;
import com.schwab.shortener.obs.DestinationDigest;
import com.schwab.shortener.obs.Events;
import com.schwab.shortener.service.LinkService;
import com.schwab.shortener.web.errors.ApiError;
import com.schwab.shortener.web.errors.UnauthenticatedException;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.validation.constraints.NotBlank;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
/** Programmatic surface (FR-016). Versioned; the redirect route is not (R9). */
@RestController
@RequestMapping("/v1/links")
public class LinkController {

    private static final Logger LOG = LoggerFactory.getLogger(LinkController.class);

    private final LinkService links;
    private final CreationMetrics metrics;

    public LinkController(LinkService links, CreationMetrics metrics) {
        this.metrics = metrics;
        this.links = links;
    }

    public record CreateRequest(@NotBlank String destination,
                                @JsonProperty("expires_at") Instant expiresAt) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record CreateResponse(String code, String destination,
                                 @JsonProperty("created_at") Instant createdAt,
                                 @JsonProperty("expires_at") Instant expiresAt) {}

    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record SummaryResponse(String code,
                                  @JsonProperty("total_redirects") long totalRedirects,
                                  @JsonProperty("first_redirect_at") Instant firstRedirectAt,
                                  @JsonProperty("last_redirect_at") Instant lastRedirectAt) {}

    // The generated document must state what the service actually returns. Without these
    // annotations springdoc advertises a bare 200 and no error envelope, so a client reading
    // the published contract would not know the stable `error` identifiers exist (FR-016,
    // SC-004). These are documentation only — no runtime behaviour changes.
    @ApiResponses({
        @ApiResponse(responseCode = "201", description = "link created"),
        @ApiResponse(responseCode = "400",
                description = "invalid_scheme | malformed_url | url_too_long",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "401", description = "forbidden — X-Client-Id missing",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
    })
    @PostMapping
    public ResponseEntity<CreateResponse> create(
            @RequestBody CreateRequest request,
            @Parameter(name = "X-Client-Id", required = true,
                       description = "creating client credential")
            @RequestHeader(value = "X-Client-Id", required = false) String clientId) {
        String client = requireClient(clientId);

        // Timing brackets the *proxied* call. LinkService is a @Service whose create() is
        // @Transactional and is injected here as a field, so this invocation goes through the
        // transaction proxy: a normal return means the transaction has already committed, and a
        // throw means it rolled back. That is why the success event lives here and not inside the
        // service — an event emitted in the method body would precede the commit.
        String creationStartedAt = Instant.now().toString();
        long creationStart = System.nanoTime();
        try {
            var created = links.create(request.destination(), request.expiresAt(), client);
            long elapsed = System.nanoTime() - creationStart;

            metrics.recordSuccess(elapsed);
            LOG.info("{} request_received_at={} creation_started_at={} created_at={} "
                            + "creation_duration_ms={} db_lookup_duration_ms={} short_code={} "
                            + "destination_host={} destination_hash={} outcome=success",
                    Events.SHORT_LINK_CREATED, MDC.get(CorrelationFilter.MDC_RECEIVED_AT),
                    creationStartedAt, created.createdAt(),
                    millis(elapsed), millis(created.dbLookupNanos()), created.code(),
                    // Host and hash only — never the raw destination, which can carry a token.
                    DestinationDigest.host(request.destination()),
                    DestinationDigest.hash(request.destination()));

            return ResponseEntity.status(HttpStatus.CREATED).body(new CreateResponse(
                    created.code(), created.destination(), created.createdAt(),
                    created.expiresAt()));
        } catch (RuntimeException failure) {
            long elapsed = System.nanoTime() - creationStart;
            metrics.recordFailure(elapsed, CreationMetrics.classify(failure));
            // Type only. An exception message can carry a JDBC URL, SQL parameters, or the
            // destination itself.
            LOG.warn("{} request_received_at={} creation_started_at={} duration_ms={} "
                            + "error_type={} outcome=failed",
                    Events.SHORT_LINK_CREATION_FAILED, MDC.get(CorrelationFilter.MDC_RECEIVED_AT),
                    creationStartedAt, millis(elapsed), failure.getClass().getSimpleName());
            // Rethrown unchanged so ApiExceptionHandler still owns the response shape.
            throw failure;
        }
    }

    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "link revoked"),
        @ApiResponse(responseCode = "401", description = "forbidden — X-Client-Id missing",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "403", description = "forbidden — not the creating client",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "404", description = "not_found",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
    })
    @PostMapping("/{code}/revoke")
    public ResponseEntity<Void> revoke(
            @PathVariable String code,
            @Parameter(name = "X-Client-Id", required = true)
            @RequestHeader(value = "X-Client-Id", required = false) String clientId) {
        links.revoke(code, requireClient(clientId));
        return ResponseEntity.ok().build();
    }

    @ApiResponses({
        @ApiResponse(responseCode = "200", description = "owner-scoped analytics summary"),
        @ApiResponse(responseCode = "401", description = "forbidden — X-Client-Id missing",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "403", description = "forbidden — analytics are owner-scoped",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "404", description = "not_found",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
    })
    @GetMapping("/{code}/analytics")
    public SummaryResponse analytics(
            @PathVariable String code,
            @Parameter(name = "X-Client-Id", required = true)
            @RequestHeader(value = "X-Client-Id", required = false) String clientId) {
        var summary = links.summary(code, requireClient(clientId));
        return new SummaryResponse(summary.code(), summary.totalRedirects(),
                summary.firstRedirectAt(), summary.lastRedirectAt());
    }

    private static String requireClient(String clientId) {
        if (clientId == null || clientId.isBlank()) {
            throw new UnauthenticatedException("X-Client-Id is required");
        }
        return clientId;
    }

    /** Nanoseconds to milliseconds, three decimals. Durations only ever come from nanoTime(). */
    private static String millis(long nanos) {
        return String.format("%.3f", nanos / 1_000_000.0);
    }
}
