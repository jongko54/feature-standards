/** Source-only offset-list-v1. Apply server authorization before pagination. */
export type ListingFieldType = 'string' | 'integer' | 'boolean';
export interface ListingSchemaInput {
  sortFields: Readonly<Record<string, ListingFieldType>>;
  filterFields: Readonly<Record<string, ListingFieldType>>;
}
export interface ListingSchema extends ListingSchemaInput {}
export interface ListQuery {
  readonly limit: number;
  readonly offset: number;
  readonly sort: string;
  readonly descending: boolean;
  readonly filters: Readonly<Record<string, string | number | boolean>>;
  readonly raw: string;
}
export interface ListPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  nextOffset: number | null;
}
export class ListingError extends Error {
  readonly code: 'INVALID_LIST_SCHEMA' | 'INVALID_LIST_QUERY' | 'INVALID_LIST_DATA';
  constructor(code: ListingError['code']);
}
export function createListingSchema(input: ListingSchemaInput): ListingSchema;
export function parseListQuery(raw: string, schema: ListingSchema): ListQuery;
export function listPage<T extends Record<string, unknown>>(rows: readonly T[], query: ListQuery, schema: ListingSchema): ListPage<T>;
