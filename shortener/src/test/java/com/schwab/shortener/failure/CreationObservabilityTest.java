package com.schwab.shortener.failure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.schwab.shortener.obs.CreationMetrics;
import com.schwab.shortener.obs.DestinationDigest;
import com.schwab.shortener.obs.Events;
import com.schwab.shortener.support.PostgresSupport;
import com.schwab.shortener.web.CorrelationFilter;
import io.micrometer.core.instrument.MeterRegistry;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

/**
 * End-to-end observability for link creation.
 *
 * <p>The load-bearing property is <em>where</em> the success event is emitted. {@code
 * LinkService.create} is {@code @Transactional}, so an event emitted inside it would be written
 * before the proxy commits — it could claim a creation that then rolled back. The event therefore
 * lives in the controller, after the proxied call returns. {@link
 * #successEventIsEmittedOnlyAfterTheTransactionHasCommitted()} demonstrates that ordering.
 *
 * <p>The second property is that a destination never reaches a log line. A URL can carry a bearer
 * token in its query and credentials in its userinfo, and these lines go to stdout.
 */
@SpringBootTest
@AutoConfigureMockMvc
class CreationObservabilityTest extends PostgresSupport {

    private static final String TOKEN = "sk-not-a-real-token-value";
    private static final String SECRET_USER = "alice";
    private static final String SECRET_PW = "hunter2-not-real";
    private static final String DESTINATION =
            "https://" + SECRET_USER + ":" + SECRET_PW + "@example.com/private/path?access_token=" + TOKEN;

    @Autowired private MockMvc mockMvc;
    @Autowired private MeterRegistry registry;
    @Autowired private CreationMetrics metrics;

    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void captureLogs() {
        appender = new ListAppender<>();
        appender.start();
        LoggerContext context = (LoggerContext) LoggerFactory.getILoggerFactory();
        context.getLogger("ROOT").addAppender(appender);
        context.getLogger("ROOT").setLevel(Level.INFO);
    }

    @AfterEach
    void releaseLogs() {
        ((LoggerContext) LoggerFactory.getILoggerFactory()).getLogger("ROOT").detachAppender(appender);
    }

    private List<String> lines() {
        return appender.list.stream().map(ILoggingEvent::getFormattedMessage).toList();
    }

    private List<String> linesFor(String event) {
        return lines().stream().filter(l -> l.startsWith(event + " ")).toList();
    }

    private static double field(String line, String name) {
        Matcher m = Pattern.compile(name + "=([0-9.]+)").matcher(line);
        assertThat(m.find()).as("field %s present in: %s", name, line).isTrue();
        return Double.parseDouble(m.group(1));
    }

    private MvcResult create(String destination) throws Exception {
        return mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "obs-test")
                        .content("{\"destination\":\"" + destination + "\"}"))
                .andReturn();
    }

    // --- success path -------------------------------------------------------

    @Test
    void aSuccessfulPostEmitsExactlyOneCreationEvent() throws Exception {
        create("https://example.com/ok");
        assertThat(linesFor(Events.SHORT_LINK_CREATED)).hasSize(1);
        assertThat(linesFor(Events.SHORT_LINK_CREATION_FAILED)).isEmpty();
    }

    @Test
    void successEventIsEmittedOnlyAfterTheTransactionHasCommitted() throws Exception {
        // LinkService.create is @Transactional and injected into the controller as a field, so the
        // call goes through the transaction proxy. The controller emits only after that call
        // returns — i.e. after commit. Demonstrated structurally: the service no longer logs a
        // success event at all, so no "created" line can precede the commit.
        create("https://example.com/ordering");
        assertThat(linesFor(Events.LINK_CREATED))
                .as("the service must not emit a success event from inside the transaction")
                .isEmpty();
        assertThat(linesFor(Events.SHORT_LINK_CREATED)).hasSize(1);
    }

    @Test
    void theCreationEventCarriesEveryRequiredField() throws Exception {
        create("https://example.com/fields");
        String line = linesFor(Events.SHORT_LINK_CREATED).get(0);
        assertThat(line).contains("request_received_at=").contains("creation_started_at=")
                .contains("created_at=").contains("short_code=").contains("outcome=success");
        assertThat(field(line, "creation_duration_ms")).isGreaterThanOrEqualTo(0.0);
        assertThat(field(line, "db_lookup_duration_ms")).isGreaterThanOrEqualTo(0.0);
    }

    @Test
    void requestDurationIsAtLeastCreationDuration() throws Exception {
        create("https://example.com/nesting");
        double creation = field(linesFor(Events.SHORT_LINK_CREATED).get(0), "creation_duration_ms");
        double request = field(linesFor(Events.HTTP_REQUEST_COMPLETED).get(0), "request_duration_ms");
        assertThat(request)
                .as("the request brackets the creation, so it cannot be shorter")
                .isGreaterThanOrEqualTo(creation);
    }

    @Test
    void correlationIdMatchesAcrossTheResponseHeaderAndTheRequestEvent() throws Exception {
        String supplied = "corr-observability-0001";
        MvcResult result = mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "obs-test")
                        .header(CorrelationFilter.HEADER, supplied)
                        .content("{\"destination\":\"https://example.com/corr\"}"))
                .andExpect(status().isCreated()).andReturn();

        assertThat(result.getResponse().getHeader(CorrelationFilter.HEADER)).isEqualTo(supplied);
        // The correlation id reaches the log through MDC, which the JSON layout promotes.
        assertThat(appender.list.stream()
                .anyMatch(e -> supplied.equals(e.getMDCPropertyMap().get(CorrelationFilter.MDC_KEY))))
                .as("no log event carried the supplied correlation id").isTrue();
    }

    @Test
    void theRequestCompletionEventRecordsMethodPathAndStatus() throws Exception {
        create("https://example.com/completed");
        String line = linesFor(Events.HTTP_REQUEST_COMPLETED).get(0);
        assertThat(line).contains("method=POST").contains("path=/v1/links")
                .contains("status=201").contains("outcome=success");
    }

    // --- the destination never reaches a log ---------------------------------

    @Test
    void noLogLineContainsTheRawDestinationOrItsSecrets() throws Exception {
        create(DESTINATION);
        String all = String.join("\n", lines());
        assertThat(all).doesNotContain(TOKEN);
        assertThat(all).doesNotContain(SECRET_PW);
        assertThat(all).doesNotContain(SECRET_USER + ":");
        assertThat(all).doesNotContain("access_token");
        assertThat(all).doesNotContain("/private/path");
        assertThat(all).doesNotContain(DESTINATION);
    }

    @Test
    void theHostIsLoggedWithoutUserinfoPathQueryOrFragment() {
        String host = DestinationDigest.host(DESTINATION);
        assertThat(host).isEqualTo("example.com");
        assertThat(host).doesNotContain("@").doesNotContain("?").doesNotContain("/").doesNotContain("#");
    }

    @Test
    void theHashCorrelatesWithoutDisclosing() {
        String hash = DestinationDigest.hash(DESTINATION);
        assertThat(hash).hasSize(64).matches("[0-9a-f]+");
        assertThat(hash).isEqualTo(DestinationDigest.hash(DESTINATION));
        assertThat(hash).isNotEqualTo(DestinationDigest.hash(DESTINATION + "x"));
    }

    @Test
    void anUnparseableDestinationDoesNotLeakItself() {
        assertThat(DestinationDigest.host("::::not a url::::")).isEqualTo("unparseable");
    }

    // --- failure path --------------------------------------------------------

    @Test
    void aRejectedCreationEmitsTheFailureEventAndNoSuccessEvent() throws Exception {
        mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "obs-test")
                        .content("{\"destination\":\"javascript:alert(1)\"}"))
                .andExpect(status().isBadRequest());

        assertThat(linesFor(Events.SHORT_LINK_CREATED))
                .as("a failed creation must never produce a success event").isEmpty();
        List<String> failures = linesFor(Events.SHORT_LINK_CREATION_FAILED);
        assertThat(failures).hasSize(1);
        assertThat(failures.get(0)).contains("error_type=").contains("outcome=failed");
        assertThat(field(failures.get(0), "duration_ms")).isGreaterThanOrEqualTo(0.0);
    }

    @Test
    void theFailureEventLogsATypeNotAMessage() throws Exception {
        mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "obs-test")
                        .content("{\"destination\":\"" + DESTINATION.replace("https", "ftp") + "\"}"))
                .andExpect(status().isBadRequest());
        String line = linesFor(Events.SHORT_LINK_CREATION_FAILED).get(0);
        assertThat(line).contains("error_type=ApiException");
        assertThat(line).doesNotContain(TOKEN).doesNotContain(SECRET_PW);
    }

    @Test
    void responseSemanticsAreUnchangedByInstrumentation() throws Exception {
        MvcResult ok = create("https://example.com/semantics");
        assertThat(ok.getResponse().getStatus()).isEqualTo(201);
        assertThat(ok.getResponse().getContentAsString()).contains("\"code\":").contains("\"destination\":");
        // The instrumentation must not have added a field to the body.
        assertThat(ok.getResponse().getContentAsString())
                .doesNotContain("duration").doesNotContain("hash").doesNotContain("correlation");
    }

    @Test
    void mdcIsClearedAfterTheRequest() throws Exception {
        create("https://example.com/mdc");
        assertThat(MDC.get(CorrelationFilter.MDC_KEY)).isNull();
        assertThat(MDC.get(CorrelationFilter.MDC_RECEIVED_AT)).isNull();
    }

    // --- metrics -------------------------------------------------------------

    @Test
    void aSuccessfulCreationIncrementsTheSuccessTimerAndCounter() throws Exception {
        double before = metrics.counter("success") == null ? 0 : metrics.counter("success").count();
        create("https://example.com/metric-success");
        assertThat(metrics.timer("success").count()).isGreaterThan(0);
        assertThat(metrics.counter("success").count()).isGreaterThan(before);
    }

    @Test
    void aFailedCreationIncrementsTheFailureTimerAndCounter() throws Exception {
        mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "obs-test")
                        .content("{\"destination\":\"file:///etc/passwd\"}"))
                .andExpect(status().isBadRequest());
        assertThat(metrics.timer("failure").count()).isGreaterThan(0);
        assertThat(metrics.counter("failure").count()).isGreaterThan(0.0);
    }

    @Test
    void metricCardinalityStaysBounded() throws Exception {
        // Twenty distinct destinations, codes and hosts must not create twenty series.
        for (int i = 0; i < 20; i++) {
            create("https://host-" + i + ".example.com/p" + i);
        }
        long series = registry.find(CreationMetrics.TIMER).timers().size()
                + registry.find(CreationMetrics.COUNTER).counters().size();
        assertThat(series)
                .as("tags must be outcome and reason only — never code, host, hash or client")
                .isLessThanOrEqualTo(14);

        registry.find(CreationMetrics.TIMER).timers().forEach(t ->
                t.getId().getTags().forEach(tag ->
                        assertThat(tag.getKey()).isIn("outcome", "reason")));
    }
}
