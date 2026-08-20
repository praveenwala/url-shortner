package com.schwab.shortener.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.schwab.shortener.support.PostgresSupport;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Generates the shortener's OpenAPI document from the running application (T030).
 *
 * <p>The application is the source of runtime truth: this reads springdoc's {@code
 * /v3/api-docs} output rather than a hand-maintained description, so the published artifact
 * cannot drift from what the service actually serves. {@link OpenApiParityTest} is what fails
 * the build when it does.
 */
@SpringBootTest
@AutoConfigureMockMvc
class OpenApiGeneratorTest extends PostgresSupport {

    static final Path OUTPUT =
            Path.of(System.getProperty("user.dir"))
                    .getParent()
                    .resolve("docs/contracts/shortener-openapi.json");

    @Autowired MockMvc mvc;

    @Test
    void writesTheGeneratedDocument() throws Exception {
        String body = mvc.perform(get("/v3/api-docs"))
                .andReturn().getResponse().getContentAsString();
        assertThat(body).as("springdoc must serve the document").contains("\"openapi\"");

        ObjectMapper mapper = new ObjectMapper();
        mapper.enable(SerializationFeature.INDENT_OUTPUT);
        mapper.configure(com.fasterxml.jackson.databind.MapperFeature.SORT_PROPERTIES_ALPHABETICALLY, true);
        Object tree = mapper.readValue(body, Object.class);

        Files.createDirectories(OUTPUT.getParent());
        Files.writeString(OUTPUT, mapper.writerWithDefaultPrettyPrinter()
                .writeValueAsString(tree) + System.lineSeparator());
    }
}
