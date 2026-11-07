"""Optional postgres-list-v1 reader, independent of materialized offset v1.

The caller supplies an exclusively owned idle connection, trusted schema and
visibility derived from current server membership/policy. No migration or
membership lookup happens here. The psycopg driver is loaded only by page().
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .listing import ListingError, ListingSchema, _valid_value, parse_query

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z", re.ASCII)
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z", re.ASCII)
_SAFE = 9007199254740991


def _identifier(value):
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class VisibilityScope:
    """Require an explicit owner, or deliberate None for tenant-wide access."""

    tenant_id: str
    owner_id: str | None

    def __post_init__(self):
        if not isinstance(self.tenant_id, str) or not _SUBJECT.fullmatch(
            self.tenant_id
        ):
            raise ListingError("INVALID_LIST_SCOPE")
        if self.owner_id is not None and (
            not isinstance(self.owner_id, str) or not _SUBJECT.fullmatch(self.owner_id)
        ):
            raise ListingError("INVALID_LIST_SCOPE")


@dataclass(frozen=True, slots=True, init=False)
class PostgresListing:
    """Copy a trusted allowlist; fetch only scoped rows through bound queries."""

    schema: ListingSchema
    table: tuple[str, str]
    columns: Mapping
    tenant_column: str
    owner_column: str

    def __init__(self, *, schema, table, columns, tenant_column, owner_column):
        if not isinstance(schema, ListingSchema):
            raise ListingError("INVALID_LIST_SCHEMA")
        fields = set(schema.sort_fields) | set(schema.filter_fields)
        if (
            not isinstance(table, tuple)
            or len(table) != 2
            or not all(_identifier(part) for part in table)
            or not isinstance(columns, Mapping)
            or set(columns) != fields
            or not all(_identifier(column) for column in columns.values())
            or len(set(columns.values())) != len(columns)
            or not _identifier(tenant_column)
            or not _identifier(owner_column)
        ):
            raise ListingError("INVALID_LIST_SCHEMA")
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "table", tuple(table))
        object.__setattr__(self, "columns", MappingProxyType(dict(columns)))
        object.__setattr__(self, "tenant_column", tenant_column)
        object.__setattr__(self, "owner_column", owner_column)

    def page(self, connection, raw_query, scope):
        """Read one consistent page without taking ownership of the connection."""
        if not isinstance(scope, VisibilityScope):
            raise ListingError("INVALID_LIST_SCOPE")
        # Frozen dataclasses are a programming aid, not a trust-boundary bypass.
        scope = VisibilityScope(scope.tenant_id, scope.owner_id)
        query = parse_query(raw_query, self.schema)
        try:
            import psycopg
            from psycopg import sql
            from psycopg.pq import TransactionStatus
            from psycopg.rows import dict_row
        except ImportError:
            raise ListingError("LISTING_UNAVAILABLE") from None
        if not isinstance(connection, psycopg.Connection):
            raise ListingError("INVALID_LIST_TRANSACTION")
        if connection.closed:
            raise ListingError("LISTING_UNAVAILABLE")
        if connection.info.transaction_status != TransactionStatus.IDLE:
            raise ListingError("INVALID_LIST_TRANSACTION")
        if connection.info.parameter_status("server_encoding") != "UTF8":
            raise ListingError("INVALID_LIST_SCHEMA")

        def field(name, kind):
            identifier = sql.Identifier(self.columns[name])
            return (
                sql.SQL('{} COLLATE "C"').format(identifier)
                if kind == "string"
                else identifier
            )

        terms = [
            sql.SQL('{} COLLATE "C" = %s').format(sql.Identifier(self.tenant_column))
        ]
        parameters = [scope.tenant_id]
        if scope.owner_id is not None:
            terms.append(
                sql.SQL('{} COLLATE "C" = %s').format(sql.Identifier(self.owner_column))
            )
            parameters.append(scope.owner_id)
        for name, value in query.filters.items():
            terms.append(
                sql.SQL("{} = %s").format(field(name, self.schema.filter_fields[name]))
            )
            parameters.append(value)
        predicate = sql.SQL(" AND ").join(terms)
        relation = sql.Identifier(*self.table)
        count = sql.SQL("SELECT COUNT(*) AS total FROM {} WHERE {}").format(
            relation, predicate
        )
        direction = sql.SQL("DESC" if query.descending else "ASC")
        ordering = sql.SQL("{} {}").format(
            field(query.sort, self.schema.sort_fields[query.sort]), direction
        )
        if query.sort != "id":
            ordering += sql.SQL(", {} ASC").format(field("id", "string"))
        projection = sql.SQL(", ").join(
            sql.SQL("{} AS {}").format(sql.Identifier(column), sql.Identifier(name))
            for name, column in self.columns.items()
        )
        selected = sql.SQL(
            "SELECT {} FROM {} WHERE {} ORDER BY {} LIMIT %s OFFSET %s"
        ).format(
            projection,
            relation,
            predicate,
            ordering,
        )
        try:
            with (
                connection.transaction(),
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                cursor.execute(count, parameters)
                total = cursor.fetchone()["total"]
                cursor.execute(selected, [*parameters, query.limit, query.offset])
                rows = cursor.fetchall()
                self._validate_result(total, rows)
        except psycopg.Error:
            raise ListingError("LISTING_UNAVAILABLE") from None
        end = query.offset + query.limit
        return {
            "items": rows,
            "total": total,
            "limit": query.limit,
            "offset": query.offset,
            "nextOffset": end if end < total and end <= 10000 else None,
        }

    def _validate_result(self, total, rows):
        kinds = {**self.schema.sort_fields, **self.schema.filter_fields}
        if type(total) is not int or not 0 <= total <= _SAFE:
            raise ListingError("INVALID_LIST_DATA")
        seen = set()
        for row in rows:
            identifier = row.get("id")
            if (
                not isinstance(identifier, str)
                or not _SUBJECT.fullmatch(identifier)
                or identifier in seen
                or any(
                    not _valid_value(row.get(name), kind)
                    for name, kind in kinds.items()
                )
            ):
                raise ListingError("INVALID_LIST_DATA")
            seen.add(identifier)
