"""Strict offset-list-v1 parsing and bounded in-memory pagination.

Scope rows by tenant/authorization before calling :func:`page`. This module
operates on a bounded materialized list; it is not a database query builder.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cmp_to_key
from types import MappingProxyType
from urllib.parse import unquote_to_bytes

_FIELD = re.compile(r"[a-z][a-z0-9_]{0,31}\Z", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z", re.ASCII)
_UNSIGNED = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
_SIGNED = re.compile(r"(?:0|-?[1-9][0-9]*)\Z", re.ASCII)
_BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_SAFE = 9007199254740991


def _text(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        value.encode("utf-8", "strict")
        return True
    except UnicodeError:
        return False


def _valid_value(value, kind):
    if kind == "string":
        return (
            _text(value)
            and 0 < len(value) <= 256
            and len(value.encode("utf-8")) <= 1024
        )
    if kind == "boolean":
        return isinstance(value, bool)
    return (
        type(value) in (int, float)
        and abs(value) <= _SAFE
        and math.isfinite(value)
        and value == int(value)
    )


class ListingError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, init=False)
class ListingSchema:
    sort_fields: Mapping
    filter_fields: Mapping

    def __init__(self, sort_fields, filter_fields):
        for fields in (sort_fields, filter_fields):
            if (
                not isinstance(fields, Mapping)
                or len(fields) > 16
                or any(
                    not isinstance(k, str)
                    or not _FIELD.fullmatch(k)
                    or v not in ("string", "integer", "boolean")
                    for k, v in fields.items()
                )
            ):
                raise ListingError("INVALID_LIST_SCHEMA")
        if sort_fields.get("id") != "string" or any(
            k in sort_fields and sort_fields[k] != v for k, v in filter_fields.items()
        ):
            raise ListingError("INVALID_LIST_SCHEMA")
        object.__setattr__(self, "sort_fields", MappingProxyType(dict(sort_fields)))
        object.__setattr__(self, "filter_fields", MappingProxyType(dict(filter_fields)))


@dataclass(frozen=True, slots=True)
class ListQuery:
    limit: int
    offset: int
    sort: str
    descending: bool
    filters: Mapping
    raw: str


def _schema(schema):
    if not isinstance(schema, ListingSchema):
        raise ListingError("INVALID_LIST_SCHEMA")


def parse_query(raw_query, schema):
    _schema(schema)
    if (
        not _text(raw_query)
        or raw_query.startswith("?")
        or len(raw_query.encode("utf-8")) > 2048
    ):
        raise ListingError("INVALID_LIST_QUERY")
    pairs = raw_query.split("&") if raw_query else []
    if len(pairs) > 16:
        raise ListingError("INVALID_LIST_QUERY")
    decoded = {}
    for pair in pairs:
        if not pair or "=" not in pair or _BAD_ESCAPE.search(pair):
            raise ListingError("INVALID_LIST_QUERY")
        try:
            key, value = (
                unquote_to_bytes(part.replace("+", " ")).decode("utf-8", "strict")
                for part in pair.split("=", 1)
            )
        except (UnicodeError, ValueError):
            raise ListingError("INVALID_LIST_QUERY") from None
        if not _text(key) or not _text(value) or key in decoded:
            raise ListingError("INVALID_LIST_QUERY")
        decoded[key] = value
    limit, offset, sort, descending, filters = 20, 0, "id", False, {}
    for key, value in decoded.items():
        if key in ("limit", "offset"):
            bound = 100 if key == "limit" else 10000
            if (
                not _UNSIGNED.fullmatch(value)
                or len(value) > 5
                or int(value) > bound
                or (key == "limit" and value == "0")
            ):
                raise ListingError("INVALID_LIST_QUERY")
            if key == "limit":
                limit = int(value)
            else:
                offset = int(value)
        elif key == "sort":
            descending = value.startswith("-")
            sort = value[1:] if descending else value
            if sort not in schema.sort_fields:
                raise ListingError("INVALID_LIST_QUERY")
        elif key.startswith("filter.") and key[7:] in schema.filter_fields:
            field = key[7:]
            kind = schema.filter_fields[field]
            if kind == "integer":
                if (
                    not _SIGNED.fullmatch(value)
                    or len(value) > 17
                    or abs(int(value)) > _SAFE
                ):
                    raise ListingError("INVALID_LIST_QUERY")
                value = int(value)
            elif kind == "boolean":
                if value not in ("true", "false"):
                    raise ListingError("INVALID_LIST_QUERY")
                value = value == "true"
            elif not _valid_value(value, kind):
                raise ListingError("INVALID_LIST_QUERY")
            filters[field] = value
        else:
            raise ListingError("INVALID_LIST_QUERY")
    return ListQuery(
        limit, offset, sort, descending, MappingProxyType(filters), raw_query
    )


def page(rows, query, schema):
    _schema(schema)
    if not isinstance(query, ListQuery):
        raise ListingError("INVALID_LIST_QUERY")
    query = parse_query(query.raw, schema)
    if not isinstance(rows, (list, tuple)) or len(rows) > 10000:
        raise ListingError("INVALID_LIST_DATA")
    ids = set()
    fields = {
        query.sort: schema.sort_fields[query.sort],
        **{k: schema.filter_fields[k] for k in query.filters},
    }
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("id"), str)
            or not _ID.fullmatch(row["id"])
            or row["id"] in ids
        ):
            raise ListingError("INVALID_LIST_DATA")
        ids.add(row["id"])
        if any(
            not _valid_value(row.get(field), kind) for field, kind in fields.items()
        ):
            raise ListingError("INVALID_LIST_DATA")
    selected = [
        row
        for row in rows
        if all(row[k] == value for k, value in query.filters.items())
    ]

    def compare(left, right):
        a, b = left[query.sort], right[query.sort]
        primary = (a > b) - (a < b)
        if primary:
            return -primary if query.descending else primary
        return (left["id"] > right["id"]) - (left["id"] < right["id"])

    selected.sort(key=cmp_to_key(compare))
    total = len(selected)
    end = query.offset + query.limit
    return {
        "items": selected[query.offset : end],
        "total": total,
        "limit": query.limit,
        "offset": query.offset,
        "nextOffset": end if end < total else None,
    }
