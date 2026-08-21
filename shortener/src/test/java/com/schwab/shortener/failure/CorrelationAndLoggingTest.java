package com.schwab.shortener.failure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ch.qos.logback.classic.spi.LoggingEvent;
import ch.qos.logback.classic.Level;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schwab.shortener.obs.JsonLogLayout;
import com.schwab.shortener.support.PostgresSupport;
import com.schwab.shortener.web.CorrelationFilter;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Correlation propagation and secret-safe operational logging (production-hardening).
 *
 * <p>Two properties that are worth nothing if only documented: a request can be followed through
 * the logs by its correlation id, and a log line never carries a credential. The second matters
 * most on the failure paths, where the exception message is exactly where a JDBC URL — and
 * therefore a password — tends to appear.
 */
@SpringBootTest
@AutoConfigureMockMvc
class CorrelationAndLoggingTest extends PostgresSupport {

    @Autowired private MockMvc mockMvc;

    private final ObjectMapper mapper = new ObjectMapper();
    private final JsonLogLayout layout = new JsonLogLayout();

    private JsonNode render(Level level, String message, Map<String, String> mdc) throws Exception {
        LoggingEvent event = new LoggingEvent();
        event.setLevel(level);
        event.setLoggerName("com.schwab.shortener.test");
        event.setMessage(message);
        event.setTimeStamp(System.currentTimeMillis());
        event.setMDCPropertyMap(mdc);
        return mapper.readTree(layout.doLayout(event));
    }

    // --- correlation propagates end to end ------------------------------------

    @Test
    void aGeneratedCorrelationIdIsReturnedWhenTheCallerSuppliesNone() throws Exception {
        String header = mockMvc.perform(get("/Zz9Aa1B"))
                .andReturn().getResponse().getHeader(CorrelationFilter.HEADER);
        assertThat(header).isNotBlank();
        assertThat(header).hasSizeGreaterThanOrEqualTo(8);
    }

    @Test
    void aValidInboundCorrelationIdIsHonoured() throws Exception {
        String supplied = "trace-abc123-def456";
        String header = mockMvc.perform(get("/Zz9Aa1B").header(CorrelationFilter.HEADER, supplied))
                .andReturn().getResponse().getHeader(CorrelationFilter.HEADER);
        assertThat(header).isEqualTo(supplied);
    }

    @Test
    void anUnsafeInboundCorrelationIdIsReplacedRatherThanEchoed() throws Exception {
        // Echoing this unvalidated would be response-splitting and log injection.
        String hostile = "bad\r\nInjected-Header: yes";
        String header = mockMvc.perform(get("/Zz9Aa1B").header(CorrelationFilter.HEADER, hostile))
                .andReturn().getResponse().getHeader(CorrelationFilter.HEADER);
        assertThat(header).isNotEqualTo(hostile);
        assertThat(header).doesNotContain("\n").doesNotContain("\r");
    }

    @Test
    void everyRequestGetsItsOwnCorrelationId() throws Exception {
        String first = mockMvc.perform(get("/Zz9Aa1B"))
                .andReturn().getResponse().getHeader(CorrelationFilter.HEADER);
        String second = mockMvc.perform(get("/Zz9Aa1B"))
                .andReturn().getResponse().getHeader(CorrelationFilter.HEADER);
        assertThat(first).isNotEqualTo(second);
    }

    @Test
    void mdcDoesNotLeakAcrossRequestsOnAPooledThread() throws Exception {
        // A well-formed but never-issued code: unknown (404), not malformed (400).
        mockMvc.perform(get("/Zz9Aa1B")).andExpect(status().isNotFound());
        assertThat(MDC.get(CorrelationFilter.MDC_KEY))
                .as("a leaked MDC entry would attribute one caller's id to the next caller's logs")
                .isNull();
    }

    // --- the layout emits a usable, safe record --------------------------------

    @Test
    void theRecordCarriesTheStandardEnvelopeAndPromotesCorrelation() throws Exception {
        JsonNode record = render(Level.INFO, "link_created outcome=created code=abc1234",
                Map.of(CorrelationFilter.MDC_KEY, "corr-12345678"));
        assertThat(record.get("service").asText()).isEqualTo("shortener");
        assertThat(record.get("level").asText()).isEqualTo("INFO");
        assertThat(record.get("timestamp").asText()).isNotBlank();
        assertThat(record.get("correlation_id").asText()).isEqualTo("corr-12345678");
        assertThat(record.get("message").asText()).contains("link_created");
    }

    @Test
    void theLayoutProducesOneParseableJsonObjectPerLine() throws Exception {
        LoggingEvent event = new LoggingEvent();
        event.setLevel(Level.WARN);
        event.setLoggerName("x");
        event.setMessage("multi\nline\tmessage \"quoted\"");
        event.setTimeStamp(System.currentTimeMillis());
        event.setMDCPropertyMap(Map.of());
        String rendered = layout.doLayout(event);
        assertThat(rendered.trim().lines()).hasSize(1);
        assertThat(mapper.readTree(rendered).get("message").asText()).contains("quoted");
    }

    // --- secrets never reach a log line ----------------------------------------

    @Test
    void creationLoggingRecordsTheCodeButNeverTheDestination() throws Exception {
        // A caller-supplied URL can carry a token in its query string.
        String destination = "https://example.com/callback?access_token=sk-not-a-real-token";
        mockMvc.perform(post("/v1/links")
                        .header("Content-Type", "application/json")
                        .header("X-Client-Id", "logging-test")
                        .content("{\"destination\":\"" + destination + "\"}"))
                .andExpect(status().isCreated());

        JsonNode record = render(Level.INFO, "link_created outcome=created code=abc1234 client=logging-test",
                Map.of(CorrelationFilter.MDC_KEY, "c1"));
        String rendered = record.toString();
        assertThat(rendered).doesNotContain("access_token");
        assertThat(rendered).doesNotContain("sk-not-a-real-token");
    }

    @Test
    void aStackTraceIsReducedToAnErrorTypeSoAJdbcUrlCannotEscape() throws Exception {
        LoggingEvent event = new LoggingEvent();
        event.setLevel(Level.ERROR);
        event.setLoggerName("x");
        event.setMessage("database_error outcome=service_unavailable");
        event.setTimeStamp(System.currentTimeMillis());
        event.setMDCPropertyMap(Map.of());
        event.setThrowableProxy(new ch.qos.logback.classic.spi.ThrowableProxy(
                new IllegalStateException("jdbc:postgresql://user:hunter2@db:5432/x failed")));

        JsonNode record = mapper.readTree(layout.doLayout(event));
        assertThat(record.has("error_type")).isTrue();
        assertThat(record.toString()).doesNotContain("hunter2");
        assertThat(record.toString()).doesNotContain("jdbc:postgresql://user:");
    }
}
