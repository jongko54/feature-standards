package dev.featurestandards.auth;

import java.security.MessageDigest;
import java.security.SecureRandom;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;

/** Process-local, single-user state. Hash verification is serialized to bound its memory use. */
final class AuthService {
    record Session(String csrfToken, Instant expiresAt) { }
    private record Failure(int count, Instant expiresAt) { }
    record Login(Session session, String token, long retryAfter) { }
    private final AuthConfig config;
    private final Clock clock;
    private final SecureRandom random = new SecureRandom();
    private final Argon2PasswordEncoder encoder = new Argon2PasswordEncoder(16, 32, 4, 65536, 3);
    private final String passwordHash;
    private final Map<String, Session> sessions = new HashMap<>();
    private final Map<String, Failure> failures = new HashMap<>();

    AuthService(AuthConfig config, String password, Clock clock) {
        this.config = config;
        this.clock = clock;
        this.passwordHash = encoder.encode(password);
    }
    synchronized Login login(String peer, String previous, Credentials credentials) {
        Instant now = clock.instant();
        clean(now);
        Failure failure = failures.get(peer);
        if (failure != null && failure.count >= config.rateLimit()) {
            long remainingMillis = java.time.Duration.between(now, failure.expiresAt).toMillis();
            return new Login(null, null, Math.max(1, (remainingMillis + 999) / 1000));
        }
        // Verify even for an unknown email. No early account-existence branch skips Argon2id.
        boolean passwordMatches = encoder.matches(credentials.password(), passwordHash);
        if (!passwordMatches || !credentials.email().equals(config.email())) {
            failures.put(peer, failure == null ? new Failure(1, now.plusSeconds(config.rateWindow()))
                    : new Failure(failure.count + 1, failure.expiresAt));
            return new Login(null, null, 0);
        }
        failures.remove(peer);
        if (previous != null) sessions.remove(previous);
        String token = token();
        Session session = new Session(token(), clock.instant().plusSeconds(config.sessionTtl()));
        sessions.put(token, session);
        return new Login(session, token, 0);
    }
    synchronized Session session(String token) {
        clean(clock.instant());
        return token == null ? null : sessions.get(token);
    }
    synchronized boolean logout(String token, String csrf) {
        Session session = session(token);
        if (session == null) return true;
        if (csrf == null || !MessageDigest.isEqual(session.csrfToken.getBytes(StandardCharsets.UTF_8), csrf.getBytes(StandardCharsets.UTF_8))) {
            return false;
        }
        sessions.remove(token);
        return true;
    }
    private void clean(Instant now) {
        sessions.values().removeIf(session -> !session.expiresAt.isAfter(now));
        failures.values().removeIf(failure -> !failure.expiresAt.isAfter(now));
    }
    private String token() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
