package dev.featurestandards.auth;

import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.assertj.core.api.Assertions.*;

class AuthConfigTest {
    @Test void explicitDemoRequired() {
        assertThatThrownBy(() -> AuthConfig.load(Map.<String, String>of()::get)).isInstanceOf(IllegalArgumentException.class);
        var demo = AuthConfig.load(Map.of("AUTH_DEMO", "true")::get);
        assertThat(demo.secure()).isTrue();
        assertThat(demo.email()).isEqualTo("demo@example.com");
    }
    @Test void normalizesConfiguredUnicodeUserWithoutLowercasingUnicode() {
        var env = Map.of("AUTH_ALLOWED_ORIGIN", "https://example.com", "AUTH_USER_EMAIL", "\tÄDEMO@EXAMPLE.COM\r",
                "AUTH_USER_PASSWORD", "한글😀 ");
        assertThat(AuthConfig.load(env::get).email()).isEqualTo("Ädemo@example.com");
    }
    @ParameterizedTest @ValueSource(strings = {"http://*", "http://localhost/", "http://localhost?q", "http://localhost#x",
        "http://user@localhost", "http://localhost:0", "http://localhost:65536", "http://localhost:",
        "http://localhost:abc", "null", "file:///tmp", "http://localhost,localhost"})
    void rejectsNonOrigins(String origin) {
        assertInvalid("AUTH_ALLOWED_ORIGIN", origin);
    }
    @ParameterizedTest @ValueSource(strings = {"0", "-1", "1.5", "true", "999999999999999999999", "9223372037", " 5"})
    void rejectsInvalidPositiveIntegers(String value) {
        for (String key : new String[]{"AUTH_SESSION_TTL_SECONDS", "AUTH_RATE_LIMIT_MAX", "AUTH_RATE_LIMIT_WINDOW_SECONDS"}) {
            assertInvalid(key, value);
        }
    }
    @Test void rejectsUnsafeInsecureCookiesAndInvalidBooleans() {
        assertInvalid("AUTH_DEMO", "yes");
        assertInvalid("AUTH_COOKIE_SECURE", "False");
        assertInvalid("AUTH_PORT", "65536");
        assertThatThrownBy(() -> AuthConfig.load(Map.of("AUTH_DEMO", "true", "AUTH_COOKIE_SECURE", "false",
                "AUTH_ALLOWED_ORIGIN", "http://127.0.0.999")::get)).isInstanceOf(IllegalArgumentException.class);
        for (String origin : new String[]{"http://localhost", "http://127.0.0.1", "http://[::1]:5173"}) {
            assertThat(AuthConfig.load(Map.of("AUTH_DEMO", "true", "AUTH_COOKIE_SECURE", "false", "AUTH_ALLOWED_ORIGIN", origin)::get).secure()).isFalse();
        }
        assertThatThrownBy(() -> AuthConfig.load(Map.of("AUTH_USER_EMAIL", "x@y", "AUTH_USER_PASSWORD", "p",
                "AUTH_COOKIE_SECURE", "false", "AUTH_ALLOWED_ORIGIN", "https://localhost")::get)).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> AuthConfig.load(Map.of("AUTH_USER_EMAIL", "x@y", "AUTH_USER_PASSWORD", "p")::get)).isInstanceOf(IllegalArgumentException.class);
    }
    private void assertInvalid(String key, String value) {
        var env = new HashMap<>(Map.of("AUTH_DEMO", "true")); env.put(key, value);
        assertThatThrownBy(() -> AuthConfig.load(env::get)).isInstanceOf(IllegalArgumentException.class);
    }
}
