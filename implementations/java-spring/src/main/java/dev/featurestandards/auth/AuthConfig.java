package dev.featurestandards.auth;

import java.net.URI;
import java.net.InetAddress;
import java.util.function.Function;

/** Validated configuration. The credential-bearing database URL is redacted from diagnostics. */
public record AuthConfig(String host, int port, boolean demo, boolean secure, String origin,
                  String email, long sessionTtl, int rateLimit, long rateWindow, String store, String databaseUrl) {
    public AuthConfig(String host, int port, boolean demo, boolean secure, String origin,
                      String email, long sessionTtl, int rateLimit, long rateWindow) {
        this(host, port, demo, secure, origin, email, sessionTtl, rateLimit, rateWindow, "memory", null);
    }
    @Override public String toString() { return "AuthConfig[store=" + store + ", databaseUrl=<redacted>]"; }
    public static AuthConfig load(Function<String, String> env) {
        String store = value(env, "AUTH_STORE", "memory");
        if (!store.equals("memory") && !store.equals("postgres")) throw invalid("AUTH_STORE must be memory or postgres");
        String databaseUrl = null;
        if (store.equals("postgres")) {
            databaseUrl = value(env, "AUTH_DATABASE_URL", "");
            PostgresConnectionFactory.validate(databaseUrl);
        }
        boolean demo = bool(env, "AUTH_DEMO", false);
        boolean secure = bool(env, "AUTH_COOKIE_SECURE", true);
        String host = value(env, "AUTH_HOST", "127.0.0.1");
        long port = positive(env, "AUTH_PORT", 8000);
        if (port > 65535) throw invalid("AUTH_PORT must be between 1 and 65535");
        String origin = value(env, "AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173");
        URI uri;
        try { uri = new URI(origin); } catch (Exception ex) { throw invalid("AUTH_ALLOWED_ORIGIN is invalid"); }
        if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) || uri.getHost() == null
                || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || (uri.getRawPath() != null && !uri.getRawPath().isEmpty()) || origin.contains("*")
                || uri.getPort() == 0 || uri.getPort() > 65535 || uri.getRawAuthority().endsWith(":")) {
            throw invalid("AUTH_ALLOWED_ORIGIN must be one exact HTTP(S) origin without path, credentials, query or fragment");
        }
        String originHost = uri.getHost();
        boolean loopback = originHost.equals("localhost") || ipv6Loopback(originHost)
                || originHost.matches("127(?:\\.(?:[0-9]{1,3})){3}") && validIpv4(originHost);
        if (!secure && (!demo || !loopback)) throw invalid("AUTH_COOKIE_SECURE=false requires an explicit loopback demo");
        if (!demo && !uri.getScheme().equals("https")) throw invalid("non-demo mode requires an HTTPS origin");
        String email = store.equals("postgres") ? "" : demo ? "demo@example.com" : Credentials.normalizeEmail(value(env, "AUTH_USER_EMAIL", ""));
        String password = store.equals("postgres") ? "" : password(env, demo);
        if (store.equals("memory") && (!Credentials.validEmail(email) || !Credentials.validPassword(password))) {
            throw invalid("non-demo mode requires valid AUTH_USER_EMAIL and AUTH_USER_PASSWORD");
        }
        long ttl = positive(env, "AUTH_SESSION_TTL_SECONDS", 1800);
        long window = positive(env, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 60);
        long max = positive(env, "AUTH_RATE_LIMIT_MAX", 5);
        if (max > Integer.MAX_VALUE) throw invalid("AUTH_RATE_LIMIT_MAX is outside the integer range");
        return new AuthConfig(host, (int) port, demo, secure, origin, email, ttl, (int) max, window, store, databaseUrl);
    }

    static String password(Function<String, String> env, boolean demo) {
        return demo ? "correct-horse-battery-staple" : value(env, "AUTH_USER_PASSWORD", "");
    }

    private static boolean ipv6Loopback(String host) {
        if (!host.contains(":")) return false; // Never resolve a DNS hostname to establish this exception.
        try { return InetAddress.getByName(host).isLoopbackAddress(); }
        catch (Exception ex) { return false; }
    }
    private static boolean validIpv4(String host) {
        for (String part : host.split("\\.")) if (Integer.parseInt(part) > 255) return false;
        return true;
    }
    private static String value(Function<String, String> env, String key, String fallback) {
        String value = env.apply(key);
        return value == null || value.isEmpty() ? fallback : value;
    }
    private static boolean bool(Function<String, String> env, String key, boolean fallback) {
        String raw = value(env, key, Boolean.toString(fallback));
        if (!raw.equals("true") && !raw.equals("false")) throw invalid(key + " must be true or false");
        return Boolean.parseBoolean(raw);
    }
    private static long positive(Function<String, String> env, String key, long fallback) {
        try {
            String raw = value(env, key, Long.toString(fallback));
            if (!raw.matches("[0-9]+")) throw new IllegalArgumentException();
            long result = Long.parseLong(raw);
            // Keep all second-based durations within a signed nanosecond duration.
            if (result <= 0 || result > Long.MAX_VALUE / 1_000_000_000L) throw new IllegalArgumentException();
            return result;
        } catch (IllegalArgumentException ex) { throw invalid(key + " must be a positive integer within duration range"); }
    }
    private static IllegalArgumentException invalid(String message) { return new IllegalArgumentException(message); }
}
