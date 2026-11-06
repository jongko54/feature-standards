import {
  Grant, Policy, Principal, Resource,
  createListingSchema, parseListQuery, listPage,
  type Decision, type ListPage,
} from '../src/index.mjs';

const policy = new Policy([new Grant('viewer', 'documents:read', 'owner')]);
const decision: Decision = policy.decide(
  new Principal('user-1', 'tenant-a', ['viewer']),
  'documents:read', new Resource('tenant-a', 'user-1'),
);
const schema = createListingSchema({sortFields: {id: 'string', score: 'integer'}, filterFields: {score: 'integer'}});
const result: ListPage<{id: string; score: number}> = listPage(
  [{id: 'a', score: 1}], parseListQuery('sort=-score', schema), schema,
);
const allowed: boolean = decision.allowed;
const id: string | undefined = result.items[0]?.id;
void allowed;
void id;
// @ts-expect-error Only explicit tenant/owner grant scopes are part of rbac-v1.
new Grant('admin', '*', 'global');
// @ts-expect-error Unknown schema types must not compile.
createListingSchema({sortFields: {id: 'text'}, filterFields: {}});
// @ts-expect-error A record map, not a number, is a supported list row.
listPage([1], parseListQuery('', schema), schema);
