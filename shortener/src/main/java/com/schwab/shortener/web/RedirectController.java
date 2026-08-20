package com.schwab.shortener.web;

import com.schwab.shortener.service.LinkService;
import com.schwab.shortener.web.errors.ApiError;
import io.swagger.v3.oas.annotations.headers.Header;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * The redirect (FR-007, FR-010). Unversioned and permanent as a route: short links are handed
 * to third parties and must never change shape (R9).
 */
@RestController
public class RedirectController {

    private final LinkService links;

    public RedirectController(LinkService links) {
        this.links = links;
    }

    // Documented as 302 with the non-cacheable headers because that *is* the contract: a
    // cached redirect never reaches the service again, so counts would drift and revoked or
    // expired links would keep resolving. A published document showing a bare 200 would hide
    // the one property clients most need to respect.
    @ApiResponses({
        @ApiResponse(responseCode = "302", description = "temporary, non-cacheable redirect",
                headers = {
                    @Header(name = "Location", description = "the exact stored destination",
                            schema = @Schema(type = "string")),
                    @Header(name = "Cache-Control",
                            description = "no-store, no-cache, must-revalidate",
                            schema = @Schema(type = "string")),
                    @Header(name = "Pragma", description = "no-cache",
                            schema = @Schema(type = "string")),
                    @Header(name = "Expires", description = "0",
                            schema = @Schema(type = "string")),
                }),
        @ApiResponse(responseCode = "400", description = "malformed_url",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "404", description = "not_found",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "410", description = "expired | revoked",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
        @ApiResponse(responseCode = "503", description = "redirect_not_recorded",
                content = @Content(schema = @Schema(implementation = ApiError.class))),
    })
    @GetMapping("/{code}")
    public ResponseEntity<Void> resolve(@PathVariable String code, HttpServletRequest request) {
        // The count is committed by the time this returns. Only then is a redirect issued.
        String destination = links.resolveAndCount(code);

        HttpHeaders headers = new HttpHeaders();
        // Temporary and explicitly non-cacheable. A cached redirect would never reach the
        // service again: counts would drift and revoked or expired links would keep working.
        headers.setLocation(URI.create(destination));
        headers.set(HttpHeaders.CACHE_CONTROL, "no-store, no-cache, must-revalidate");
        headers.set(HttpHeaders.PRAGMA, "no-cache");
        headers.set(HttpHeaders.EXPIRES, "0");
        return new ResponseEntity<>(headers, HttpStatus.FOUND);
    }
}
