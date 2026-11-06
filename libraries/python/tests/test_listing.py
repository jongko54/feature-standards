"""Native boundaries and the shared offset-list-v1 vectors."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from feature_standards.listing import (
    ListingError,
    ListingSchema,
    ListQuery,
    page,
    parse_query,
)


def schema():
    return ListingSchema(
        {"id": "string", "name": "string", "count": "integer", "active": "boolean"},
        {"name": "string", "count": "integer", "active": "boolean"},
    )


class ListingTests(unittest.TestCase):
    def test_shared_vectors(self):
        fixture = (
            Path(__file__).resolve().parents[3] / "features/listing/scenarios.json"
        )
        for case in json.loads(fixture.read_text())["cases"]:
            with self.subTest(case=case["id"]):

                def execute(case=case):
                    raw_schema = case["schema"]
                    selected = ListingSchema(
                        raw_schema["sortFields"], raw_schema["filterFields"]
                    )
                    return page(
                        case["items"], parse_query(case["query"], selected), selected
                    )

                if "error" in case["expected"]:
                    with self.assertRaises(ListingError) as caught:
                        execute()
                    self.assertEqual(caught.exception.code, case["expected"]["error"])
                else:
                    self.assertEqual(execute(), case["expected"])

    def test_defaults_and_stable_descending_ties(self):
        rows = [
            {"id": "b", "count": 2},
            {"id": "a", "count": 2},
            {"id": "c", "count": 1},
        ]
        result = page(rows, parse_query("sort=-count&limit=1", schema()), schema())
        self.assertEqual(
            result,
            {"items": [rows[1]], "total": 3, "limit": 1, "offset": 0, "nextOffset": 1},
        )
        self.assertEqual([r["id"] for r in rows], ["b", "a", "c"])

    def test_strict_raw_query(self):
        for raw in (
            "?limit=1",
            "limit=01",
            "limit=0",
            "offset=10001",
            "limit=1&%6cimit=2",
            "sort=id&",
            "sort",
            "filter.name=%FF",
            "filter.name=%ZZ",
            "filter.name=%00",
            "filter.count=-0",
            "filter.active=True",
            "sort=name,id",
            "filter.unknown=x",
            "&",
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"),
            ):
                parse_query(raw, schema())

    def test_form_decoding_types_and_scalar_order(self):
        rows = [
            {"id": "a", "name": "\U00010000", "count": 1.0, "active": False},
            {"id": "b", "name": "\ue000", "count": 1, "active": True},
        ]
        self.assertEqual(
            [
                r["id"]
                for r in page(rows, parse_query("sort=name", schema()), schema())[
                    "items"
                ]
            ],
            ["b", "a"],
        )
        self.assertEqual(
            page(
                rows,
                parse_query("filter.count=1&filter.active=false", schema()),
                schema(),
            )["items"],
            [rows[0]],
        )
        self.assertEqual(
            page(
                [{"id": "a", "name": "a b"}],
                parse_query("filter.name=a+b", schema()),
                schema(),
            )["total"],
            1,
        )

    def test_schema_snapshot_and_invalid_inputs(self):
        fields = {"id": "string"}
        frozen = ListingSchema(fields, {})
        fields["id"] = "integer"
        self.assertEqual(
            page([{"id": "a"}], parse_query("", frozen), frozen)["total"], 1
        )
        for sort, filters in (
            ({}, {}),
            ({"id": "integer"}, {}),
            ({"id": "string", "Name": "string"}, {}),
            ({"id": "string"}, {"id": "integer"}),
            ({"id": "string"}, {"x": "float"}),
        ):
            with self.assertRaisesRegex(ListingError, "^INVALID_LIST_SCHEMA$"):
                ListingSchema(sort, filters)

    def test_invalid_data_even_when_filtered_out(self):
        for rows, raw in (
            ([{"id": "a"}, {"id": "a"}], ""),
            ([{"id": "bad id"}], ""),
            ([{"id": "a", "count": True}], "sort=count"),
            ([{"id": "a", "count": 1.5}], "sort=count"),
            ([{"id": "a", "count": 9007199254740992}], "sort=count"),
            ([{"id": "a", "name": "\ud800"}], "sort=name"),
            ([{"id": "a"}], "filter.active=true"),
            ([{"id": str(i)} for i in range(10001)], ""),
        ):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ListingError, "^INVALID_LIST_DATA$"),
            ):
                page(rows, parse_query(raw, schema()), schema())

    def test_query_revalidated_against_current_schema(self):
        parsed = parse_query("sort=count", schema())
        only_id = ListingSchema({"id": "string"}, {})
        with self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"):
            page([{"id": "a", "count": 1}], parsed, only_id)
        forged = ListQuery(10001, 0, "count", False, {}, "limit=0")
        with self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"):
            page([], forged, schema())
        with self.assertRaisesRegex(ListingError, "^INVALID_LIST_DATA$"):
            page(
                [{"id": "a", "count": 1.5, "active": False}],
                parse_query("sort=count&filter.active=true", schema()),
                schema(),
            )

    def test_huge_native_integer_is_fixed_data_error(self):
        with self.assertRaisesRegex(ListingError, "^INVALID_LIST_DATA$"):
            page(
                [{"id": "a", "count": 10**10000}],
                parse_query("sort=count", schema()),
                schema(),
            )

    def test_bounds_and_empty_page(self):
        for raw in (
            "filter.name=" + "x" * 257,
            "filter.name=" + "x" * 2048,
            "&".join(f"x{i}=y" for i in range(17)),
            "filter.count=9007199254740992",
            "filter.count=+1",
        ):
            with self.assertRaisesRegex(ListingError, "^INVALID_LIST_QUERY$"):
                parse_query(raw, schema())
        result = page(
            [{"id": "a"}], parse_query("offset=10000&limit=100", schema()), schema()
        )
        self.assertEqual(
            result,
            {
                "items": [],
                "total": 1,
                "limit": 100,
                "offset": 10000,
                "nextOffset": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
