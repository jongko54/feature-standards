package dev.featurestandards.auth;

import java.util.Base64;
import java.util.regex.Pattern;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;

final class PasswordHashes {
    private static final Argon2PasswordEncoder ENCODER = new Argon2PasswordEncoder(16, 32, 4, 65536, 3);
    private static final Pattern PHC = Pattern.compile(
            "^\\$argon2id\\$v=19\\$m=65536,t=3,p=4\\$([A-Za-z0-9+/]{22})\\$([A-Za-z0-9+/]{43})$");
    private static final String DUMMY = ENCODER.encode("feature-auth-dummy-password");
    // Bound expensive verification memory across connections in this JVM.
    static synchronized boolean matches(String password, String hash) {
        String actual = hash == null ? DUMMY : hash;
        var match = PHC.matcher(actual);
        if (!match.matches() || !canonical(match.group(1), 16) || !canonical(match.group(2), 32)) {
            throw new StorageUnavailableException();
        }
        try { return ENCODER.matches(password, actual); }
        catch (RuntimeException ex) { throw new StorageUnavailableException(); }
    }
    private static boolean canonical(String value, int length) {
        try {
            byte[] decoded = Base64.getDecoder().decode(value);
            return decoded.length == length && Base64.getEncoder().withoutPadding().encodeToString(decoded).equals(value);
        } catch (IllegalArgumentException ex) { return false; }
    }
}
