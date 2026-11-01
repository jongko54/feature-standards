package dev.featurestandards.auth;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

record Credentials(String email, String password) {
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    static Credentials decode(byte[] body) throws IllegalArgumentException {
        try {
            String raw = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(body)).toString();
            JsonNode json = JSON.readTree(raw);
            if (json == null || !json.isObject() || json.size() != 2 || !json.has("email") || !json.has("password")
                    || !json.get("email").isTextual() || !json.get("password").isTextual()) throw new IllegalArgumentException();
            String email = normalizeEmail(json.get("email").textValue());
            String password = json.get("password").textValue();
            if (!validEmail(email) || !validPassword(password)) throw new IllegalArgumentException();
            return new Credentials(email, password);
        } catch (Exception ex) { throw new IllegalArgumentException("Invalid credentials JSON"); }
    }

    static String normalizeEmail(String value) {
        int start = 0, end = value.length();
        while (start < end && asciiSpace(value.charAt(start))) start++;
        while (end > start && asciiSpace(value.charAt(end - 1))) end--;
        var normalized = new StringBuilder(end - start);
        for (int i = start; i < end; i++) {
            char c = value.charAt(i);
            normalized.append(c >= 'A' && c <= 'Z' ? (char) (c + 32) : c);
        }
        return normalized.toString();
    }
    private static boolean asciiSpace(char c) { return c == ' ' || c >= '\t' && c <= '\r'; }
    static boolean validEmail(String email) {
        return validUnicode(email) && !email.isEmpty() && email.contains("@") && bytes(email) <= 254;
    }
    static boolean validPassword(String password) { return validUnicode(password) && bytes(password) >= 1 && bytes(password) <= 1024; }
    static int bytes(String value) { return value.getBytes(StandardCharsets.UTF_8).length; }
    static boolean validUnicode(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isHighSurrogate(c)) {
                if (++i >= value.length() || !Character.isLowSurrogate(value.charAt(i))) return false;
            } else if (Character.isLowSurrogate(c)) return false;
        }
        return true;
    }
}
