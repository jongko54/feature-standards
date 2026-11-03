#!/usr/bin/env node
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createCheckEnvironment, startDatabaseFixture } from './check-fixture.mjs';

const STACKS = ['python', 'go', 'java', 'rust'];
const PROFILES = ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'];

function configuration(directory) {
  const metadata = JSON.parse(readFileSync(join(directory, 'feature-auth.json'), 'utf8'));
  if (!STACKS.includes(metadata.stack) || !PROFILES.includes(metadata.profile)
      || typeof metadata.source !== 'string' || /[\0-\x1f\x7f]/.test(metadata.source)) {
    throw new Error('invalid-project-metadata');
  }
  return { ...metadata, directory, source: resolve(directory, metadata.source) };
}

function processEnvironment(directory) {
  const environment = { ...process.env };
  environment.UV_PROJECT_ENVIRONMENT = join(directory, '.venv');
  environment.CARGO_TARGET_DIR = join(directory, 'target');
  environment.GOWORK = 'off';
  delete environment.CARGO_BUILD_TARGET;
  // Generated Maven arguments choose the local repository explicitly.
  delete environment.MAVEN_ARGS;
  return environment;
}

function stop(child, signal = 'SIGTERM') {
  if (!Number.isInteger(child.pid)) return;
  try {
    if (process.platform === 'win32') child.kill(signal);
    else process.kill(-child.pid, signal);
  } catch (error) { if (error.code !== 'ESRCH') throw error; }
}

async function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise(resolveExit => {
    const timer = setTimeout(() => { stop(child, 'SIGKILL'); resolveExit(); }, 3000);
    child.once('exit', () => { clearTimeout(timer); resolveExit(); });
  });
}

async function command(program, args, directory, environment, timeout = 240000) {
  const child = spawn(program, args, { cwd: directory, env: environment, stdio: 'inherit', detached: process.platform !== 'win32' });
  const timer = setTimeout(() => stop(child, 'SIGKILL'), timeout);
  const interrupt = () => stop(child);
  process.once('SIGINT', interrupt);
  process.once('SIGTERM', interrupt);
  try {
    await new Promise((resolveCommand, reject) => {
      child.once('error', () => reject(new Error('required-build-command-unavailable: ' + program)));
      child.once('exit', code => code === 0 ? resolveCommand() : reject(new Error('build-command-failed: ' + program)));
    });
  } finally {
    clearTimeout(timer);
    process.removeListener('SIGINT', interrupt);
    process.removeListener('SIGTERM', interrupt);
    stop(child, 'SIGKILL');
  }
}

const xml = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

async function build(config, environment) {
  const directory = config.directory;
  if (config.stack === 'python') {
    await command('uv', ['sync', '--project', directory], directory, environment);
  } else if (config.stack === 'go') {
    await command('go', ['mod', 'tidy'], directory, environment);
    mkdirSync(join(directory, '.feature-auth'), { recursive: true });
    await command('go', ['build', '-o', join(directory, '.feature-auth', process.platform === 'win32' ? 'server.exe' : 'server'), '.'], directory, environment);
  } else if (config.stack === 'rust') {
    await command('cargo', ['build', '--locked'], directory, environment);
  } else {
    const library = join(config.source, 'implementations/java-spring');
    const staging = join(directory, '.feature-auth', 'java-library');
    const repository = join(directory, '.feature-auth', 'm2');
    mkdirSync(staging, { recursive: true });
    const sourcePom = readFileSync(join(library, 'pom.xml'), 'utf8');
    if (!sourcePom.includes('<build>') || sourcePom.includes('<sourceDirectory>') || sourcePom.includes('<resources>')) {
      throw new Error('unsupported-java-source-build-layout');
    }
    const overlay = sourcePom.replace('<build>', `<build>
      <sourceDirectory>${xml(join(library, 'src/main/java'))}</sourceDirectory>
      <resources><resource><directory>${xml(join(library, 'src/main/resources'))}</directory></resource></resources>`);
    writeFileSync(join(staging, 'pom.xml'), overlay);
    const wrapper = join(library, process.platform === 'win32' ? 'mvnw.cmd' : 'mvnw');
    await command(wrapper, ['-q', '-f', join(staging, 'pom.xml'), '-Dmaven.test.skip=true', '-Dmaven.repo.local=' + repository, 'install'], directory, environment);
    await command(wrapper, ['-q', '-f', join(directory, 'pom.xml'), '-Dmaven.repo.local=' + repository, 'package'], directory, environment);
  }
}

function startCommand(config, environment) {
  const directory = config.directory;
  if (config.stack === 'python') return ['uv', ['run', '--frozen', '--project', directory, 'uvicorn', 'app:app', '--no-proxy-headers', '--host', environment.AUTH_HOST || '127.0.0.1', '--port', environment.AUTH_PORT || '8000']];
  if (config.stack === 'go') return [join(directory, '.feature-auth', process.platform === 'win32' ? 'server.exe' : 'server'), []];
  if (config.stack === 'rust') return [join(directory, 'target/debug', process.platform === 'win32' ? 'feature-auth-generated.exe' : 'feature-auth-generated'), []];
  const java = environment.JAVA_HOME ? join(environment.JAVA_HOME, 'bin', process.platform === 'win32' ? 'java.exe' : 'java') : 'java';
  return [java, ['-jar', join(directory, 'target/generated-auth-app.jar')]];
}

function profileEnvironment(config, environment, demo = false) {
  const output = { ...environment, AUTH_STORE: config.profile === 'browser-session-v1' ? 'memory' : 'postgres', AUTH_ACCOUNT_LIFECYCLE: String(config.profile === 'browser-session-v3') };
  if (demo) Object.assign(output, { AUTH_DEMO: 'true', AUTH_HOST: '127.0.0.1', AUTH_COOKIE_SECURE: 'false', AUTH_ALLOWED_ORIGIN: environment.AUTH_ALLOWED_ORIGIN || 'http://127.0.0.1:5173' });
  return output;
}

async function freePort() {
  const listener = createServer();
  await new Promise((resolveListen, reject) => { listener.once('error', reject); listener.listen(0, '127.0.0.1', resolveListen); });
  const port = listener.address().port;
  await new Promise((resolveClose, reject) => listener.close(error => error ? reject(error) : resolveClose()));
  return port;
}

async function check(config, environment) {
  if (config.checkProtocolVersion !== 1) throw new Error('unsupported-check-protocol');
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  // Validate before compiling or making an administrative database connection.
  const fixture = createCheckEnvironment(config, base, environment);
  const checks = [];
  let database;
  let child;
  const interrupt = () => { if (child) stop(child); };
  process.once('SIGINT', interrupt); process.once('SIGTERM', interrupt);
  const request = (path, options = {}) => fetch(base + path, { ...options, headers: { Origin: base, ...(options.headers || {}) }, signal: AbortSignal.timeout(3000), redirect: 'error' });
  const expect = (response, status, label) => { if (response.status !== status) throw new Error('check-' + label); return response; };
  const post = (path, value, headers = {}) => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(value),
  });
  const login = async (email = 'demo@example.com', password = 'correct-horse-battery-staple') => {
    const response = expect(await post('/auth/login', { email, password }), 200, 'login');
    const session = await response.json();
    const cookie = response.headers.get('set-cookie')?.split(';', 1)[0];
    if (!/^fs_session=[A-Za-z0-9_-]{43}$/.test(cookie || '') || typeof session.csrfToken !== 'string' || !session.user) throw new Error('check-session-shape');
    return { ...session, cookie };
  };
  const protectedIdentity = async session => {
    const response = expect(await request('/api/profile', { headers: { Cookie: session.cookie } }), 200, 'profile');
    assert.deepEqual((await response.json()).user, session.user, 'check-profile-identity');
  };
  const stopServer = async () => {
    if (!child) return;
    stop(child); await waitForExit(child); stop(child, 'SIGKILL'); child = undefined;
  };
  const startServer = async () => {
    const [program, args] = startCommand(config, fixture);
    child = spawn(program, args, { cwd: config.directory, env: fixture, stdio: ['ignore', 'ignore', 'ignore'], detached: process.platform !== 'win32' });
    let launchError = false;
    child.once('error', () => { launchError = true; });
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      if (launchError || child.exitCode !== null || child.signalCode !== null) throw new Error('check-server-exited');
      try {
        const response = await request('/healthz');
        if (response.status === 200) {
          const health = await response.json();
          if (health.profile !== config.profile) throw new Error('check-selected-profile-mismatch');
          return;
        }
      } catch (error) {
        if (error.message === 'check-selected-profile-mismatch') throw error;
        // The child has not opened its listener yet.
      }
      await new Promise(resolveDelay => setTimeout(resolveDelay, 100));
    }
    throw new Error('check-server-timeout');
  };
  try {
    if (config.profile !== 'browser-session-v1') {
      database = await startDatabaseFixture(config, environment);
      fixture.AUTH_DATABASE_URL = database.url;
    }
    await build(config, fixture);
    await startServer();
    checks.push('selected-profile-health');
    expect(await request('/api/profile'), 401, 'anonymous');
    expect(await request('/api/profile', { headers: { Cookie: 'fs_session=forged-consumer-cookie' } }), 401, 'forged-cookie');
    checks.push('anonymous-and-forged-protected-access');
    const first = await login();
    const second = await login();
    assert.notEqual(first.cookie, second.cookie, 'check-independent-cookies');
    assert.notEqual(first.csrfToken, second.csrfToken, 'check-independent-csrf');
    await protectedIdentity(first);
    await protectedIdentity(second);
    checks.push('login-shared-protected-identity', 'independent-sessions');
    expect(await request('/auth/logout', { method: 'POST', headers: { Cookie: first.cookie, 'X-CSRF-Token': second.csrfToken } }), 403, 'csrf');
    await protectedIdentity(first);
    checks.push('csrf-rejection-preserves-session');
    expect(await request('/auth/logout', { method: 'POST', headers: { Cookie: first.cookie, 'X-CSRF-Token': first.csrfToken } }), 204, 'logout');
    expect(await request('/api/profile', { headers: { Cookie: first.cookie } }), 401, 'copied-cookie');
    expect(await request('/auth/me', { headers: { Cookie: first.cookie } }), 401, 'revoked-session');
    await protectedIdentity(second);
    checks.push('server-logout-revokes-copied-cookie');
    if (database) {
      await stopServer();
      await startServer();
      await protectedIdentity(second);
      checks.push('database-session-survives-server-restart');
    }
    if (config.profile === 'browser-session-v3') {
      const email = 'generated-account@example.com';
      const password = 'correct-horse-battery-staple';
      const newPassword = 'generated-new-password-after-reset';
      expect(await post('/auth/register', { email, password }), 202, 'register');
      expect(await post('/auth/login', { email, password }), 401, 'unverified-login');
      checks.push('registration-awaits-verification');
      const verification = await database.token(email, 'verify');
      expect(await post('/auth/email-verification/confirm', { token: verification }), 204, 'verification');
      expect(await post('/auth/email-verification/confirm', { token: verification }), 400, 'verification-replay');
      checks.push('email-verification-single-use');
      const account = await login(email, password);
      const independent = await login(email, password);
      await protectedIdentity(account);
      assert.equal(account.user.email, email, 'check-registered-identity');
      expect(await post('/auth/password-reset/request', { email }), 202, 'reset-request');
      const reset = await database.token(email, 'reset');
      expect(await post('/auth/password-reset/confirm', { token: reset, password: newPassword }), 204, 'reset-confirm');
      for (const session of [account, independent]) {
        expect(await request('/api/profile', { headers: { Cookie: session.cookie } }), 401, 'reset-revokes-protected');
        expect(await request('/auth/me', { headers: { Cookie: session.cookie } }), 401, 'reset-revokes-session');
      }
      checks.push('password-reset-revokes-all-sessions');
      expect(await post('/auth/password-reset/confirm', { token: reset, password: newPassword }), 400, 'reset-replay');
      expect(await post('/auth/login', { email, password }), 401, 'old-password');
      await protectedIdentity(await login(email, newPassword));
      checks.push('password-reset-single-use', 'new-password-authenticates');
    }
  } finally {
    process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', interrupt);
    await stopServer();
    if (database) await database.close();
  }
  return {
    schemaVersion: 1, stack: config.stack, profile: config.profile, passed: true, checks,
    database: database
      ? { used: true, isolated: true, created: true, dropped: true, existingDatabaseModified: false }
      : { used: false, isolated: false },
  };
}

export async function runProject(mode, directory = dirname(fileURLToPath(import.meta.url))) {
  if (!['build', 'start', 'demo', 'check'].includes(mode)) throw new Error('usage: node project.mjs build|start|demo|check');
  const config = configuration(directory);
  const environment = processEnvironment(directory);
  if (mode === 'build') return build(config, environment);
  if (mode === 'check') return check(config, environment);
  const runtime = profileEnvironment(config, environment, mode === 'demo');
  const [program, args] = startCommand(config, runtime);
  return command(program, args, directory, runtime, 0x7fffffff);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runProject(process.argv[2]).then(result => { if (result) console.log(JSON.stringify(result, null, 2)); })
    .catch(error => { console.error('feature-auth project: ' + error.message); process.exitCode = 1; });
}
