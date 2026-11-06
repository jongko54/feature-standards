# Listing: offset-list-v1

Status: experimental source contract, version 1. All requirements below are normative.


- Strict raw query input, no initial `?`. Maximum 2048 UTF-8 bytes and 16 `&`-separated pairs. Standard form encoding (`+` means space), exactly one decoded value per key. Reject malformed percent escapes, invalid UTF-8/surrogates, ASCII control characters (U+0000..U+001F and U+007F), duplicate/unknown keys, empty pairs or missing `=`. Percent-decode before key duplicate/allowlist checks.
- `limit` default 20, range 1..100; `offset` default 0, range 0..10000. Canonical ASCII decimal only: 0 or a nonzero leading digit followed by digits. Empty values, signs, whitespace, leading zeros and overflow reject. `limit=0` rejects.
- `sort` is one schema-allowlisted field, optionally prefixed with `-`; default `id`. No comma expressions. IDs use the identifier grammar above, are unique, and always break non-ID sort ties ascending, including for descending primary sort.
- `filter.<field>` supports exact equality on server-allowlisted fields only. Schema is `{sortFields:{field:type},filterFields:{field:type}}`, types `string`, `integer`, `boolean`. `id` must be sortable string. At most 16 fields per map, field grammar `[a-z][a-z0-9_]{0,31}`; overlapping map entries must agree. Invalid schema is INVALID_LIST_SCHEMA.
- Integer filters use canonical signed decimal (no plus, leading zeros, or -0), within JavaScript safe integer bounds +/-9007199254740991. Boolean filters are exactly true/false. String filters are nonempty valid Unicode, at most 256 Unicode scalars and 1024 UTF-8 bytes, with no ASCII control characters. Equality does not case-fold or normalize Unicode.
- Reusable page helper accepts a materialized collection of maps/objects, at most 10000 rows. Every row needs a unique valid string id. Referenced sort/filter values must match declared types and bounds; missing/null/invalid referenced values are INVALID_LIST_DATA. Other record fields are passed through unchanged.
- String sorting compares Unicode scalar values, not locale or UTF-16 code units. Integer and boolean ordering are natural, false before true. Filter, then stable ordering, then slicing. Return `{items,total,limit,offset,nextOffset}`; nextOffset is null at the end. Out-of-range offset returns an empty page, unchanged filtered total, and null nextOffset.
- Query failures are INVALID_LIST_QUERY (HTTP 400), trusted schema/data failures are generic HTTP 500 with their fixed code and no raw input echoed. Native core errors expose only those codes.
- Callers apply tenant/authorization visibility before invoking page helper. No SQL interpolation, database adapter, cursor encoding, cross-request snapshot guarantee, or streaming/unbounded collection claim. AIP-158 is a reference; this strict offset profile does not claim AIP conformance.


Integral JSON numbers such as `1.0` are valid integer row values when mathematically integral and within the safe range; booleans are not integers. Schema validation precedes query parsing. Validate all referenced row values before filtering, even in rows that would not match. The page helper revalidates parsed query fields at its public boundary.

## HTTP composition

The Python consumer exposes `GET /api/documents`. It authenticates, loads current membership, checks documents:list, restricts rows using documents:read, then parses the raw ASGI query string and applies the page helper. Never compute totals on the unscoped collection. Its allowlist is id/name/score/active for sorting and name/score/active for filters. A rejected query returns 400 INVALID_LIST_QUERY. Schema/data failures return 500 with the appropriate fixed code. Responses are no-store.

Offset pagination can shift under concurrent writes; this profile provides deterministic ordering for a supplied materialized collection, not a cross-request snapshot or an efficient database adapter.

## Executable contract

`scenarios.json` is consumed by every native implementation. Run `python3 tools/check_core_features.py --feature listing --stack all`. See [composition guide](../../docs/core-standards.md).
