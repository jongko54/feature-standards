import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createListingSchema, parseListQuery, listPage } from '../src/listing.mjs';

const schema = () => createListingSchema({ sortFields: { id: 'string', name: 'string', count: 'integer', active: 'boolean' }, filterFields: { name: 'string', count: 'integer', active: 'boolean' } });
const run = (rows, raw, s = schema()) => listPage(rows, parseListQuery(raw, s), s);
test('scalar ordering and ascending ID ties for descending sort', () => {
  const rows = [{ id: 'b', count: 2 }, { id: 'a', count: 2 }, { id: 'c', count: 1 }];
  assert.deepEqual(run(rows, 'sort=-count&limit=1'), { items: [rows[1]], total: 3, limit: 1, offset: 0, nextOffset: 1 });
  assert.deepEqual(rows.map(r => r.id), ['b', 'a', 'c']);
  assert.deepEqual(run([{ id: 'a', name: '\u{10000}' }, { id: 'b', name: '\ue000' }], 'sort=name').items.map(r => r.id), ['b', 'a']);
});
test('strict parser rejects malformed bytes, duplicate decoded keys and bounds', () => {
  for (const raw of ['?limit=1', 'limit=01', 'limit=0', 'offset=10001', 'limit=1&%6cimit=2', 'sort=id&', 'sort', 'filter.name=%FF', 'filter.name=%ZZ', 'filter.name=%00', 'filter.count=-0', 'filter.active=True', 'sort=name,id', 'filter.unknown=x', '&', 'filter.name=\ud800', 'filter.name=' + 'x'.repeat(257), 'filter.count=9007199254740992']) {
    assert.throws(() => run([], raw), { message: 'INVALID_LIST_QUERY', code: 'INVALID_LIST_QUERY' });
  }
});
test('typed equality, empty pages and immutable schema snapshot', () => {
  assert.equal(run([{ id: 'a', name: 'a b', count: 1, active: false }], 'filter.name=a+b&filter.count=1&filter.active=false').total, 1);
  assert.deepEqual(run([{ id: 'a' }], 'offset=10000'), { items: [], total: 1, limit: 20, offset: 10000, nextOffset: null });
  const fields = { id: 'string' }; const s = createListingSchema({ sortFields: fields, filterFields: {} }); fields.id = 'integer';
  assert.equal(run([{ id: 'a' }], '', s).total, 1);
});
test('invalid schemas and bounded referenced data reject with fixed codes', () => {
  for (const s of [{ sortFields: {}, filterFields: {} }, { sortFields: { id: 'integer' }, filterFields: {} }, { sortFields: { id: 'string', Name: 'string' }, filterFields: {} }, { sortFields: { id: 'string' }, filterFields: { id: 'integer' } }]) assert.throws(() => createListingSchema(s), { message: 'INVALID_LIST_SCHEMA' });
  for (const [rows, raw] of [[[ { id: 'a' }, { id: 'a' } ], ''], [[{ id: 'bad id' }], ''], [[{ id: 'a', count: true }], 'sort=count'], [[{ id: 'a', count: NaN }], 'sort=count'], [[{ id: 'a', count: 9007199254740992 }], 'sort=count'], [[{ id: 'a', name: '\ud800' }], 'sort=name'], [[{ id: 'a' }], 'filter.active=false'], [Array.from({ length: 10001 }, (_, id) => ({ id: `${id}` })), '']]) assert.throws(() => run(rows, raw), { message: 'INVALID_LIST_DATA' });
});
test('shared listing vectors', () => {
  const { cases } = JSON.parse(readFileSync(new URL('../../../features/listing/scenarios.json', import.meta.url), 'utf8'));
  for (const c of cases) {
    const execute = () => { const s = createListingSchema(c.schema); return run(c.items, c.query, s); };
    if (c.expected.error) assert.throws(execute, { message: c.expected.error }, c.id);
    else assert.deepEqual(execute(), c.expected, c.id);
  }
});
