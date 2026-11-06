package dev.featurestandards.core.listing;

import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Strict offset-list-v1. Apply server authorization before constructing rows. */
public final class Listing {
    private Listing() {}
    private static final long SAFE = 9007199254740991L;
    private static final Pattern FIELD = Pattern.compile("[a-z][a-z0-9_]{0,31}\\z");
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\\z");
    private static final Pattern UNSIGNED = Pattern.compile("(?:0|[1-9][0-9]*)\\z");
    private static final Pattern SIGNED = Pattern.compile("(?:0|-?[1-9][0-9]*)\\z");

    /** Fixed-code failure; no caller query or data is included. */
    public static final class Error extends IllegalArgumentException {
        private final String code;
        private Error(String code) { super(code); this.code = code; }
        public String code() { return code; }
    }
    private static Error error(String code) { return new Error(code); }

    /** Immutable snapshot of the trusted sort/filter allowlists. */
    public static final class Schema {
        private final Map<String, String> sortFields;
        private final Map<String, String> filterFields;
        public Schema(Map<String, String> sortFields, Map<String, String> filterFields) {
            this.sortFields = fields(sortFields);
            this.filterFields = fields(filterFields);
            if (!"string".equals(this.sortFields.get("id"))) throw error("INVALID_LIST_SCHEMA");
            for (var entry : this.filterFields.entrySet()) {
                if (this.sortFields.containsKey(entry.getKey()) && !this.sortFields.get(entry.getKey()).equals(entry.getValue())) throw error("INVALID_LIST_SCHEMA");
            }
        }
        private static Map<String, String> fields(Map<String, String> source) {
            if (source == null || source.size() > 16) throw error("INVALID_LIST_SCHEMA");
            Map<String, String> copy = new HashMap<>();
            for (var entry : source.entrySet()) {
                if (entry.getKey() == null || !FIELD.matcher(entry.getKey()).matches() || !Set.of("string", "integer", "boolean").contains(entry.getValue() == null ? "" : entry.getValue())) throw error("INVALID_LIST_SCHEMA");
                copy.put(entry.getKey(), entry.getValue());
            }
            return Collections.unmodifiableMap(copy);
        }
        public Map<String, String> sortFields() { return sortFields; }
        public Map<String, String> filterFields() { return filterFields; }
    }

    /** Query instances are constructed only by the strict parser. */
    public static final class Query {
        private final int limit;
        private final int offset;
        private final String sort;
        private final boolean descending;
        private final Map<String, Object> filters;
        private final String raw;
        private Query(int limit, int offset, String sort, boolean descending, Map<String, Object> filters, String raw) {
            this.limit = limit; this.offset = offset; this.sort = sort; this.descending = descending;
            this.filters = Collections.unmodifiableMap(new HashMap<>(filters)); this.raw = raw;
        }
        public int limit() { return limit; }
        public int offset() { return offset; }
        public String sort() { return sort; }
        public boolean descending() { return descending; }
        public Map<String, Object> filters() { return filters; }
        public String raw() { return raw; }
    }

    public record PageResult(List<Map<String, Object>> items, int total, int limit, int offset, Integer nextOffset) {}

    private static boolean text(String value) {
        if (value == null) return false;
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (current < 32 || current == 127) return false;
            if (Character.isHighSurrogate(current)) {
                if (index + 1 >= value.length() || !Character.isLowSurrogate(value.charAt(++index))) return false;
            } else if (Character.isLowSurrogate(current)) return false;
        }
        return true;
    }
    private static boolean validValue(Object value, String kind) {
        return switch (kind) {
            case "string" -> value instanceof String string && text(string) && string.codePointCount(0, string.length()) > 0 && string.codePointCount(0, string.length()) <= 256 && string.getBytes(StandardCharsets.UTF_8).length <= 1024;
            case "boolean" -> value instanceof Boolean;
            case "integer" -> integer(value) != null;
            default -> false;
        };
    }
    private static Long integer(Object value) {
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) {
            long number = ((Number) value).longValue(); return number >= -SAFE && number <= SAFE ? number : null;
        }
        if (value instanceof Float || value instanceof Double) {
            double number = ((Number) value).doubleValue();
            return Double.isFinite(number) && Math.rint(number) == number && Math.abs(number) <= SAFE ? (long) number : null;
        }
        if (value instanceof BigInteger number) {
            return number.abs().compareTo(BigInteger.valueOf(SAFE)) <= 0 ? number.longValue() : null;
        }
        if (value instanceof BigDecimal number) {
            try { return integer(number.toBigIntegerExact()); } catch (ArithmeticException ignored) { return null; }
        }
        return null;
    }
    private static String decode(String value) {
        var bytes = new ByteArrayOutputStream();
        for (int index = 0; index < value.length();) {
            char current = value.charAt(index);
            if (current == '%') {
                if (index + 2 >= value.length()) throw error("INVALID_LIST_QUERY");
                int high = Character.digit(value.charAt(index + 1), 16), low = Character.digit(value.charAt(index + 2), 16);
                // Character.digit also accepts non-ASCII characters; escapes are ASCII only.
                if (high < 0 || low < 0 || value.charAt(index + 1) > 127 || value.charAt(index + 2) > 127) throw error("INVALID_LIST_QUERY");
                bytes.write(high * 16 + low); index += 3;
            } else if (current == '+') { bytes.write(' '); index++; }
            else {
                int point = value.codePointAt(index); byte[] encoded = new String(Character.toChars(point)).getBytes(StandardCharsets.UTF_8);
                bytes.writeBytes(encoded); index += Character.charCount(point);
            }
        }
        try {
            String result = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes.toByteArray())).toString();
            if (!text(result)) throw error("INVALID_LIST_QUERY"); return result;
        } catch (CharacterCodingException ignored) { throw error("INVALID_LIST_QUERY"); }
    }
    public static Query parseQuery(String raw, Schema schema) {
        if (schema == null) throw error("INVALID_LIST_SCHEMA");
        if (!text(raw) || raw.startsWith("?") || raw.getBytes(StandardCharsets.UTF_8).length > 2048) throw error("INVALID_LIST_QUERY");
        String[] pairs = raw.isEmpty() ? new String[0] : raw.split("&", -1);
        if (pairs.length > 16) throw error("INVALID_LIST_QUERY");
        Map<String, String> decoded = new LinkedHashMap<>();
        for (String pair : pairs) {
            int separator = pair.indexOf('='); if (separator < 0) throw error("INVALID_LIST_QUERY");
            String key = decode(pair.substring(0, separator)), value = decode(pair.substring(separator + 1));
            if (decoded.putIfAbsent(key, value) != null) throw error("INVALID_LIST_QUERY");
        }
        int limit = 20, offset = 0; String sort = "id"; boolean descending = false;
        Map<String, Object> filters = new HashMap<>();
        for (var entry : decoded.entrySet()) {
            String key = entry.getKey(), value = entry.getValue();
            if (key.equals("limit") || key.equals("offset")) {
                if (!UNSIGNED.matcher(value).matches() || value.length() > 5) throw error("INVALID_LIST_QUERY");
                int number = Integer.parseInt(value), bound = key.equals("limit") ? 100 : 10000;
                if (number > bound || (key.equals("limit") && number == 0)) throw error("INVALID_LIST_QUERY");
                if (key.equals("limit")) limit = number; else offset = number;
            } else if (key.equals("sort")) {
                descending = value.startsWith("-"); sort = descending ? value.substring(1) : value;
                if (!schema.sortFields.containsKey(sort)) throw error("INVALID_LIST_QUERY");
            } else if (key.startsWith("filter.") && schema.filterFields.containsKey(key.substring(7))) {
                String field = key.substring(7), kind = schema.filterFields.get(field); Object parsed;
                switch (kind) {
                    case "integer" -> {
                        if (!SIGNED.matcher(value).matches() || value.length() > 17) throw error("INVALID_LIST_QUERY");
                        long number = Long.parseLong(value); if (Math.abs(number) > SAFE) throw error("INVALID_LIST_QUERY"); parsed = number;
                    }
                    case "boolean" -> { if (!value.equals("true") && !value.equals("false")) throw error("INVALID_LIST_QUERY"); parsed = value.equals("true"); }
                    default -> { if (!validValue(value, kind)) throw error("INVALID_LIST_QUERY"); parsed = value; }
                }
                filters.put(field, parsed);
            } else throw error("INVALID_LIST_QUERY");
        }
        return new Query(limit, offset, sort, descending, filters, raw);
    }
    private static int scalarCompare(String left, String right) {
        var a = left.codePoints().iterator(); var b = right.codePoints().iterator();
        while (a.hasNext() && b.hasNext()) {
            int result = Integer.compare(a.nextInt(), b.nextInt()); if (result != 0) return result;
        }
        return Boolean.compare(a.hasNext(), b.hasNext());
    }
    private static int compare(Object left, Object right, String kind) {
        return switch (kind) {
            case "string" -> scalarCompare((String) left, (String) right);
            case "boolean" -> Boolean.compare((Boolean) left, (Boolean) right);
            default -> Long.compare(integer(left), integer(right));
        };
    }
    public static PageResult page(List<Map<String, Object>> rows, Query query, Schema schema) {
        if (schema == null) throw error("INVALID_LIST_SCHEMA");
        if (query == null) throw error("INVALID_LIST_QUERY");
        final Query selectedQuery = parseQuery(query.raw, schema);
        if (rows == null || rows.size() > 10000) throw error("INVALID_LIST_DATA");
        Set<String> ids = new HashSet<>();
        Map<String, String> fields = new HashMap<>(); fields.put(selectedQuery.sort, schema.sortFields.get(selectedQuery.sort));
        for (String field : selectedQuery.filters.keySet()) fields.put(field, schema.filterFields.get(field));
        for (var row : rows) {
            if (row == null || !(row.get("id") instanceof String id) || !ID.matcher(id).matches() || !ids.add(id)) throw error("INVALID_LIST_DATA");
            for (var field : fields.entrySet()) if (!validValue(row.get(field.getKey()), field.getValue())) throw error("INVALID_LIST_DATA");
        }
        List<Map<String, Object>> selected = new ArrayList<>();
        for (var row : rows) {
            boolean matched = true;
            for (var filter : selectedQuery.filters.entrySet()) if (compare(row.get(filter.getKey()), filter.getValue(), schema.filterFields.get(filter.getKey())) != 0) { matched = false; break; }
            if (matched) selected.add(row);
        }
        selected.sort((left, right) -> {
            int result = compare(left.get(selectedQuery.sort), right.get(selectedQuery.sort), schema.sortFields.get(selectedQuery.sort));
            if (result != 0) return selectedQuery.descending ? -result : result;
            return scalarCompare((String) left.get("id"), (String) right.get("id"));
        });
        int total = selected.size(), end = selectedQuery.offset + selectedQuery.limit;
        List<Map<String, Object>> items = selectedQuery.offset >= total ? List.of() : List.copyOf(selected.subList(selectedQuery.offset, Math.min(end, total)));
        return new PageResult(items, total, selectedQuery.limit, selectedQuery.offset, end < total ? end : null);
    }
}
