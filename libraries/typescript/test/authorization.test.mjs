import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { AuthorizationError, Grant, Policy, Principal, Resource } from '../src/authorization.mjs';

const vectors = JSON.parse(readFileSync(new URL('../../../features/authorization/scenarios.json', import.meta.url)));
for (const c of vectors.cases) test(`authorization vector: ${c.id}`, () => {
  const grants = c.grants.map(g => new Grant(g.role, g.permission, g.scope));
  if (c.expected.error) {
    assert.throws(() => new Policy(grants), error => error instanceof AuthorizationError && error.code === c.expected.error);
    return;
  }
  const principal = c.principal === null ? null : new Principal(c.principal.subjectId, c.principal.tenantId, c.principal.roles);
  const result = new Policy(grants).decide(principal, c.permission, new Resource(c.resource.tenantId, c.resource.ownerId));
  assert.deepEqual(result, c.expected);
});
test('policy and principal snapshot caller-owned arrays', () => {
  const grants = [new Grant('viewer', 'documents:read', 'tenant')];
  const roles = ['viewer'];
  const principal = new Principal('alice', 'tenant-a', roles);
  const policy = new Policy(grants);
  grants.length = 0; roles.length = 0;
  assert.equal(policy.decide(principal, 'documents:read', new Resource('tenant-a')).allowed, true);
  assert.throws(() => principal.roles.push('admin'), TypeError);
  assert.throws(() => { policy.grants = []; }, TypeError);
});
test('malformed runtime values fail closed', () => {
  const policy = new Policy([new Grant('viewer', 'documents:read', 'tenant')]);
  for (const principal of [undefined, {}, new Principal('alice', 'tenant-a', 'viewer'), new Principal('alice', 'tenant-a', [null])]) {
    assert.deepEqual(policy.decide(principal, 'documents:read', new Resource('tenant-a')), {allowed:false,code:'FORBIDDEN'});
  }
  for (const grants of [null, {}, Array(1), [null], [new Grant('viewer', 'documents:read\n', 'tenant')]]) {
    assert.throws(() => new Policy(grants), AuthorizationError);
  }
});
