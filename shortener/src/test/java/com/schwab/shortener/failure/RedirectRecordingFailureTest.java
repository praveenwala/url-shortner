package com.schwab.shortener.failure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.service.LinkService;
import com.schwab.shortener.support.PostgresSupport;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.test.web.servlet.MockMvc;

/**
 * T020 — a redirect that cannot be durably counted is not served (R14, approval item 7).
 *
 * <p>The approved consistency-over-availability decision, made testable: exact accounting is
 * part of successful redirect processing. If the count cannot be committed, the caller gets a
 * failure rather than an uncounted redirect.
 */
@SpringBootTest
@AutoConfigureMockMvc
class RedirectRecordingFailureTest extends PostgresSupport {

    @Autowired MockMvc mvc;
    @Autowired LinkService links;
    @Autowired ShortLinkRepository repository;
    @SpyBean RedirectEventRepository events;

    private String code;

    @BeforeEach
    void setUp() {
        Mockito.reset(events);
        events.deleteAll();
        repository.deleteAll();
        code = links.create("https://example.com/target", null, "client-a").code();
    }

    @Test
    void aRedirectWhoseAnalyticsWriteFailsIsNotServed() throws Exception {
        Mockito.doThrow(new DataAccessResourceFailureException("event store unavailable"))
                .when(events).save(Mockito.any());

        mvc.perform(get("/" + code))
                .andExpect(status().is5xxServerError())
                .andExpect(header().doesNotExist("Location"));

        Mockito.reset(events);
        assertThat(repository.findById(code).orElseThrow().getRedirectCount())
                .as("a failed transaction must leave the counter untouched")
                .isZero();
        assertThat(events.countByCode(code)).isZero();
    }

    @Test
    void theCounterAndTheEventStayConsistentAfterAFailure() throws Exception {
        mvc.perform(get("/" + code)).andExpect(status().isFound());

        Mockito.doThrow(new DataAccessResourceFailureException("event store unavailable"))
                .when(events).save(Mockito.any());
        mvc.perform(get("/" + code)).andExpect(status().is5xxServerError());

        Mockito.reset(events);
        assertThat(repository.findById(code).orElseThrow().getRedirectCount()).isEqualTo(1L);
        assertThat(events.countByCode(code)).isEqualTo(1L);
    }

    @Test
    void recoveryAfterTheFailureResumesExactCounting() throws Exception {
        Mockito.doThrow(new DataAccessResourceFailureException("down"))
                .when(events).save(Mockito.any());
        mvc.perform(get("/" + code)).andExpect(status().is5xxServerError());

        Mockito.reset(events);
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        assertThat(repository.findById(code).orElseThrow().getRedirectCount()).isEqualTo(1L);
        assertThat(events.countByCode(code)).isEqualTo(1L);
    }
}
