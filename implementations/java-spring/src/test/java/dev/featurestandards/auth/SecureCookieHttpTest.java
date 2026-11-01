package dev.featurestandards.auth;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "AUTH_DEMO=true", "AUTH_COOKIE_SECURE=true", "server.address=127.0.0.1"})
class SecureCookieHttpTest {
    @LocalServerPort int port;
    @Test void secureCookieIsPreservedWhenClearingIt() throws Exception {
        var client = HttpClient.newHttpClient();
        var login = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/auth/login"))
                .header("Origin", AuthHttpTest.ORIGIN).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(AuthHttpTest.LOGIN)).build();
        var response = client.send(login, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(200);
        assertThat(response.headers().firstValue("Set-Cookie").orElseThrow()).contains("; Secure", "; HttpOnly", "; SameSite=Lax");
        var logout = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/auth/logout"))
                .header("Origin", AuthHttpTest.ORIGIN).POST(HttpRequest.BodyPublishers.noBody()).build();
        var cleared = client.send(logout, HttpResponse.BodyHandlers.ofString());
        assertThat(cleared.statusCode()).isEqualTo(204);
        assertThat(cleared.headers().firstValue("Set-Cookie").orElseThrow()).contains("Max-Age=0", "; Secure", "; HttpOnly", "; SameSite=Lax");
    }
}
