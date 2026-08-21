package com.schwab.shortener;

import com.schwab.shortener.obs.Events;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.context.event.EventListener;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/** Shortener service entry point (T011). Business features are not implemented yet. */
@SpringBootApplication
public class ShortenerApplication {

    private static final Logger LOG = LoggerFactory.getLogger(ShortenerApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(ShortenerApplication.class, args);
    }

    /** Startup and shutdown are the two lines an operator looks for first in a container log. */
    @EventListener(ApplicationReadyEvent.class)
    public void onReady() {
        LOG.info("{} outcome=ready", Events.APPLICATION_STARTED);
    }

    @EventListener(ContextClosedEvent.class)
    public void onStopping() {
        LOG.info("{} outcome=stopping", Events.APPLICATION_STOPPING);
    }
}
