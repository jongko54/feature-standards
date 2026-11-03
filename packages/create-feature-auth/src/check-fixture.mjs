import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

// The generated checker owns its synthetic environment, independent of app configuration.
export function validateTestDatabaseURL(value, environment = {}) {
  if (typeof value !== 'string' || !value) throw new Error('test-database-url-required: set FEATURE_STANDARDS_TEST_DATABASE_URL');
  try {
    if (/[\0-\x20\x7f]/.test(value)) throw new Error();
    const parsed = new URL(value);
    // Reject malformed credential escapes before comparing canonical userinfo.
    decodeURIComponent(parsed.username);
    decodeURIComponent(parsed.password);
    const name = decodeURIComponent(parsed.pathname.slice(1));
    const host = parsed.hostname.replace(/^\[|\]$/g, '');
    const query = [...parsed.searchParams];
    if (!['postgres:', 'postgresql:'].includes(parsed.protocol)
        || !/^feature_standards_test[A-Za-z0-9_]*$/.test(name)
        || !['localhost', '127.0.0.1', '::1'].includes(host)
        || !parsed.port || Number(parsed.port) < 1 || Number(parsed.port) > 65535
        || parsed.hash || (query.length && !(query.length === 1 && query[0][0] === 'sslmode' && query[0][1] === 'disable'))
        || Object.entries(environment).some(([key, current]) => key.startsWith('PG') && current)) {
      throw new Error();
    }
    parsed.protocol = 'postgresql:';
    parsed.hostname = host === '::1' ? '[::1]' : '127.0.0.1';
    parsed.pathname = '/' + name;
    parsed.search = '?sslmode=disable';
    return parsed.href;
  } catch {
    throw new Error('unsafe-test-database-url: use an explicit loopback feature_standards_test database and clear PG environment');
  }
}

export function createCheckEnvironment(config, base, environment) {
  if (!['browser-session-v1', 'browser-session-v2', 'browser-session-v3'].includes(config.profile)) throw new Error('unsupported-check-profile');
  const database = config.profile !== 'browser-session-v1';
  if (database) validateTestDatabaseURL(environment.FEATURE_STANDARDS_TEST_DATABASE_URL, environment);
  const fixture = { ...environment };
  for (const key of Object.keys(fixture)) if (key.startsWith('AUTH_')) delete fixture[key];
  delete fixture.FEATURE_STANDARDS_TEST_DATABASE_URL;
  Object.assign(fixture, {
    AUTH_STORE: database ? 'postgres' : 'memory',
    AUTH_ACCOUNT_LIFECYCLE: String(config.profile === 'browser-session-v3'), AUTH_DEMO: 'true',
    AUTH_HOST: '127.0.0.1', AUTH_PORT: new URL(base).port,
    AUTH_ALLOWED_ORIGIN: base, AUTH_COOKIE_SECURE: 'false',
    AUTH_USER_EMAIL: 'demo@example.com', AUTH_USER_PASSWORD: 'correct-horse-battery-staple',
    AUTH_SESSION_TTL_SECONDS: '1800', AUTH_RATE_LIMIT_MAX: '100', AUTH_RATE_LIMIT_WINDOW_SECONDS: '60',
  });
  return fixture;
}

export function validateOwnedDatabaseURL(value, base, config, environment = {}) {
  const url = validateTestDatabaseURL(value, environment);
  const created = new URL(url);
  const original = new URL(base);
  const expectedName = new RegExp('^/feature_standards_test_generated_' + config.stack + '_' + config.profile.slice(-2) + '_[a-f0-9]{12}$');
  if (!expectedName.test(created.pathname) || created.host !== original.host
      || decodeURIComponent(created.username) !== decodeURIComponent(original.username)
      || decodeURIComponent(created.password) !== decodeURIComponent(original.password)) {
    throw new Error('check-database-isolation-failed');
  }
  return url;
}

export async function startDatabaseFixture(config, environment) {
  const base = validateTestDatabaseURL(environment.FEATURE_STANDARDS_TEST_DATABASE_URL, environment);
  const helperEnvironment = { ...environment, FEATURE_STANDARDS_TEST_DATABASE_URL: base };
  delete helperEnvironment.UV_PROJECT_ENVIRONMENT;
  for (const key of Object.keys(helperEnvironment)) if (key.startsWith('AUTH_')) delete helperEnvironment[key];
  const child = spawn('uv', [
    'run', '--frozen', '--project', join(config.source, 'tools'), 'python',
    join(config.directory, 'check-db.py'), config.source, config.stack, config.profile,
  ], { env: helperEnvironment, stdio: ['pipe', 'pipe', 'ignore'], detached: process.platform !== 'win32' });
  let unavailable = false;
  let finished = false;
  const exited = new Promise(resolveExit => {
    child.once('exit', () => { finished = true; resolveExit(); });
    child.once('error', () => { unavailable = true; finished = true; resolveExit(); });
  });
  const reader = createInterface({ input: child.stdout, crlfDelay: Infinity });
  const lines = reader[Symbol.asyncIterator]();
  async function receive(timeout = 30000) {
    let timer;
    try {
      const line = await Promise.race([
        lines.next(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('check-database-fixture-timeout')), timeout); }),
      ]);
      if (line.done || unavailable || line.value.length > 16384) throw new Error('check-database-fixture-failed');
      const value = JSON.parse(line.value);
      if (!value || typeof value !== 'object' || value.error) throw new Error('check-database-fixture-failed');
      return value;
    } catch (error) {
      if (error.message === 'check-database-fixture-timeout') throw error;
      throw new Error('check-database-fixture-failed');
    } finally { clearTimeout(timer); }
  }
  let closed = false;
  const signal = kind => {
    if (!Number.isInteger(child.pid) || finished) return;
    try {
      if (process.platform === 'win32') child.kill(kind);
      else process.kill(-child.pid, kind);
    } catch (error) { if (error.code !== 'ESRCH') throw error; }
  };
  const waitForHelper = async () => {
    let timer;
    try { await Promise.race([exited, new Promise(resolveWait => { timer = setTimeout(resolveWait, 5000); })]); }
    finally { clearTimeout(timer); }
  };
  async function close(requireConfirmation = true) {
    if (closed) return;
    closed = true;
    let confirmed = false;
    try {
      if (child.exitCode === null && child.signalCode === null && !unavailable) {
        child.stdin.end('{"command":"close"}\n');
        if (requireConfirmation) confirmed = (await receive(10000)).closed === true;
      }
      if (requireConfirmation && !confirmed) throw new Error('check-database-cleanup-failed');
    } finally {
      // EOF gives the helper a chance to drop its database even when startup or
      // a capability request failed. Kill only this task's child process group.
      await waitForHelper();
      if (!finished) { signal('SIGTERM'); await waitForHelper(); }
      if (!finished) signal('SIGKILL');
      reader.close();
      child.stdin.destroy();
    }
  }
  try {
    const ready = await receive();
    if (ready.ready !== true || typeof ready.url !== 'string') throw new Error('check-database-fixture-failed');
    const url = validateOwnedDatabaseURL(ready.url, base, config, environment);
    return {
      url,
      async token(email, kind) {
        if (closed || typeof email !== 'string' || !['verify', 'reset'].includes(kind)) throw new Error('invalid-fixture-request');
        child.stdin.write(JSON.stringify({ command: 'token', email, kind }) + '\n');
        const value = await receive();
        if (typeof value.token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(value.token)) throw new Error('check-database-capability-invalid');
        return value.token;
      },
      close,
    };
  } catch (error) {
    await close(false);
    throw error;
  }
}
