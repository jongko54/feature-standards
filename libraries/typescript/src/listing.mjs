/** Strict offset-list-v1 helpers. Scope rows on the server before pagination. */
const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const schemas = new WeakSet();
const queries = new WeakSet();
const fieldPattern = /^[a-z][a-z0-9_]{0,31}$/u;
const idPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/u;
const unsignedPattern = /^(?:0|[1-9][0-9]*)$/u;
const signedPattern = /^(?:0|-?[1-9][0-9]*)$/u;
// Compare the complete match: JavaScript's $ also matches before a final newline.
const matches = (value, pattern) => typeof value === 'string' && pattern.exec(value)?.[0] === value;
const own = (object, field) => Object.hasOwn(object, field);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const bytes = value => new TextEncoder().encode(value).length;

export class ListingError extends Error {
  constructor(code) { super(code); this.name = 'ListingError'; this.code = code; }
}
const fail = code => { throw new ListingError(code); };
function text(value) {
  if (typeof value !== 'string') return false;
  for (const char of value) {
    const point = char.codePointAt(0);
    if (point < 32 || point === 127 || (point >= 0xd800 && point <= 0xdfff)) return false;
  }
  return true;
}
function validValue(value, kind) {
  if (kind === 'string') return text(value) && [...value].length > 0 && [...value].length <= 256 && bytes(value) <= 1024;
  if (kind === 'boolean') return typeof value === 'boolean';
  return Number.isSafeInteger(value);
}
export function createListingSchema(input) {
  if (!object(input)) fail('INVALID_LIST_SCHEMA');
  const copies = [];
  for (const fields of [input.sortFields, input.filterFields]) {
    if (!object(fields) || Object.keys(fields).length > 16) fail('INVALID_LIST_SCHEMA');
    const copy = Object.create(null);
    for (const [field, kind] of Object.entries(fields)) {
      if (!matches(field, fieldPattern) || !['string', 'integer', 'boolean'].includes(kind)) fail('INVALID_LIST_SCHEMA');
      copy[field] = kind;
    }
    copies.push(Object.freeze(copy));
  }
  const [sortFields, filterFields] = copies;
  if (sortFields.id !== 'string') fail('INVALID_LIST_SCHEMA');
  for (const [field, kind] of Object.entries(filterFields)) if (own(sortFields, field) && sortFields[field] !== kind) fail('INVALID_LIST_SCHEMA');
  const schema = Object.freeze({ sortFields, filterFields });
  schemas.add(schema);
  return schema;
}
function checkSchema(schema) { if (!object(schema) || !schemas.has(schema)) fail('INVALID_LIST_SCHEMA'); }
export function parseListQuery(raw, schema) {
  checkSchema(schema);
  if (!text(raw) || raw.startsWith('?') || bytes(raw) > 2048) fail('INVALID_LIST_QUERY');
  const pairs = raw === '' ? [] : raw.split('&');
  if (pairs.length > 16) fail('INVALID_LIST_QUERY');
  const decoded = new Map();
  for (const pair of pairs) {
    const split = pair.indexOf('=');
    if (split < 0 || pair === '') fail('INVALID_LIST_QUERY');
    let key; let value;
    try {
      key = decodeURIComponent(pair.slice(0, split).replaceAll('+', ' '));
      value = decodeURIComponent(pair.slice(split + 1).replaceAll('+', ' '));
    } catch { fail('INVALID_LIST_QUERY'); }
    if (!text(key) || !text(value) || decoded.has(key)) fail('INVALID_LIST_QUERY');
    decoded.set(key, value);
  }
  let limit = 20; let offset = 0; let sort = 'id'; let descending = false;
  const filters = Object.create(null);
  for (const [key, value] of decoded) {
    if (key === 'limit' || key === 'offset') {
      const number = Number(value); const max = key === 'limit' ? 100 : 10000;
      if (!matches(value, unsignedPattern) || value.length > 5 || number > max || (key === 'limit' && number === 0)) fail('INVALID_LIST_QUERY');
      if (key === 'limit') limit = number; else offset = number;
    } else if (key === 'sort') {
      descending = value.startsWith('-'); sort = descending ? value.slice(1) : value;
      if (!own(schema.sortFields, sort)) fail('INVALID_LIST_QUERY');
    } else if (key.startsWith('filter.') && own(schema.filterFields, key.slice(7))) {
      const field = key.slice(7); const kind = schema.filterFields[field]; let parsed = value;
      if (kind === 'integer') {
        if (!matches(value, signedPattern) || value.length > 17 || !Number.isSafeInteger(Number(value))) fail('INVALID_LIST_QUERY');
        parsed = Number(value);
      } else if (kind === 'boolean') {
        if (value !== 'true' && value !== 'false') fail('INVALID_LIST_QUERY');
        parsed = value === 'true';
      } else if (!validValue(value, kind)) fail('INVALID_LIST_QUERY');
      filters[field] = parsed;
    } else fail('INVALID_LIST_QUERY');
  }
  const query = Object.freeze({ limit, offset, sort, descending, filters: Object.freeze(filters), raw });
  queries.add(query);
  return query;
}
function compareStrings(left, right) {
  const a = [...left]; const b = [...right];
  for (let index = 0; index < Math.min(a.length, b.length); index++) {
    const difference = a[index].codePointAt(0) - b[index].codePointAt(0);
    if (difference !== 0) return Math.sign(difference);
  }
  return Math.sign(a.length - b.length);
}
export function listPage(rows, query, schema) {
  checkSchema(schema);
  if (!object(query) || !queries.has(query)) fail('INVALID_LIST_QUERY');
  query = parseListQuery(query.raw, schema);
  if (!Array.isArray(rows) || rows.length > 10000) fail('INVALID_LIST_DATA');
  const fields = { [query.sort]: schema.sortFields[query.sort] };
  for (const field of Object.keys(query.filters)) fields[field] = schema.filterFields[field];
  const ids = new Set();
  for (const row of rows) {
    if (!object(row) || !own(row, 'id') || !matches(row.id, idPattern) || ids.has(row.id)) fail('INVALID_LIST_DATA');
    ids.add(row.id);
    for (const [field, kind] of Object.entries(fields)) if (!own(row, field) || !validValue(row[field], kind)) fail('INVALID_LIST_DATA');
  }
  const selected = rows.filter(row => Object.entries(query.filters).every(([field, value]) => row[field] === value));
  selected.sort((left, right) => {
    const a = left[query.sort]; const b = right[query.sort];
    const primary = typeof a === 'string' ? compareStrings(a, b) : (a > b ? 1 : a < b ? -1 : 0);
    if (primary !== 0) return query.descending ? -primary : primary;
    return compareStrings(left.id, right.id);
  });
  const total = selected.length; const end = query.offset + query.limit;
  return { items: selected.slice(query.offset, end), total, limit: query.limit, offset: query.offset, nextOffset: end < total ? end : null };
}
