package dev.featurestandards.auth;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;

/** PostgreSQL v2 storage. It never creates schema, seeds users, or falls back to memory. */
public final class PostgresAuthStore implements AuthStore {
    @FunctionalInterface public interface Connections { Connection open() throws SQLException; }
    @FunctionalInterface private interface Transaction<T> { T run(Connection connection) throws SQLException; }
    private final AuthConfig config;
    private final Connections connections;

    public PostgresAuthStore(AuthConfig config) { this(config, new PostgresConnectionFactory(config.databaseUrl())); }
    public PostgresAuthStore(AuthConfig config, Connections connections) {
        this.config = config;
        this.connections = java.util.Objects.requireNonNull(connections);
        checkReady();
    }
    @Override public void checkReady() {
        try (Connection connection = connections.open();
             PreparedStatement statement = prepare(connection, "SELECT version FROM feature_auth.schema_version");
             ResultSet result = statement.executeQuery()) {
            if (!result.next() || result.getInt(1) != 1 || result.next()) throw new StorageUnavailableException();
        } catch (SQLException ex) { throw new StorageUnavailableException(); }
    }
    @Override public AuthService.Login login(String peer, String previous, String email, String password) {
        return transaction(connection -> {
            // Same namespace and PostgreSQL-normalized host key in every language.
            try (var lock = prepare(connection,
                    "SELECT pg_advisory_xact_lock(20261102, hashtext(host(CAST(? AS inet))))")) {
                lock.setString(1, peer);
                try (var ignored = lock.executeQuery()) { ignored.next(); }
            }
            Instant now = now(connection);
            try (var clean = prepare(connection,
                    "DELETE FROM feature_auth.login_attempts WHERE peer = CAST(host(CAST(? AS inet)) AS inet) AND expires_at <= ?")) {
                clean.setString(1, peer); clean.setTimestamp(2, Timestamp.from(now)); clean.executeUpdate();
            }
            try (var attempts = prepare(connection,
                    "SELECT failures, expires_at FROM feature_auth.login_attempts WHERE peer = CAST(host(CAST(? AS inet)) AS inet)")) {
                attempts.setString(1, peer);
                try (var result = attempts.executeQuery()) {
                    if (result.next() && result.getLong(1) >= config.rateLimit()) {
                        Duration remaining = Duration.between(now, result.getTimestamp(2).toInstant());
                        long seconds = remaining.getSeconds() + (remaining.getNano() > 0 ? 1 : 0);
                        return new AuthService.Login(null, null, Math.max(1, seconds));
                    }
                }
            }
            AuthService.User user = null;
            String hash = null;
            boolean enabled = false;
            try (var find = prepare(connection,
                    "SELECT id, email, password_hash, enabled FROM feature_auth.users WHERE email = ? FOR SHARE")) {
                find.setString(1, email);
                try (var result = find.executeQuery()) {
                    if (result.next()) {
                        user = new AuthService.User(result.getString(1), result.getString(2));
                        hash = result.getString(3); enabled = result.getBoolean(4);
                    }
                }
            }
            boolean matches = PasswordHashes.matches(password, hash);
            if (!matches || user == null || !enabled) {
                try (var fail = prepare(connection,
                        "INSERT INTO feature_auth.login_attempts(peer, failures, expires_at) VALUES (CAST(host(CAST(? AS inet)) AS inet), 1, ?) "
                        + "ON CONFLICT(peer) DO UPDATE SET failures = feature_auth.login_attempts.failures + 1")) {
                    fail.setString(1, peer); fail.setTimestamp(2, Timestamp.from(now.plusSeconds(config.rateWindow())));
                    fail.executeUpdate();
                }
                return new AuthService.Login(null, null, 0);
            }
            try (var clear = prepare(connection, "DELETE FROM feature_auth.login_attempts WHERE peer = CAST(host(CAST(? AS inet)) AS inet)")) {
                clear.setString(1, peer); clear.executeUpdate();
            }
            if (previous != null) delete(connection, Tokens.hash(previous));
            String token = Tokens.random();
            String csrf = Tokens.random();
            Instant created = now(connection);
            Instant expiry = created.plusSeconds(config.sessionTtl());
            try (var insert = prepare(connection,
                    "INSERT INTO feature_auth.sessions(token_hash, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)")) {
                insert.setBytes(1, Tokens.hash(token)); insert.setString(2, user.id()); insert.setString(3, csrf);
                insert.setTimestamp(4, Timestamp.from(created)); insert.setTimestamp(5, Timestamp.from(expiry));
                insert.executeUpdate();
            }
            return new AuthService.Login(new AuthService.Session(csrf, expiry, user), token, 0);
        });
    }
    @Override public AuthService.Session session(String token) {
        // Even an anonymous request must observe an unavailable database as 503.
        return transaction(connection -> {
            if (token == null) { now(connection); return null; }
            try (var find = prepare(connection,
                    "SELECT s.csrf_token, s.expires_at, u.id, u.email FROM feature_auth.sessions s "
                    + "JOIN feature_auth.users u ON u.id = s.user_id "
                    + "WHERE s.token_hash = ? AND u.enabled AND s.expires_at > clock_timestamp()")) {
                find.setBytes(1, Tokens.hash(token));
                try (var result = find.executeQuery()) { return result.next() ? readSession(result) : null; }
            }
        });
    }
    @Override public boolean logout(String token, String csrf) {
        return transaction(connection -> {
            if (token == null) { now(connection); return true; }
            // Lock first; read clock only after lock acquisition to handle expiry during lock waits.
            try (var find = prepare(connection,
                    "SELECT s.csrf_token, s.expires_at, u.id, u.email FROM feature_auth.sessions s "
                    + "JOIN feature_auth.users u ON u.id = s.user_id WHERE s.token_hash = ? FOR UPDATE OF s")) {
                byte[] hash = Tokens.hash(token);
                find.setBytes(1, hash);
                AuthService.Session session;
                try (var result = find.executeQuery()) {
                    if (!result.next()) return true;
                    session = readSession(result);
                }
                Instant now = now(connection);
                if (session.expiresAt().isAfter(now) && !Tokens.equal(session.csrfToken(), csrf)) return false;
                delete(connection, hash);
                return true;
            }
        });
    }
    private static AuthService.Session readSession(ResultSet result) throws SQLException {
        return new AuthService.Session(result.getString(1), result.getTimestamp(2).toInstant(),
                new AuthService.User(result.getString(3), result.getString(4)));
    }
    private static Instant now(Connection connection) throws SQLException {
        try (var statement = prepare(connection, "SELECT clock_timestamp()"); var result = statement.executeQuery()) {
            result.next(); return result.getTimestamp(1).toInstant();
        }
    }
    private static void delete(Connection connection, byte[] hash) throws SQLException {
        try (var statement = prepare(connection, "DELETE FROM feature_auth.sessions WHERE token_hash = ?")) {
            statement.setBytes(1, hash); statement.executeUpdate();
        }
    }
    private static PreparedStatement prepare(Connection connection, String sql) throws SQLException {
        PreparedStatement statement = connection.prepareStatement(sql);
        statement.setQueryTimeout(15);
        return statement;
    }
    private <T> T transaction(Transaction<T> operation) {
        try (Connection connection = connections.open()) {
            connection.setAutoCommit(false);
            try {
                T result = operation.run(connection);
                connection.commit();
                return result;
            } catch (SQLException | RuntimeException ex) {
                try { connection.rollback(); } catch (SQLException ignored) { }
                throw new StorageUnavailableException();
            }
        } catch (SQLException ex) { throw new StorageUnavailableException(); }
    }
}
