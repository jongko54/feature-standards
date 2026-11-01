package dev.featurestandards.auth;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Map;
import java.util.Properties;

/** Converts a libpq-style URI without retaining credentials in the JDBC URL or diagnostics. */
public final class PostgresConnectionFactory implements PostgresAuthStore.Connections {
    private final String jdbcUrl;
    private final Properties properties = new Properties();
    private static final Map<String, String> OPTIONS = Map.ofEntries(
            Map.entry("user", "user"), Map.entry("password", "password"), Map.entry("sslmode", "sslmode"),
            Map.entry("ssl", "ssl"), Map.entry("sslcert", "sslcert"), Map.entry("sslkey", "sslkey"),
            Map.entry("sslrootcert", "sslrootcert"), Map.entry("sslpassword", "sslpassword"),
            Map.entry("application_name", "ApplicationName"), Map.entry("connect_timeout", "connectTimeout"));

    public PostgresConnectionFactory(String databaseUrl) {
        try {
            URI uri = new URI(databaseUrl);
            if (!(uri.getScheme().equals("postgresql") || uri.getScheme().equals("postgres")) || uri.getHost() == null
                    || uri.getPort() == 0 || uri.getPort() > 65535 || uri.getRawFragment() != null
                    || uri.getRawPath() == null || !uri.getRawPath().matches("/[^/]+")
                    || uri.getRawAuthority().endsWith(":")) throw new IllegalArgumentException();
            String authority = uri.getRawAuthority();
            jdbcUrl = "jdbc:postgresql://" + authority.substring(authority.lastIndexOf('@') + 1) + uri.getRawPath();
            if (uri.getRawUserInfo() != null) {
                String[] credentials = uri.getRawUserInfo().split(":", 2);
                properties.setProperty("user", decode(credentials[0]));
                if (credentials.length == 2) properties.setProperty("password", decode(credentials[1]));
            }
            if (uri.getRawQuery() != null) {
                for (String item : uri.getRawQuery().split("&")) {
                    String[] option = item.split("=", 2);
                    String name = OPTIONS.get(decode(option[0]));
                    if (name == null || option.length != 2) throw new IllegalArgumentException();
                    properties.setProperty(name, decode(option[1]));
                }
            }
            // URI options cannot disable the finite network bounds.
            properties.setProperty("connectTimeout", "5");
            properties.setProperty("loginTimeout", "5");
            properties.setProperty("socketTimeout", "15");
            properties.setProperty("cancelSignalTimeout", "5");
            properties.setProperty("ApplicationName", "feature-auth-java");
        } catch (Exception ex) {
            throw new IllegalArgumentException("AUTH_DATABASE_URL must be a valid PostgreSQL URI with supported connection options");
        }
    }
    public static void validate(String databaseUrl) { new PostgresConnectionFactory(databaseUrl); }
    @Override public Connection open() throws SQLException { return DriverManager.getConnection(jdbcUrl, properties); }
    @Override public String toString() { return "PostgresConnectionFactory[<redacted>]"; }
    private static String decode(String value) {
        return URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8);
    }
}
