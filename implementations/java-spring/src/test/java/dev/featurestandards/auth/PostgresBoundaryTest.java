package dev.featurestandards.auth;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import static org.assertj.core.api.Assertions.*;

class PostgresBoundaryTest {
    @Test void verifiesExactPortablePhcAndRejectsMalformedAndUnsupportedHashes() {
        String hash = new Argon2PasswordEncoder(16, 32, 4, 65536, 3).encode("한글😀 ");
        assertThat(PasswordHashes.matches("한글😀 ", hash)).isTrue();
        assertThat(PasswordHashes.matches("wrong", hash)).isFalse();
        assertThat(PasswordHashes.matches("wrong", null)).isFalse();
        for (String unsupported : new String[]{"bcrypt", hash.replace("v=19", "v=16"),
                hash.replace("m=65536", "m=32768"), hash + "=", hash.replace("argon2id", "argon2i"),
                hash.substring(0, hash.lastIndexOf('$')) + "$invalid"}) {
            assertThatThrownBy(() -> PasswordHashes.matches("password", unsupported))
                    .isInstanceOf(StorageUnavailableException.class).hasNoCause();
        }
    }
    @Test void rejectsInvalidUrlsWithoutLeakingTheirContentsOrAcceptingSchemaSelection() {
        for (String url : new String[]{"", "jdbc:postgresql://secret@localhost/test", "postgresql://secret@localhost",
                "postgresql://secret@localhost/test?currentSchema=other", "postgresql://secret@localhost/test?options=-c%20search_path=other",
                "postgresql://secret@localhost:65536/test", "postgresql://secret@localhost/test#secret"}) {
            assertThatThrownBy(() -> PostgresConnectionFactory.validate(url)).isInstanceOf(IllegalArgumentException.class)
                    .hasMessageNotContaining("secret").hasNoCause();
        }
        assertThat(new PostgresConnectionFactory("postgresql://user:p%40ss+word@localhost/test?sslmode=disable").toString())
                .doesNotContain("user", "word", "localhost");
    }
    @Test void injectedStoreSuppliesUserIdentityToHttpWithoutServletOrSqlInService() throws Exception {
        var session = new AuthService.Session("csrf", Instant.now().plusSeconds(60),
                new AuthService.User("원본-id😀", "other@example.com"));
        AuthStore store = new AuthStore() {
            public AuthService.Login login(String peer, String old, String email, String password) {
                assertThat(email).isEqualTo("other@example.com");
                return new AuthService.Login(session, "token", 0);
            }
            public AuthService.Session session(String token) { return session; }
            public boolean logout(String token, String csrf) { return true; }
        };
        var config = AuthConfig.load(Map.of("AUTH_DEMO", "true")::get);
        var service = new AuthService(store);
        assertThat(service.login("127.0.0.1", null, "  OTHER@EXAMPLE.COM ", "p").session().user().id()).isEqualTo("원본-id😀");
        var request = new MockHttpServletRequest("GET", "/auth/me");
        var response = new MockHttpServletResponse();
        new AuthFilter(config, service).doFilter(request, response, (a, b) -> fail("Unexpected chain"));
        assertThat(response.getStatus()).isEqualTo(200);
        var body = AuthHttpTest.JSON.readTree(response.getContentAsString());
        assertThat(body.path("user").path("id").asText()).isEqualTo("원본-id😀");
        assertThat(body.path("user").path("email").asText()).isEqualTo("other@example.com");
    }
    @Test void everyStorageFailureUsesGeneric503WithNoCookieIncludingAnonymousAndHealth() throws Exception {
        AuthStore unavailable = new AuthStore() {
            public AuthService.Login login(String peer, String old, String email, String password) { throw new StorageUnavailableException(); }
            public AuthService.Session session(String token) { throw new StorageUnavailableException(); }
            public boolean logout(String token, String csrf) { throw new StorageUnavailableException(); }
            public void checkReady() { throw new StorageUnavailableException(); }
        };
        var config = AuthConfig.load(Map.of("AUTH_DEMO", "true")::get);
        var filter = new AuthFilter(config, new AuthService(unavailable));
        for (String path : new String[]{"/auth/login", "/auth/me", "/auth/logout", "/healthz"}) {
            var request = new MockHttpServletRequest(path.equals("/auth/login") || path.equals("/auth/logout") ? "POST" : "GET", path);
            request.addHeader("Origin", config.origin());
            request.addHeader("Content-Type", "application/json");
            request.setContent(AuthHttpTest.LOGIN.getBytes(StandardCharsets.UTF_8));
            var response = new MockHttpServletResponse();
            filter.doFilter(request, response, (a, b) -> fail("Unexpected chain"));
            assertThat(response.getStatus()).isEqualTo(503);
            assertThat(response.getContentAsString()).contains("STORAGE_UNAVAILABLE");
            assertThat(response.getHeader("Set-Cookie")).isNull();
            assertThat(response.getHeader("Cache-Control")).isEqualTo("no-store");
            assertThat(response.getHeader("X-Content-Type-Options")).isEqualTo("nosniff");
        }
    }
}
