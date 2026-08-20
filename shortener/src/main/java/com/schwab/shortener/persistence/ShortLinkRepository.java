package com.schwab.shortener.persistence;

import com.schwab.shortener.domain.ShortLink;
import java.time.Instant;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ShortLinkRepository extends JpaRepository<ShortLink, String> {

    /**
     * Atomic counter increment (FR-013).
     *
     * <p>A read-modify-write through the entity would lose updates under concurrent redirects
     * to the same link. Expressing it as one UPDATE makes the increment a property of the row
     * lock rather than of application timing, and keeps first/last consistent with the total.
     */
    @Modifying
    @Query("""
           update ShortLink l
              set l.redirectCount = l.redirectCount + 1,
                  l.lastRedirectAt = :at,
                  l.firstRedirectAt = coalesce(l.firstRedirectAt, :at)
            where l.code = :code
           """)
    int recordRedirect(@Param("code") String code, @Param("at") Instant at);

    @Modifying
    @Query("update ShortLink l set l.revokedAt = :at where l.code = :code and l.revokedAt is null")
    int revoke(@Param("code") String code, @Param("at") Instant at);
}
