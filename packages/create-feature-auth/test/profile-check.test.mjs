import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createCheckEnvironment, validateOwnedDatabaseURL, validateTestDatabaseURL } from '../src/check-fixture.mjs';
import { runProject } from '../src/project.mjs';

test('database profiles refuse a missing dedicated test URL instead of silently checking memory', () => {
  for (const profile of ['browser-session-v2', 'browser-session-v3']) {
    assert.throws(() => createCheckEnvironment({ profile }, 'http://127.0.0.1:18000', {
      AUTH_DATABASE_URL: 'postgresql://production.example/customer_data',
    }), /test-database-url-required/);
  }
});

test('memory profile ignores inherited production auth settings', () => {
  const fixture = createCheckEnvironment({ profile: 'browser-session-v1' }, 'http://127.0.0.1:18000', {
    AUTH_STORE: 'postgres', AUTH_ACCOUNT_LIFECYCLE: 'true', AUTH_DATABASE_URL: 'postgresql://production.example/customer_data',
  });
  assert.equal(fixture.AUTH_STORE, 'memory');
  assert.equal(fixture.AUTH_ACCOUNT_LIFECYCLE, 'false');
  assert.equal(fixture.AUTH_DATABASE_URL, undefined);
});

test('database profiles select PostgreSQL and v3 capability without exposing the base DB as runtime storage', () => {
  const url = 'postgresql://fixture@localhost:18001/feature_standards_test_base?sslmode=disable';
  for (const profile of ['browser-session-v2', 'browser-session-v3']) {
    const fixture = createCheckEnvironment({ profile }, 'http://127.0.0.1:18000', { FEATURE_STANDARDS_TEST_DATABASE_URL: url, AUTH_DATABASE_URL: 'do-not-use' });
    assert.equal(fixture.AUTH_STORE, 'postgres');
    assert.equal(fixture.AUTH_ACCOUNT_LIFECYCLE, String(profile === 'browser-session-v3'));
    assert.equal(fixture.AUTH_DATABASE_URL, undefined);
    assert.equal(fixture.FEATURE_STANDARDS_TEST_DATABASE_URL, undefined);
  }
});

test('test database routing is restricted to explicit loopback test databases with no libpq overrides', () => {
  assert.equal(validateTestDatabaseURL('postgres://fixture@localhost:18001/feature_standards_test_base'), 'postgresql://fixture@127.0.0.1:18001/feature_standards_test_base?sslmode=disable');
  assert.equal(validateTestDatabaseURL('postgresql://fixture@[::1]:18001/feature_standards_test_base?sslmode=disable'), 'postgresql://fixture@[::1]:18001/feature_standards_test_base?sslmode=disable');
  for (const url of [
    'postgresql://127.0.0.1/feature_standards_test_base',
    'postgresql://remote.example:18001/feature_standards_test_base',
    'postgresql://127.0.0.1:18001/customer_data',
    'postgresql://127.0.0.1:18001/feature_standards_test_base?host=remote.example',
    'postgresql://127.0.0.1:18001/feature_standards_test_base?sslmode=require',
    'postgresql://127.0.0.1:18001/feature_standards_test_base?sslmode=disable&sslmode=disable',
    'postgresql://127.0.0.1:18001/feature_standards_test_base#fragment',
    'postgresql://127.0.0.1:18001/feature_standards_test_base\n',
    'postgresql://fixture:%FF@127.0.0.1:18001/feature_standards_test_base',
    'postgresql://fixture%ZZ@127.0.0.1:18001/feature_standards_test_base',
  ]) assert.throws(() => validateTestDatabaseURL(url), /unsafe-test-database-url/);
  assert.throws(() => validateTestDatabaseURL('postgresql://127.0.0.1:18001/feature_standards_test_base', { PGHOST: 'remote.example' }), /unsafe-test-database-url/);
});

test('a database check refuses absent test setup before building or creating app artifacts', async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), 'feature-auth-check-guard-')));
  const inherited = process.env.FEATURE_STANDARDS_TEST_DATABASE_URL;
  try {
    delete process.env.FEATURE_STANDARDS_TEST_DATABASE_URL;
    writeFileSync(join(directory, 'feature-auth.json'), JSON.stringify({ stack: 'python', profile: 'browser-session-v3', source: '.', checkProtocolVersion: 1 }));
    await assert.rejects(runProject('check', directory), /test-database-url-required/);
    assert.equal(existsSync(join(directory, '.venv')), false);
    assert.equal(existsSync(join(directory, '.feature-auth')), false);
  } finally {
    if (inherited === undefined) delete process.env.FEATURE_STANDARDS_TEST_DATABASE_URL;
    else process.env.FEATURE_STANDARDS_TEST_DATABASE_URL = inherited;
    rmSync(directory, { recursive: true, force: true });
  }
});

test('owned fixture credentials accept equivalent percent encodings without weakening database ownership', () => {
  const config = { stack: 'python', profile: 'browser-session-v3' };
  const name = 'feature_standards_test_generated_python_v3_123456abcdef';
  const base = validateTestDatabaseURL('postgresql://fixture!:synthetic!%2f%3a%40@localhost:18001/feature_standards_test_base');
  const ready = `postgresql://fixture%21:synthetic%21%2F%3A%40@127.0.0.1:18001/${name}?sslmode=disable`;
  assert.equal(validateOwnedDatabaseURL(ready, base, config), ready);
  for (const invalid of [
    ready.replace(':18001/', ':18002/'),
    ready.replace('fixture%21:', 'different:'),
    ready.replace('synthetic%21', 'different%21'),
    ready.replace(name, 'feature_standards_test_base'),
    ready.replace('generated_python_v3', 'generated_go_v3'),
  ]) assert.throws(() => validateOwnedDatabaseURL(invalid, base, config), /check-database-isolation-failed/);
});
