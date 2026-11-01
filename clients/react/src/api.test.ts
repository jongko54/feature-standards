import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ApiError, createAuthApi } from './api.ts';

const session = { user: { id: 'demo-user', email: 'demo@example.com' }, csrfToken: 'a-test-csrf-token' };

test('initial session lookup treats an unauthenticated response as signed out', async () => {
  const api = createAuthApi(async () => Response.json({ error: { code: 'UNAUTHENTICATED' } }, { status: 401 }));
  assert.equal(await api.me(), null);
});

test('network failure remains distinguishable from signed out', async () => {
  const api = createAuthApi(async () => { throw new TypeError('network unavailable'); });
  await assert.rejects(api.me(), TypeError);
});

test('login sends the exact contract without changing the password', async () => {
  const api = createAuthApi(async (url, options) => {
    assert.equal(url, '/auth/login');
    assert.equal(options?.method, 'POST');
    assert.equal(options?.credentials, 'same-origin');
    assert.equal(options?.cache, 'no-store');
    assert.equal(new Headers(options?.headers).get('Content-Type'), 'application/json');
    assert.deepEqual(JSON.parse(String(options?.body)), { email: 'DEMO@example.com', password: ' secret ' });
    return Response.json(session);
  });
  assert.deepEqual(await api.login('DEMO@example.com', ' secret '), session);
});

test('rate limiting preserves a bounded retry time for the UI', async () => {
  const api = createAuthApi(async () => Response.json(
    { error: { code: 'RATE_LIMITED', message: 'internal wording' } },
    { status: 429, headers: { 'Retry-After': '15' } },
  ));
  await assert.rejects(api.login('demo@example.com', 'wrong'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.status, 429);
    assert.equal(error.retryAfter, 15);
    return true;
  });
});

test('logout sends CSRF and accepts an empty 204 response', async () => {
  const api = createAuthApi(async (url, options) => {
    assert.equal(url, '/auth/logout');
    assert.equal(options?.method, 'POST');
    assert.equal(new Headers(options?.headers).get('X-CSRF-Token'), session.csrfToken);
    assert.equal(options?.credentials, 'same-origin');
    return new Response(null, { status: 204 });
  });
  assert.equal(await api.logout(session.csrfToken), undefined);
});

test('failed logout rejects instead of reporting a destroyed session', async () => {
  const api = createAuthApi(async () => Response.json({ error: { code: 'CSRF_INVALID' } }, { status: 403 }));
  await assert.rejects(api.logout('invalid'), (error: unknown) => error instanceof ApiError && error.code === 'CSRF_INVALID');
});

test('unexpected or malformed successful payloads are rejected', async () => {
  const api = createAuthApi(async () => Response.json({ user: { id: 42 } }));
  await assert.rejects(api.me(), (error: unknown) => error instanceof ApiError && error.code === 'INVALID_RESPONSE');
});
