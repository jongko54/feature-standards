import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { request as httpRequest } from 'node:http';
import { createServer } from 'node:net';
import { CORE_CHECK_PROTOCOL_VERSION, CORE_FEATURES, CORE_PROFILES, CORE_REQUIRED_CHECKS } from './core-protocol.mjs';
import { stop, stopAndWait } from './core-process.mjs';

const PASSWORD = 'correct-horse-battery-staple';
const ALPHA = { id: 'own-a', name: 'Alpha', score: 2, active: true };
const BETA = { id: 'own-b', name: 'Beta', score: 2, active: false };

async function freePort() {
  const listener = createServer();
  await new Promise((resolveListen, reject) => { listener.once('error', reject); listener.listen(0, '127.0.0.1', resolveListen); });
  const port = listener.address().port;
  await new Promise((resolveClose, reject) => listener.close(error => error ? reject(error) : resolveClose()));
  return port;
}

/** Direct loopback HTTP: no redirects, proxy configuration, browser cookies or DNS. */
export function requestJson(base, path, { method = 'GET', origin = base, headers = {}, body } = {}) {
  const address = new URL(base);
  if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' || !address.port || address.username || address.password || address.pathname !== '/' || address.search || address.hash || !path.startsWith('/')) throw new Error('unsafe-core-check-address');
  const payload = body === undefined ? undefined : JSON.stringify(body);
  return new Promise((resolveRequest, reject) => {
    const request = httpRequest({ hostname: '127.0.0.1', port: address.port, path, method,
      headers: { ...(origin === null ? {} : { Origin: origin }), ...(payload === undefined ? {} : { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) }), ...headers } }, response => {
      let output = '';
      response.setEncoding('utf8');
      response.on('data', chunk => {
        output += chunk;
        if (output.length > 1024 * 1024) response.destroy(new Error('core-check-response-too-large'));
      });
      response.once('error', () => reject(new Error('core-check-response-failed')));
      response.once('end', () => {
        let value;
        try { value = output ? JSON.parse(output) : undefined; }
        catch { reject(new Error('core-check-response-not-json')); return; }
        resolveRequest({ status: response.statusCode, headers: response.headers, value });
      });
    });
    request.setTimeout(3000, () => request.destroy(new Error('core-check-request-timeout')));
    request.once('error', () => reject(new Error('core-check-request-failed')));
    if (payload !== undefined) request.write(payload);
    request.end();
  });
}

function expect(result, status, label) {
  assert.equal(result.status, status, 'core-check-' + label);
  return result;
}

function error(result, status, code) {
  expect(result, status, code);
  assert.equal(result.value?.error?.code, code, 'core-check-error-code');
  assert.equal(result.headers['cache-control'], 'no-store', 'core-check-error-cache');
  assert.equal(result.headers['x-content-type-options'], 'nosniff', 'core-check-error-nosniff');
  return result;
}

function client(base, origin = base) {
  const request = (path, options = {}) => requestJson(base, path, { origin, ...options });
  const post = (path, body, headers = {}, override = {}) => request(path, { method: 'POST', body, headers, ...override });
  const login = async (email = 'demo@example.com', secure = false) => {
    const result = expect(await post('/auth/login', { email, password: PASSWORD }), 200, 'login');
    const cookies = result.headers['set-cookie'];
    assert.ok(Array.isArray(cookies) && cookies.length === 1, 'core-check-session-cookie');
    const cookie = cookies[0].split(';', 1)[0];
    assert.match(cookie, /^fs_session=[A-Za-z0-9_-]{43}$/);
    assert.match(cookies[0], /;\s*HttpOnly(?:;|$)/i);
    assert.equal(/;\s*Secure(?:;|$)/i.test(cookies[0]), secure, 'core-check-secure-cookie');
    assert.equal(result.value?.user?.email, email, 'core-check-login-email');
    assert.equal(typeof result.value?.user?.id, 'string');
    assert.equal(typeof result.value?.csrfToken, 'string');
    assert.ok(result.value.csrfToken.length > 0);
    return { ...result.value, cookie };
  };
  const profile = async session => {
    const result = expect(await request('/api/profile', { headers: { Cookie: session.cookie } }), 200, 'profile');
    assert.deepEqual(result.value, { user: session.user }, 'core-check-shared-session-identity');
    assert.equal(result.headers['cache-control'], 'no-store');
    assert.equal(result.headers['x-content-type-options'], 'nosniff');
    return result;
  };
  return { request, post, login, profile };
}

export async function checkCore(config, environment, hooks) {
  if (config.coreCheckProtocolVersion !== CORE_CHECK_PROTOCOL_VERSION) throw new Error('unsupported-core-check-protocol');
  const checks = [];
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const demoEnvironment = hooks.coreEnvironment('check', environment, base);
  const normalEnvironment = hooks.coreEnvironment('normal-check', environment, base);
  let child;
  let interrupted = false;
  const interrupt = () => { interrupted = true; stop(child); };
  const alive = () => {
    if (interrupted) throw new Error('core-check-interrupted');
    if (!child || child.exitCode !== null || child.signalCode !== null) throw new Error('core-check-server-exited');
  };
  const stopServer = async () => { const current = child; child = undefined; await stopAndWait(current); };
  const startServer = async runtime => {
    if (interrupted) throw new Error('core-check-interrupted');
    const [program, args] = hooks.startCommand(config, runtime);
    child = spawn(program, args, { cwd: config.directory, env: runtime, stdio: ['ignore', 'ignore', 'ignore'], detached: process.platform !== 'win32' });
    let launchError = false;
    child.once('error', () => { launchError = true; });
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      alive();
      if (launchError) throw new Error('core-check-server-unavailable');
      try {
        const health = await requestJson(base, '/healthz', { origin: runtime.AUTH_ALLOWED_ORIGIN });
        if (health.status === 200) {
          assert.equal(health.value?.profile, CORE_PROFILES.auth, 'core-check-selected-profile');
          alive();
          return;
        }
      } catch (failure) {
        if (failure.code === 'ERR_ASSERTION') throw failure;
      }
      await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
    }
    throw new Error('core-check-server-timeout');
  };
  process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);
  let origins;
  try {
    await hooks.build(config, demoEnvironment);
    if (interrupted) throw new Error('core-check-interrupted');
    origins = await hooks.dependencyOrigins(config, demoEnvironment);
    for (const name of ['auth', 'core']) {
      assert.equal(origins[name]?.kind, 'source'); assert.equal(origins[name]?.verified, true);
      assert.equal(origins[name]?.expectedPath, config.dependencies[name]); assert.equal(origins[name]?.resolvedPath, config.dependencies[name]);
    }
    checks.push('actual-sdk-dependency-origins');

    await startServer(normalEnvironment);
    const normal = client(base, normalEnvironment.AUTH_ALLOWED_ORIGIN);
    const normalSession = await normal.login('core-starter@example.com', true);
    await normal.profile(normalSession);
    for (const path of ['/api/documents', '/api/documents/own-a']) error(await normal.request(path, { headers: { Cookie: normalSession.cookie } }), 403, 'FORBIDDEN');
    alive();
    checks.push('normal-start-denies-sample-access');
    await stopServer();

    await startServer(demoEnvironment);
    const { request, post, login, profile } = client(base);
    checks.push('selected-profile-health');
    for (const path of ['/api/profile', '/api/documents', '/api/documents/own-a']) {
      error(await request(path), 401, 'UNAUTHENTICATED');
      error(await request(path, { headers: { Cookie: 'fs_session=forged-core-cookie' } }), 401, 'UNAUTHENTICATED');
    }
    checks.push('anonymous-and-forged-protected-access');
    const first = await login(); const second = await login();
    assert.equal(first.user.id, 'demo-user');
    await profile(first); await profile(second);
    checks.push('login-shared-protected-identity');
    assert.notEqual(first.cookie, second.cookie); assert.notEqual(first.csrfToken, second.csrfToken);
    checks.push('independent-sessions');

    error(await post('/auth/login', { email: 'demo@example.com', password: PASSWORD }, {}, { origin: null }), 403, 'ORIGIN_DENIED');
    error(await post('/auth/login', { email: 'demo@example.com', password: PASSWORD }, {}, { origin: 'https://wrong-origin.example' }), 403, 'ORIGIN_DENIED');
    for (const headers of [{ Cookie: first.cookie }, { Cookie: first.cookie, 'X-CSRF-Token': second.csrfToken }]) error(await post('/auth/logout', undefined, headers), 403, 'CSRF_INVALID');
    error(await post('/auth/logout', undefined, { Cookie: first.cookie, 'X-CSRF-Token': first.csrfToken }, { origin: 'https://wrong-origin.example' }), 403, 'ORIGIN_DENIED');
    await profile(first); await profile(second);
    checks.push('origin-and-csrf-rejection');

    const headers = { Cookie: first.cookie };
    assert.deepEqual(expect(await request('/api/documents/own-a', { headers }), 200, 'own-resource').value, ALPHA);
    for (const id of ['other-owner', 'other-tenant', 'missing']) error(await request('/api/documents/' + id, { headers }), 403, 'FORBIDDEN');
    const forged = { ...headers, 'X-Role': 'admin', 'X-Roles': 'editor', 'X-Tenant-Id': 'tenant-b', 'X-Subject-Id': 'other-user' };
    error(await request('/api/documents/other-owner', { headers: forged }), 403, 'FORBIDDEN');
    error(await request('/api/documents?role=admin', { headers: forged }), 400, 'INVALID_LIST_QUERY');
    checks.push('owner-and-tenant-isolation');

    const page = expect(await request('/api/documents?limit=1&sort=-score', { headers }), 200, 'list-visibility').value;
    assert.deepEqual(page, { items: [ALPHA], total: 2, limit: 1, offset: 0, nextOffset: 1 });
    checks.push('authorization-before-list-totals');
    assert.deepEqual(expect(await request('/api/documents?limit=1&offset=1&sort=-score', { headers }), 200, 'list-next-page').value, { items: [BETA], total: 2, limit: 1, offset: 1, nextOffset: null });
    assert.deepEqual(expect(await request('/api/documents?filter.active=false', { headers }), 200, 'typed-boolean-filter').value, { items: [BETA], total: 1, limit: 20, offset: 0, nextOffset: null });
    assert.deepEqual(expect(await request('/api/documents?filter.score=2&sort=-name&limit=1', { headers }), 200, 'typed-integer-filter').value, { items: [BETA], total: 2, limit: 1, offset: 0, nextOffset: 1 });
    assert.deepEqual(expect(await request('/api/documents?filter.name=Alpha', { headers }), 200, 'typed-string-filter').value, { items: [ALPHA], total: 1, limit: 20, offset: 0, nextOffset: null });
    assert.deepEqual(expect(await request('/api/documents?filter.active=false&offset=10000', { headers }), 200, 'empty-offset-page').value, { items: [], total: 1, limit: 20, offset: 10000, nextOffset: null });
    checks.push('typed-filter-sort-pagination');
    for (const query of ['limit=1&%6cimit=2', 'filter.name=%FF', 'filter.name=%ED%A0%80', 'sort=id%2Cname', 'limit=01', 'filter.score=-0', 'limit=1&', 'filter.name=%00']) error(await request('/api/documents?' + query, { headers }), 400, 'INVALID_LIST_QUERY');
    checks.push('strict-raw-query-errors');

    expect(await post('/auth/logout', undefined, { Cookie: first.cookie, 'X-CSRF-Token': first.csrfToken }), 204, 'logout');
    for (const path of ['/auth/me', '/api/profile', '/api/documents']) error(await request(path, { headers }), 401, 'UNAUTHENTICATED');
    await profile(second);
    checks.push('logout-revokes-copied-cookie');
    alive();
    assert.equal(checks.length, CORE_REQUIRED_CHECKS.length);
    assert.ok(CORE_REQUIRED_CHECKS.every(check => checks.includes(check)));
  } finally {
    process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    await stopServer();
  }
  return { schemaVersion: 1, template: 'core', coreCheckProtocolVersion: CORE_CHECK_PROTOCOL_VERSION,
    features: CORE_FEATURES, profiles: CORE_PROFILES, stack: config.stack, profile: CORE_PROFILES.auth,
    passed: true, checks: CORE_REQUIRED_CHECKS.filter(check => checks.includes(check)), database: { used: false, isolated: false }, dependencyOrigins: origins };
}
