package com.schwab.shortener.web;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.schwab.shortener.web.errors.ApiError;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.schwab.shortener.service.LinkService;
import com.schwab.shortener.web.errors.UnauthenticatedException;
import jakarta.validation.constraints.NotBlank;
import java.time.Instant;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Programmatic surface (FR-016). Versioned; the redirect route is not (R9). */
@RestController
@RequestMapping("/v1/links")
public class LinkController {

    private final LinkService links;

    public LinkController(LinkService links) {
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
        var created = links.create(request.destination(), request.expiresAt(), client);
        return ResponseEntity.status(HttpStatus.CREATED).body(new CreateResponse(
                created.code(), created.destination(), created.createdAt(), created.expiresAt()));
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
}
