package dev.featurestandards.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Collections;
import java.util.Map;
import org.springframework.http.MediaType;

/** Own the small HTTP contract instead of inheriting framework-specific error/HEAD/OPTIONS responses. */
final class AuthFilter implements Filter {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final AuthConfig config;
    private final AuthService service;
    AuthFilter(AuthConfig config, AuthService service) { this.config = config; this.service = service; }

    @Override public void doFilter(ServletRequest input, ServletResponse output, FilterChain chain) throws IOException {
        var request = (HttpServletRequest) input;
        var response = (HttpServletResponse) output;
        String path = request.getRequestURI();
        if (path.startsWith("/auth/")) {
            response.setHeader("Cache-Control", "no-store");
            response.setHeader("X-Content-Type-Options", "nosniff");
        }
        String method = switch (path) {
            case "/auth/login", "/auth/logout" -> "POST";
            case "/auth/me", "/healthz" -> "GET";
            default -> null;
        };
        if (method == null) { error(response, 404, "NOT_FOUND"); return; }
        if (!request.getMethod().equals(method)) {
            response.setHeader("Allow", method);
            error(response, 405, "METHOD_NOT_ALLOWED"); return;
        }
        if (method.equals("POST") && !config.origin().equals(singleHeader(request, "Origin"))) {
            error(response, 403, "ORIGIN_DENIED"); return;
        }
        switch (path) {
            case "/auth/login" -> login(request, response);
            case "/auth/me" -> {
                var session = service.session(cookie(request));
                if (session == null) error(response, 401, "UNAUTHENTICATED");
                else user(response, session);
            }
            case "/auth/logout" -> {
                if (!service.logout(cookie(request), singleHeader(request, "X-CSRF-Token"))) {
                    error(response, 403, "CSRF_INVALID"); return;
                }
                response.setHeader("Set-Cookie", cookieHeader("", 0));
                response.setStatus(204);
            }
            case "/healthz" -> json(response, 200, Map.of("status", "ok", "profile", "browser-session-v1", "implementation", "java-spring"));
            default -> throw new IllegalStateException();
        }
    }
    private void login(HttpServletRequest request, HttpServletResponse response) throws IOException {
        try {
            String header = singleHeader(request, "Content-Type");
            if (header == null) throw new IllegalArgumentException();
            MediaType type = MediaType.parseMediaType(header);
            if (!type.getType().equalsIgnoreCase("application") || !type.getSubtype().equalsIgnoreCase("json")) {
                throw new IllegalArgumentException();
            }
        } catch (IllegalArgumentException ex) { error(response, 415, "UNSUPPORTED_MEDIA_TYPE"); return; }
        byte[] body = request.getInputStream().readNBytes(4097);
        if (body.length > 4096) { error(response, 413, "REQUEST_TOO_LARGE"); return; }
        Credentials credentials;
        try { credentials = Credentials.decode(body); }
        catch (IllegalArgumentException ex) { error(response, 400, "INVALID_REQUEST"); return; }
        // getRemoteAddr is the TCP peer: forwarded-header support is disabled at the server.
        var result = service.login(request.getRemoteAddr(), cookie(request), credentials);
        if (result.retryAfter() > 0) {
            response.setHeader("Retry-After", Long.toString(result.retryAfter()));
            error(response, 429, "RATE_LIMITED");
        } else if (result.session() == null) error(response, 401, "INVALID_CREDENTIALS");
        else {
            response.setHeader("Set-Cookie", cookieHeader(result.token(), config.sessionTtl()));
            user(response, result.session());
        }
    }
    private static String singleHeader(HttpServletRequest request, String name) {
        var values = Collections.list(request.getHeaders(name));
        return values.size() == 1 ? values.getFirst() : null;
    }
    private static String cookie(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) for (Cookie cookie : cookies) if (cookie.getName().equals("fs_session")) return cookie.getValue();
        return null;
    }
    private String cookieHeader(String value, long maxAge) {
        return "fs_session=" + value + "; Path=/; Max-Age=" + maxAge + "; HttpOnly; SameSite=Lax" + (config.secure() ? "; Secure" : "");
    }
    private void user(HttpServletResponse response, AuthService.Session session) throws IOException {
        json(response, 200, Map.of("user", Map.of("id", "demo-user", "email", config.email()), "csrfToken", session.csrfToken()));
    }
    private static void error(HttpServletResponse response, int status, String code) throws IOException {
        json(response, status, Map.of("error", Map.of("code", code, "message", code)));
    }
    private static void json(HttpServletResponse response, int status, Object body) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        JSON.writeValue(response.getOutputStream(), body);
    }
}
