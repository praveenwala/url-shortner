package com.schwab.shortener.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.support.PostgresSupport;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/** Owner-only revoke (FR-012) and the owner-scoped analytics summary (FR-014). */
@SpringBootTest
@AutoConfigureMockMvc
class AnalyticsAndRevokeTest extends PostgresSupport {

    @Autowired MockMvc mvc;
    @Autowired ShortLinkRepository links;
    @Autowired RedirectEventRepository events;

    @BeforeEach
    void clean() {
        events.deleteAll();
        links.deleteAll();
    }

    private String create(String client) throws Exception {
        String body = mvc.perform(post("/v1/links")
                        .header("X-Client-Id", client)
                        .contentType("application/json")
                        .content("{\"destination\":\"https://example.com\"}"))
                .andReturn().getResponse().getContentAsString();
        return body.replaceAll(".*\"code\"\\s*:\\s*\"([^\"]+)\".*", "$1");
    }

    @Test
    void onlyTheCreatorMayRevoke() throws Exception {
        String code = create("client-a");

        mvc.perform(post("/v1/links/" + code + "/revoke").header("X-Client-Id", "client-b"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("forbidden"));
        assertThat(links.findById(code).orElseThrow().getRevokedAt()).isNull();

        mvc.perform(post("/v1/links/" + code + "/revoke").header("X-Client-Id", "client-a"))
                .andExpect(status().isOk());
        assertThat(links.findById(code).orElseThrow().getRevokedAt()).isNotNull();
    }

    @Test
    void revokedLinkNoLongerRedirects() throws Exception {
        String code = create("client-a");
        mvc.perform(get("/" + code)).andExpect(status().isFound());
        mvc.perform(post("/v1/links/" + code + "/revoke").header("X-Client-Id", "client-a"));

        mvc.perform(get("/" + code)).andExpect(status().isGone());
        assertThat(links.findById(code).orElseThrow().getRedirectCount()).isEqualTo(1L);
    }

    @Test
    void summaryReportsTotalFirstAndMostRecent() throws Exception {
        String code = create("client-a");
        mvc.perform(get("/" + code));
        mvc.perform(get("/" + code));
        mvc.perform(get("/" + code));

        mvc.perform(get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-a"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total_redirects").value(3))
                .andExpect(jsonPath("$.first_redirect_at").isString())
                .andExpect(jsonPath("$.last_redirect_at").isString());
    }

    @Test
    void summaryIsZeroRatherThanAnErrorForAnUnfollowedLink() throws Exception {
        String code = create("client-a");
        mvc.perform(get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-a"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total_redirects").value(0))
                .andExpect(jsonPath("$.first_redirect_at").doesNotExist());
    }

    @Test
    void analyticsAreOwnerScoped() throws Exception {
        String code = create("client-a");
        mvc.perform(get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-b"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.error").value("forbidden"));
    }

    @Test
    void lifetimeCountersAreIndependentOfEventRetention() throws Exception {
        // US5: the summary must keep telling the truth after events age out. The counters
        // are denormalised onto the link precisely so retention cannot alter them (FR-013).
        // This deletes events directly — it does not add a retention sweep, which stays
        // deferred.
        String code = create("client-a");
        for (int i = 0; i < 4; i++) {
            mvc.perform(get("/" + code)).andExpect(status().isFound());
        }
        events.deleteAll();
        assertThat(events.countByCode(code)).isZero();

        mvc.perform(get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-a"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total_redirects").value(4))
                .andExpect(jsonPath("$.first_redirect_at").isString())
                .andExpect(jsonPath("$.last_redirect_at").isString());
    }

    @Test
    void firstRedirectTimestampNeverMovesAndLatestAlwaysDoes() throws Exception {
        String code = create("client-a");
        mvc.perform(get("/" + code));
        String afterFirst = mvc.perform(
                        get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-a"))
                .andReturn().getResponse().getContentAsString();

        Thread.sleep(10);
        mvc.perform(get("/" + code));
        String afterSecond = mvc.perform(
                        get("/v1/links/" + code + "/analytics").header("X-Client-Id", "client-a"))
                .andReturn().getResponse().getContentAsString();

        String firstOne = afterFirst.replaceAll(".*\"first_redirect_at\":\"([^\"]+)\".*", "$1");
        String firstTwo = afterSecond.replaceAll(".*\"first_redirect_at\":\"([^\"]+)\".*", "$1");
        String lastOne = afterFirst.replaceAll(".*\"last_redirect_at\":\"([^\"]+)\".*", "$1");
        String lastTwo = afterSecond.replaceAll(".*\"last_redirect_at\":\"([^\"]+)\".*", "$1");

        assertThat(firstTwo).isEqualTo(firstOne);
        assertThat(lastTwo).isNotEqualTo(lastOne);
    }

    @Test
    void refusedResolutionsAreNotCounted() throws Exception {
        String code = create("client-a");
        links.findById(code).ifPresent(link -> {
            link.setExpiresAt(Instant.now().minusSeconds(1));
            links.save(link);
        });

        mvc.perform(get("/" + code)).andExpect(status().isGone());
        mvc.perform(get("/zzzzzzz")).andExpect(status().isNotFound());

        assertThat(links.findById(code).orElseThrow().getRedirectCount()).isZero();
        assertThat(events.countByCode(code)).isZero();
    }
}
