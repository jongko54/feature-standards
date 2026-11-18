import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer, get, request } from 'node:http';
import { existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import { buildFrontend, loadEnvironment, parseOptions, startFrontend } from './react-preview.mjs';

const require = createRequire(new URL('../clients/react/package.json', import.meta.url));
const esbuild = require('esbuild');
const { parse } = require('dotenv');
const { expand } = require('dotenv-expand');
const environment = { VITE_AUTH_ACCOUNT_LIFECYCLE: 'false' };

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'feature-react-test-'));
  mkdirSync(join(root, 'src'));
  writeFileSync(join(root, 'index.html'), '<!doctype html><html><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>');
  const source = marker => `import './style.css'; console.log(${JSON.stringify(marker)}, import.meta.env.VITE_AUTH_ACCOUNT_LIFECYCLE);`;
  writeFileSync(join(root, 'src/main.tsx'), source('ORIGINAL_MARKER'));
  writeFileSync(join(root, 'src/style.css'), 'body { color: rebeccapurple }');
  const cleanup = [];
  t.after(async () => { for (const close of cleanup.reverse()) await close(); rmSync(root, { recursive: true, force: true }); });
  return { root, source, own: close => cleanup.push(close) };
}

async function backend(t, handler) {
  const server = createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  return { server, origin: `http://127.0.0.1:${server.address().port}` };
}

async function frontend(t, options = {}) {
  const files = fixture(t);
  const app = await startFrontend({ root: files.root, esbuild, environment, port: 0, ...options });
  files.own(app.close);
  return { ...files, ...app, origin: `http://127.0.0.1:${app.port}` };
}

async function until(check, timeout = 6000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw new Error('frontend condition did not become true');
}

function raw(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = request(url, { headers }, res => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('error', reject);
    req.end();
  });
}

test('the demo CLI refuses unknown flags and non-loopback exposure', () => {
  assert.throws(() => parseOptions(['dev', '--unknown']), /unsupported/);
  assert.throws(() => parseOptions(['dev', '--host', '0.0.0.0']), /loopback/);
  assert.throws(() => parseOptions(['dev', '--port', '0']), /port/);
  assert.throws(() => parseOptions(['dev', '--mode', '../private']), /mode/);
  assert.throws(() => parseOptions(['dev', '--port', '65536']), /port/);
  assert.throws(() => parseOptions(['dev', '--port', '5173', '--port', '5174']), /repeated/);
  assert.equal(parseOptions(['dev', '--host', 'localhost', '--port', '5173', '--strictPort']).port, 5173);
  assert.equal(parseOptions(['dev'], { defaultPort: 5174 }).port, 5174);
  assert.equal(parseOptions(['preview']).port, 4173);
});

test('dotenv precedence and expansion preserve process settings without exporting private keys', t => {
  const { root } = fixture(t);
  writeFileSync(join(root, '.env'), 'BASE_PORT=8000\nAUTH_API_TARGET=http://127.0.0.1:${BASE_PORT}\nVITE_AUTH_ACCOUNT_LIFECYCLE=false\nDATABASE_PASSWORD=PRIVATE_ENV_VALUE\n');
  writeFileSync(join(root, '.env.local'), 'BASE_PORT=8001\n');
  writeFileSync(join(root, '.env.test'), 'BASE_PORT=8002\n');
  writeFileSync(join(root, '.env.test.local'), 'BASE_PORT=8003\nVITE_AUTH_ACCOUNT_LIFECYCLE=true\n');
  const inherited = { BASE_PORT: '9000', VITE_AUTH_ACCOUNT_LIFECYCLE: 'false' };
  assert.deepEqual(loadEnvironment(root, 'test', inherited, { parse, expand }), {
    AUTH_API_TARGET: 'http://127.0.0.1:9000', VITE_AUTH_ACCOUNT_LIFECYCLE: 'false',
  });
  assert.deepEqual(inherited, { BASE_PORT: '9000', VITE_AUTH_ACCOUNT_LIFECYCLE: 'false' });
  assert.deepEqual(loadEnvironment(root, 'test', {}, { parse, expand }), {
    AUTH_API_TARGET: 'http://127.0.0.1:8003', VITE_AUTH_ACCOUNT_LIFECYCLE: 'true',
  });
});

test('actual TSX/CSS production builds expose only the account flag and preserve the HTML entry', async t => {
  const { root } = fixture(t);
  const output = await buildFrontend({ root, esbuild, environment: { VITE_AUTH_ACCOUNT_LIFECYCLE: 'true', AUTH_API_TARGET: 'http://PRIVATE_API_TARGET:8765', DATABASE_PASSWORD: 'PRIVATE_PASSWORD_VALUE' } });
  const html = readFileSync(join(output, 'index.html'), 'utf8');
  const js = readFileSync(join(output, 'assets/app.js'), 'utf8');
  assert.match(html, /\/assets\/app\.js/);
  assert.match(html, /\/assets\/app\.css/);
  assert.doesNotMatch(html, /\/src\/main\.tsx|EventSource/);
  assert.match(js, /true/);
  assert.doesNotMatch(js, /PRIVATE_API_TARGET|PRIVATE_PASSWORD_VALUE|import\.meta\.env/);
  await buildFrontend({ root, esbuild, environment });
  assert.match(readFileSync(join(output, 'assets/app.js'), 'utf8'), /false/);
  await buildFrontend({ root, esbuild, environment: { VITE_AUTH_ACCOUNT_LIFECYCLE: 'PRIVATE_MISCONFIGURED_VALUE' } });
  assert.doesNotMatch(readFileSync(join(output, 'assets/app.js'), 'utf8'), /PRIVATE_MISCONFIGURED_VALUE/);
});

test('the actual proxy preserves auth bodies, host/origin/cookie/CSRF and response headers', async t => {
  let received;
  const api = await backend(t, (req, res) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      received = { headers: req.headers, method: req.method, path: req.url, body: Buffer.concat(chunks) };
      res.writeHead(429, { 'set-cookie': ['first=one; HttpOnly', 'second=two; SameSite=Lax'], 'retry-after': '3', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
      res.end('RATE_LIMITED');
    });
  });
  const app = await frontend(t, { environment: { AUTH_API_TARGET: api.origin } });
  const body = Buffer.from([0xff, 0, 0x61]);
  const response = await fetch(app.origin + '/auth/logout?check=raw', { method: 'POST', headers: {
    origin: 'https://untrusted.example', cookie: 'fs_session=synthetic', 'x-csrf-token': 'synthetic-csrf', 'content-type': 'application/octet-stream',
  }, body });
  assert.equal(response.status, 429);
  assert.equal(await response.text(), 'RATE_LIMITED');
  assert.deepEqual(response.headers.getSetCookie(), ['first=one; HttpOnly', 'second=two; SameSite=Lax']);
  assert.equal(response.headers.get('retry-after'), '3');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(received.headers.host, new URL(app.origin).host);
  assert.equal(received.headers.origin, 'https://untrusted.example');
  assert.equal(received.headers.cookie, 'fs_session=synthetic');
  assert.equal(received.headers['x-csrf-token'], 'synthetic-csrf');
  assert.equal(received.method, 'POST');
  assert.equal(received.path, '/auth/logout?check=raw');
  assert.deepEqual(received.body, body);
});

test('API 404s stay distinct from SPA routes, and only explicit API prefixes are proxied', async t => {
  let count = 0;
  const api = await backend(t, (_req, res) => { count++; res.writeHead(404); res.end('API_NOT_FOUND'); });
  const app = await frontend(t, { environment: { AUTH_API_TARGET: api.origin }, routes: ['/auth', '/healthz', '/api'] });
  for (const path of ['/auth/missing', '/healthz', '/api/profile']) {
    const response = await fetch(app.origin + path);
    assert.equal(response.status, 404);
    assert.equal(await response.text(), 'API_NOT_FOUND');
  }
  assert.equal(count, 3);
  for (const path of ['/verify-email', '/reset-password', '/apiary']) {
    const response = await fetch(app.origin + path);
    assert.equal(response.status, 200);
    assert.match(await response.text(), /<!doctype html>/);
  }
  assert.equal(count, 3);
});

test('development serves JS/CSS but never checkout dotfiles or an alien static origin/host', async t => {
  const app = await frontend(t);
  writeFileSync(join(app.root, '.env'), 'PRIVATE_NOT_IN_BUNDLE=PRIVATE_FILE_VALUE');
  const js = await fetch(app.origin + '/assets/app.js');
  assert.equal(js.status, 200);
  assert.match(js.headers.get('content-type'), /javascript/);
  assert.match(await js.text(), /ORIGINAL_MARKER/);
  const css = await fetch(app.origin + '/assets/app.css');
  assert.match(css.headers.get('content-type'), /css/);
  assert.match(await css.text(), /rebeccapurple/);
  for (const path of ['/.env', '/src/main.tsx', '/%2e%2e/.env']) {
    const response = await fetch(app.origin + path);
    assert.doesNotMatch(await response.text(), /PRIVATE_FILE_VALUE|ORIGINAL_MARKER/);
  }
  assert.equal((await raw(app.origin, { Host: 'untrusted.example' })).status, 403);
  assert.equal((await fetch(app.origin, { headers: { Origin: 'https://untrusted.example' } })).status, 403);
  assert.equal((await fetch(app.origin + '/esbuild', { headers: { Accept: 'text/event-stream', Origin: 'https://untrusted.example' } })).status, 403);
});

test('watch rebuilds real output and emits a reload event through the public proxy', { timeout: 10000 }, async t => {
  const app = await frontend(t);
  let events = '';
  const stream = get(app.origin + '/esbuild', { headers: { Accept: 'text/event-stream' } }, res => { res.setEncoding('utf8'); res.on('data', chunk => { events += chunk; }); });
  stream.on('error', () => {});
  app.own(() => stream.destroy());
  await until(() => stream.res?.statusCode === 200);
  writeFileSync(join(app.root, 'src/main.tsx'), app.source('CHANGED_MARKER'));
  await until(() => /event:\s*change/.test(events));
  assert.match(events, /\/assets\/app\.js/);
  assert.match(await (await fetch(app.origin + '/assets/app.js')).text(), /CHANGED_MARKER/);
});

test('a later production build does not retain an old CSS link after its import is removed', async t => {
  const { root } = fixture(t);
  const output = await buildFrontend({ root, esbuild, environment });
  writeFileSync(join(output, 'user-note.txt'), 'KEEP_USER_NOTE');
  assert.match(readFileSync(join(output, 'index.html'), 'utf8'), /\/assets\/app\.css/);
  writeFileSync(join(root, 'src/main.tsx'), 'console.log("NO_STYLES");');
  await buildFrontend({ root, esbuild, environment });
  assert.doesNotMatch(readFileSync(join(output, 'index.html'), 'utf8'), /\/assets\/app\.css/);
  assert.equal(readFileSync(join(output, 'user-note.txt'), 'utf8'), 'KEEP_USER_NOTE');
});

test('preview refuses file/directory symlinks added before or after startup', async t => {
  const files = fixture(t);
  const output = await buildFrontend({ root: files.root, esbuild, environment });
  writeFileSync(join(files.root, '.env'), 'PRIVATE_CHECKOUT_VALUE');
  symlinkSync(join(files.root, '.env'), join(output, 'initial-link'));
  const app = await startFrontend({ root: files.root, esbuild, environment, command: 'preview', port: 0 });
  files.own(app.close);
  const origin = `http://127.0.0.1:${app.port}`;
  assert.equal((await fetch(origin + '/initial-link')).status, 403);
  symlinkSync(files.root, join(output, 'late-link'), 'dir');
  const response = await fetch(origin + '/late-link/.env');
  assert.equal(response.status, 403);
  assert.doesNotMatch(await response.text(), /PRIVATE_CHECKOUT_VALUE/);
  mkdirSync(join(output, 'nested'));
  symlinkSync(join(files.root, '.env'), join(output, 'nested/index.html'));
  assert.equal((await fetch(origin + '/nested/')).status, 403);
});

test('production builds reject dangling output links instead of writing beyond dist', async t => {
  const files = fixture(t);
  const assets = join(files.root, 'dist/assets');
  mkdirSync(assets, { recursive: true });
  const escapedJs = join(files.root, 'not-an-output.js');
  symlinkSync(escapedJs, join(assets, 'app.js'));
  await assert.rejects(buildFrontend({ root: files.root, esbuild, environment }), /linked frontend output/);
  assert.equal(existsSync(escapedJs), false);
  rmSync(join(assets, 'app.js'));
  const escapedHtml = join(files.root, 'not-an-output.html');
  symlinkSync(escapedHtml, join(files.root, 'dist/index.html'));
  await assert.rejects(buildFrontend({ root: files.root, esbuild, environment }), /linked frontend output/);
  assert.equal(existsSync(escapedHtml), false);
});

test('development build diagnostics do not expose source content through HTTP', async t => {
  const app = await frontend(t);
  writeFileSync(join(app.root, 'src/main.tsx'), 'const PRIVATE_COMPILE_LINE = ;');
  await until(async () => (await fetch(app.origin + '/assets/app.js')).status === 503);
  const response = await fetch(app.origin + '/assets/app.js');
  assert.equal(await response.text(), 'Frontend build unavailable');
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('preview serves the built SPA at 4173 with the same API proxy and no reload client', async t => {
  const files = fixture(t);
  const api = await backend(t, (_req, res) => { res.writeHead(204, { 'set-cookie': 'fs_session=; Max-Age=0; HttpOnly' }); res.end(); });
  await buildFrontend({ root: files.root, esbuild, environment });
  const app = await startFrontend({ root: files.root, esbuild, environment: { AUTH_API_TARGET: api.origin }, command: 'preview', port: 4173 });
  files.own(app.close);
  const html = await (await fetch('http://127.0.0.1:4173/verify-email')).text();
  assert.match(html, /\/assets\/app\.css/);
  assert.doesNotMatch(html, /EventSource/);
  const logout = await fetch('http://127.0.0.1:4173/auth/logout', { method: 'POST' });
  assert.equal(logout.status, 204);
  assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
});

test('port collisions fail without moving ports, and failed startup leaves the existing listener intact', async t => {
  const api = await backend(t, (_req, res) => res.end('EXISTING_LISTENER'));
  const files = fixture(t);
  await assert.rejects(startFrontend({ root: files.root, esbuild, environment, port: api.server.address().port }), { code: 'EADDRINUSE' });
  assert.equal(await (await fetch(api.origin)).text(), 'EXISTING_LISTENER');
});

test('a connected but stalled API has an inactivity bound and returns a generic error', async t => {
  const stalled = await backend(t, () => {});
  const app = await frontend(t, { environment: { AUTH_API_TARGET: stalled.origin }, apiTimeout: 40 });
  const response = await fetch(app.origin + '/auth/me');
  assert.equal(response.status, 502);
  assert.equal(await response.text(), 'Frontend upstream unavailable');
  assert.equal(response.headers.get('cache-control'), 'no-store');
  await assert.rejects(startFrontend({ root: app.root, esbuild, environment: { AUTH_API_TARGET: 'http://user:private@127.0.0.1:8000' } }), /without credentials/);
});

test('the actual CLI owns and releases its public listener on SIGTERM', { timeout: 10000 }, async t => {
  const files = fixture(t);
  const script = join(files.root, 'frontend.mjs');
  const moduleUrl = pathToFileURL(require.resolve('esbuild')).href;
  const dotenvUrl = pathToFileURL(require.resolve('dotenv')).href;
  const expandUrl = pathToFileURL(require.resolve('dotenv-expand')).href;
  writeFileSync(script, `import * as esbuild from ${JSON.stringify(moduleUrl)}; import {parse} from ${JSON.stringify(dotenvUrl)}; import {expand} from ${JSON.stringify(expandUrl)}; import {frontendMain} from ${JSON.stringify(new URL('./react-preview.mjs', import.meta.url).href)}; await frontendMain({root:${JSON.stringify(files.root)}, esbuild, parse, expand});`);
  const reservation = await backend(t, (_req, res) => res.end());
  const port = reservation.server.address().port;
  await new Promise(resolve => reservation.server.close(resolve));
  const child = spawn(process.execPath, [script, 'dev', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { env: { ...process.env, AUTH_API_TARGET: 'http://127.0.0.1:8000', VITE_AUTH_ACCOUNT_LIFECYCLE: 'false' }, stdio: ['ignore', 'pipe', 'pipe'] });
  files.own(() => { if (child.exitCode === null) child.kill('SIGKILL'); });
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  let diagnostic = '';
  child.stderr.on('data', chunk => { diagnostic += chunk; });
  await until(() => output.includes(`http://127.0.0.1:${port}`));
  assert.equal((await fetch(`http://127.0.0.1:${port}`)).status, 200);
  const exited = new Promise(resolve => child.once('exit', (code, signal) => resolve({ code, signal })));
  child.kill('SIGTERM');
  assert.deepEqual(await exited, { code: 0, signal: null });
  assert.equal(diagnostic, '');
  const another = createServer();
  await new Promise((resolve, reject) => { another.once('error', reject); another.listen(port, '127.0.0.1', resolve); });
  await new Promise(resolve => another.close(resolve));
});
