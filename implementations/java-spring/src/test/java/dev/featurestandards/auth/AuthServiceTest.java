package dev.featurestandards.auth;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

class AuthServiceTest {
    static final class TestClock extends Clock {
        Instant now = Instant.parse("2026-11-01T00:00:00Z");
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return this; }
        public Instant instant() { return now; }
    }
    @Test void verifiesUnicodePasswordsAndAbsoluteSessionExpiry() {
        var clock = new TestClock();
        var config = new AuthConfig("127.0.0.1", 8000, false, true, "https://example.com", "Ädemo@x", 3, 3, 60);
        var service = new AuthService(config, "한글😀 ", clock);
        var login = service.login("peer", null, new Credentials("Ädemo@x", "한글😀 "));
        assertThat(login.session()).isNotNull();
        assertThat(login.token()).hasSize(43);
        assertThat(login.session().csrfToken()).hasSize(43).isNotEqualTo(login.token());
        clock.now = clock.now.plusSeconds(2);
        assertThat(service.session(login.token())).isNotNull();
        clock.now = clock.now.plusSeconds(1);
        assertThat(service.session(login.token())).isNull();
    }
    @Test void rateLimitHasFixedWindowAndSuccessClearsFailures() {
        var clock = new TestClock();
        var config = new AuthConfig("127.0.0.1", 8000, true, false, "http://localhost", "x@y", 3, 2, 3);
        var service = new AuthService(config, "p", clock);
        var correct = new Credentials("x@y", "p");
        assertThat(service.login("peer", null, new Credentials("missing@y", "p")).session()).isNull();
        assertThat(service.login("peer", null, correct).session()).isNotNull();
        assertThat(service.login("peer", null, new Credentials("x@y", "wrong")).retryAfter()).isZero();
        clock.now = clock.now.plusSeconds(1);
        assertThat(service.login("peer", null, new Credentials("x@y", "wrong")).retryAfter()).isZero();
        assertThat(service.login("peer", null, correct).retryAfter()).isEqualTo(2);
        assertThat(service.login("other-peer", null, correct).session()).isNotNull();
        clock.now = clock.now.plusSeconds(2);
        assertThat(service.login("peer", null, correct).session()).isNotNull();
    }
}
