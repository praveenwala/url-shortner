package com.schwab.shortener.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

/** One successful resolution of a short code (FR-013). Refused resolutions are not recorded. */
@Entity
@Table(name = "redirect_event")
public class RedirectEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 32)
    private String code;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    protected RedirectEvent() {
        // for JPA
    }

    public RedirectEvent(String code, Instant occurredAt) {
        this.code = code;
        this.occurredAt = occurredAt;
    }

    public Long getId() { return id; }
    public String getCode() { return code; }
    public Instant getOccurredAt() { return occurredAt; }
}
