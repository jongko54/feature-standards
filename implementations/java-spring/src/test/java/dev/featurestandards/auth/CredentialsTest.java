package dev.featurestandards.auth;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.assertj.core.api.Assertions.*;

class CredentialsTest {
    @Test void normalizationPreservesUnicodeCaseAndNonAsciiWhitespace() {
        assertThat(Credentials.normalizeEmail("\t\n\u000b\f\r DEMO@EXAMPLE.COM \t")).isEqualTo("demo@example.com");
        assertThat(Credentials.normalizeEmail("\u00a0ÄΣİDEMO@EXAMPLE.COM\u00a0")).isEqualTo("\u00a0ÄΣİdemo@example.com\u00a0");
        assertThat(Credentials.normalizeEmail("\u001cDEMO@EXAMPLE.COM")).isEqualTo("\u001cdemo@example.com");
    }
    @ParameterizedTest
    @ValueSource(strings = {"", "{}", "[]", "null", "\"a\"", "{", "{} {}",
        "{\"email\":\"x@y\",\"password\":1}", "{\"email\":\"x@y\",\"password\":null}",
        "{\"email\":\"x@y\",\"password\":\"x\",\"admin\":true}",
        "{\"email\":\"x@y\",\"email\":\"a@b\",\"password\":\"x\"}",
        "{\"email\":\"x@y\",\"password\":\"x\",\"passw\\u006frd\":\"y\"}",
        "{\"email\":\"x@y\",\"password\":\"\\ud800\"}", "{\"email\":\"x@y\",\"password\":\"\\udfff\"}",
        "{\"email\":\"x@y\",\"password\":\"\\ud800x\"}", "{\"email\":\"x@y\",\"password\":\"\\ud800\\ud800\"}",
        "{\"email\":\"no-at\",\"password\":\"x\"}", "{\"email\":\"x@y\",\"password\":\"\"}"})
    void rejectsInvalidJsonAndUnicode(String json) {
        assertThatThrownBy(() -> Credentials.decode(json.getBytes(StandardCharsets.UTF_8))).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void rejectsMalformedUtf8InsteadOfReplacingIt() {
        byte[] bytes = "{\"email\":\"x@y\",\"password\":\"a\"}".getBytes(StandardCharsets.UTF_8);
        bytes[bytes.length - 3] = (byte) 0xff;
        assertThatThrownBy(() -> Credentials.decode(bytes)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void acceptsPairedSurrogatesAndLiteralBackslash() {
        assertThat(decodePassword("\\ud83d\\ude00")).isEqualTo("😀");
        assertThat(decodePassword("\\\\ud800")).isEqualTo("\\ud800");
    }
    @Test void boundariesUseUtf8Bytes() {
        assertThat(Credentials.validEmail("한".repeat(84) + "@x")).isTrue();
        assertThat(Credentials.validEmail("한".repeat(84) + "@xx")).isFalse();
        assertThat(Credentials.validPassword("😀".repeat(256))).isTrue();
        assertThat(Credentials.validPassword("😀".repeat(256) + "a")).isFalse();
        assertThat(Credentials.validPassword("a".repeat(1024))).isTrue();
        assertThat(Credentials.validPassword("a".repeat(1025))).isFalse();
    }
    private String decodePassword(String escaped) {
        return Credentials.decode(("{\"email\":\"x@y\",\"password\":\"" + escaped + "\"}").getBytes(StandardCharsets.UTF_8)).password();
    }
}
