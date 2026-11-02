package dev.featurestandards.auth;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Set;

/** Strict account request boundary; passwords and capabilities never appear in diagnostics. */
record AccountInput(String email, String token, String password) {
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    static AccountInput decode(String action, byte[] body) {
        try {
            String raw = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(body)).toString();
            JsonNode json = JSON.readTree(raw);
            Set<String> expected = fields(action);
            if (json == null || !json.isObject() || json.size() != expected.size()) throw new IllegalArgumentException();
            for (String key : expected) if (!json.has(key) || !json.get(key).isTextual()) throw new IllegalArgumentException();
            return checked(action, value(json, "email"), value(json, "token"), value(json, "password"));
        } catch (Exception ex) { throw new IllegalArgumentException("Invalid account JSON"); }
    }
    static AccountInput checked(String action, String email, String token, String password) {
        Set<String> expected = fields(action);
        if (expected.contains("email") && email == null || expected.contains("token") && token == null
                || expected.contains("password") && password == null) throw new IllegalArgumentException("Invalid account input");
        String normalized = expected.contains("email") ? Credentials.normalizeEmail(email) : "";
        String capability = expected.contains("token") ? token : "";
        String secret = expected.contains("password") ? password : "";
        if (expected.contains("email") && (!Credentials.validEmail(normalized)
                    || normalized.chars().anyMatch(c -> c <= 0x20 || c == 0x7f))
                || expected.contains("token") && !capability.matches("[A-Za-z0-9_-]{43}")
                || expected.contains("password") && (!Credentials.validPassword(secret)
                    || secret.codePointCount(0, secret.length()) < 15)) {
            throw new IllegalArgumentException("Invalid account input");
        }
        return new AccountInput(normalized, capability, secret);
    }
    private static String value(JsonNode json, String key) { return json.has(key) ? json.get(key).textValue() : ""; }
    private static Set<String> fields(String action) {
        return switch (action) {
            case "register" -> Set.of("email", "password");
            case "verify-request", "reset-request" -> Set.of("email");
            case "verify-confirm" -> Set.of("token");
            case "reset-confirm" -> Set.of("token", "password");
            default -> throw new IllegalArgumentException("Unknown account action");
        };
    }
    @Override public String toString() { return "AccountInput[<redacted>]"; }
}
