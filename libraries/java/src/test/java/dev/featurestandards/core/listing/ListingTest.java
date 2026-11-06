package dev.featurestandards.core.listing;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ListingTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static Listing.Schema schema() { return new Listing.Schema(Map.of("id", "string", "name", "string", "count", "integer", "active", "boolean"), Map.of("name", "string", "count", "integer", "active", "boolean")); }
    private static Path fixture() throws Exception {
        Path directory = Path.of(ListingTest.class.getProtectionDomain().getCodeSource().getLocation().toURI());
        while (directory != null) {
            Path candidate = directory.resolve("features/listing/scenarios.json"); if (Files.isRegularFile(candidate)) return candidate;
            directory = directory.getParent();
        }
        throw new IllegalStateException("shared scenarios not found");
    }
    @Test void sharedVectors() throws Exception {
        for (JsonNode vector : JSON.readTree(fixture().toFile()).get("cases")) {
            String id = vector.get("id").asText();
            java.util.function.Supplier<Listing.PageResult> execute = () -> {
                var raw = vector.get("schema");
                Listing.Schema selected = new Listing.Schema(JSON.convertValue(raw.get("sortFields"), new TypeReference<Map<String, String>>() {}), JSON.convertValue(raw.get("filterFields"), new TypeReference<Map<String, String>>() {}));
                List<Map<String, Object>> rows = JSON.convertValue(vector.get("items"), new TypeReference<>() {});
                return Listing.page(rows, Listing.parseQuery(vector.get("query").asText(), selected), selected);
            };
            JsonNode expected = vector.get("expected");
            if (expected.has("error")) {
                Listing.Error caught = assertThrows(Listing.Error.class, execute::get, id);
                assertEquals(expected.get("error").asText(), caught.code(), id); assertEquals(caught.code(), caught.getMessage(), id);
            } else assertEquals(expected, JSON.valueToTree(execute.get()), id);
        }
    }
    @Test void snapshotStableTiesAndScalarOrder() {
        Map<String, String> fields = new HashMap<>(Map.of("id", "string", "count", "integer"));
        Listing.Schema selected = new Listing.Schema(fields, Map.of()); fields.put("id", "integer");
        List<Map<String, Object>> rows = List.of(Map.of("id", "b", "count", 2), Map.of("id", "a", "count", 2), Map.of("id", "c", "count", 1));
        var result = Listing.page(rows, Listing.parseQuery("sort=-count&limit=1", selected), selected);
        assertEquals("a", result.items().getFirst().get("id")); assertEquals(1, result.nextOffset()); assertEquals("b", rows.getFirst().get("id"));
        List<Map<String, Object>> unicode = List.of(Map.of("id", "a", "name", "\uD800\uDC00"), Map.of("id", "b", "name", "\uE000"));
        assertEquals("b", Listing.page(unicode, Listing.parseQuery("sort=name", schema()), schema()).items().getFirst().get("id"));
    }
    @Test void invalidNativeInputsAndValidationBeforeFiltering() {
        for (String raw : List.of("sort=id\n", "filter.name=\uD800", "filter.name=%ED%A0%80", "filter.name=%ＦＦ")) assertEquals("INVALID_LIST_QUERY", assertThrows(Listing.Error.class, () -> Listing.parseQuery(raw, schema())).code());
        for (Object value : List.of(Double.NaN, Double.POSITIVE_INFINITY, true, 1.5, 9007199254740992L)) {
            var rows = List.<Map<String, Object>>of(Map.of("id", "a", "count", value));
            assertEquals("INVALID_LIST_DATA", assertThrows(Listing.Error.class, () -> Listing.page(rows, Listing.parseQuery("sort=count", schema()), schema())).code());
        }
        List<Map<String, Object>> tooMany = new ArrayList<>(); for (int i = 0; i < 10001; i++) tooMany.add(Map.of("id", "i" + i));
        assertEquals("INVALID_LIST_DATA", assertThrows(Listing.Error.class, () -> Listing.page(tooMany, Listing.parseQuery("", schema()), schema())).code());
        List<Map<String, Object>> hiddenInvalid = List.of(Map.of("id", "a", "active", false, "count", 1.5));
        assertEquals("INVALID_LIST_DATA", assertThrows(Listing.Error.class, () -> Listing.page(hiddenInvalid, Listing.parseQuery("sort=count&filter.active=true", schema()), schema())).code());
    }
}
