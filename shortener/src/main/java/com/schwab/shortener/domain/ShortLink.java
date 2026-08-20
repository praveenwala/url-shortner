package com.schwab.shortener.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * A mapping from a short code to a destination (FR-004, FR-007, FR-008, FR-012).
 *
 * <p>The counters live here rather than being derived from {@link RedirectEvent}: retention
 * removes events but must never change the reported total (FR-013), so the aggregate is
 * denormalised onto the link on purpose.
 */
@Entity
@Table(name = "short_link")
public class ShortLink {

    @Id
    @Column(length = 32)
    private String code;

    @Column(nullable = false, columnDefinition = "text")
    private String destination;

    @Column(name = "destination_canonical", nullable = false, columnDefinition = "text")
    private String destinationCanonical;

    @Column(name = "client_id", nullable = false, columnDefinition = "text")
    private String clientId;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "expires_at")
    private Instant expiresAt;

    @Column(name = "revoked_at")
    private Instant revokedAt;

    @Column(name = "redirect_count", nullable = false)
    private long redirectCount;

    @Column(name = "first_redirect_at")
    private Instant firstRedirectAt;

    @Column(name = "last_redirect_at")
    private Instant lastRedirectAt;

    protected ShortLink() {
        // for JPA
    }

    public ShortLink(String code, String destination, String destinationCanonical,
                     String clientId, Instant createdAt, Instant expiresAt) {
        this.code = code;
        this.destination = destination;
        this.destinationCanonical = destinationCanonical;
        this.clientId = clientId;
        this.createdAt = createdAt;
        this.expiresAt = expiresAt;
        this.redirectCount = 0L;
    }

    public boolean isExpiredAt(Instant now) {
        return expiresAt != null && !expiresAt.isAfter(now);
    }

    public boolean isRevoked() {
        return revokedAt != null;
    }

    public boolean isOwnedBy(String candidate) {
        return clientId.equals(candidate);
    }

    public String getCode() { return code; }
    public String getDestination() { return destination; }
    public String getDestinationCanonical() { return destinationCanonical; }
    public String getClientId() { return clientId; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getExpiresAt() { return expiresAt; }
    public void setExpiresAt(Instant expiresAt) { this.expiresAt = expiresAt; }
    public Instant getRevokedAt() { return revokedAt; }
    public void setRevokedAt(Instant revokedAt) { this.revokedAt = revokedAt; }
    public long getRedirectCount() { return redirectCount; }
    public Instant getFirstRedirectAt() { return firstRedirectAt; }
    public Instant getLastRedirectAt() { return lastRedirectAt; }
}
