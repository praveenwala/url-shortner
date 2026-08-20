package com.schwab.shortener.validation;

import java.util.Locale;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Paths that can never be issued or resolved as a short code (FR-006).
 *
 * <p>Without this, a code could impersonate an operational route.
 */
@Component
public class ReservedPaths {

    private static final Set<String> RESERVED = Set.of(
            "health", "actuator", "metrics", "admin", "api", "v1", "v2",
            "login", "logout", "static", "assets", "favicon.ico", "robots.txt");

    public boolean isReserved(String candidate) {
        return candidate != null && RESERVED.contains(candidate.toLowerCase(Locale.ROOT));
    }
}
