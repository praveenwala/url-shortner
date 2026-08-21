package com.schwab.shortener.service;

import com.schwab.shortener.obs.Events;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.schwab.shortener.domain.CodeGenerator;
import com.schwab.shortener.domain.RedirectEvent;
import com.schwab.shortener.domain.ShortLink;
import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.validation.DestinationValidator;
import com.schwab.shortener.validation.ReservedPaths;
import com.schwab.shortener.web.errors.ApiException;
import com.schwab.shortener.web.errors.ErrorCode;
import java.time.Instant;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Create, resolve, revoke, and the analytics summary (FR-001–FR-014). */
@Service
public class LinkService {

    private static final Logger LOG = LoggerFactory.getLogger(LinkService.class);


    private final ShortLinkRepository links;
    private final RedirectEventRepository events;
    private final DestinationValidator validator;
    private final ReservedPaths reserved;
    private final CodeGenerator generator;

    public LinkService(ShortLinkRepository links, RedirectEventRepository events,
                       DestinationValidator validator, ReservedPaths reserved) {
        this.links = links;
        this.events = events;
        this.validator = validator;
        this.reserved = reserved;
        this.generator = new CodeGenerator(
                candidate -> reserved.isReserved(candidate) || links.existsById(candidate));
    }

    public record CreatedLink(String code, String destination, Instant createdAt,
                              Instant expiresAt) {}

    public record Summary(String code, long totalRedirects, Instant firstRedirectAt,
                          Instant lastRedirectAt) {}

    @Transactional
    public CreatedLink create(String destination, Instant expiresAt, String clientId) {
        String validated = validator.validate(destination);
        if (expiresAt != null && !expiresAt.isAfter(Instant.now())) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "expiry must be in the future");
        }
        String code = generator.generate();
        ShortLink link = new ShortLink(code, validated, validator.canonicalise(validated),
                clientId, Instant.now(), expiresAt);
        links.save(link);
        // Code and client only. The destination is deliberately absent: a caller-supplied URL can
        // carry a credential or token in its query string, and this line goes to stdout.
        LOG.info("{} outcome=created code={} client={}", Events.LINK_CREATED, code, clientId);
        return new CreatedLink(code, validated, link.getCreatedAt(), link.getExpiresAt());
    }

    /**
     * Resolve and count in one transaction, committed before the caller responds.
     *
     * <p>This is the approved consistency-over-availability decision (R14, approval item 7):
     * exact accounting is part of successful redirect processing. If the count cannot be
     * durably recorded the transaction rolls back and no redirect is served — a caller sees a
     * failure rather than an uncounted redirect, and the counter and the event never diverge.
     */
    @Transactional
    public String resolveAndCount(String code) {
        if (reserved.isReserved(code)) {
            throw new ApiException(ErrorCode.NOT_FOUND, "no such link");
        }
        if (!CodeGenerator.isWellFormed(code)) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "short code is malformed");
        }

        ShortLink link = links.findById(code)
                .orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "no such link"));
        if (link.isRevoked()) {
            throw new ApiException(ErrorCode.REVOKED, "link has been revoked");
        }
        if (link.isExpiredAt(Instant.now())) {
            throw new ApiException(ErrorCode.EXPIRED, "link has expired");
        }

        Instant now = Instant.now();
        links.recordRedirect(code, now);
        events.save(new RedirectEvent(code, now));
        return link.getDestination();
    }

    @Transactional
    public void revoke(String code, String clientId) {
        ShortLink link = links.findById(code)
                .orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "no such link"));
        if (!link.isOwnedBy(clientId)) {
            // Deliberately not a 404: the creator is told "forbidden", and a non-creator
            // learns nothing about whether the code exists beyond what they supplied.
            throw new ApiException(ErrorCode.FORBIDDEN, "only the creating client may revoke");
        }
        links.revoke(code, Instant.now());
        LOG.info("{} outcome=revoked code={} client={}", Events.LINK_REVOKED, code, clientId);
    }

    @Transactional(readOnly = true)
    public Summary summary(String code, String clientId) {
        ShortLink link = links.findById(code)
                .orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "no such link"));
        if (!link.isOwnedBy(clientId)) {
            throw new ApiException(ErrorCode.FORBIDDEN, "analytics are owner-scoped");
        }
        return new Summary(code, link.getRedirectCount(), link.getFirstRedirectAt(),
                link.getLastRedirectAt());
    }
}
