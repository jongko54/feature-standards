import assert from 'node:assert/strict';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';
import test from 'node:test';
import { generateCore, inspectCore } from '../src/core-generator.mjs';
import { coreEnvironment, runProject } from '../src/core-project.mjs';
import { CORE_FEATURES, CORE_PROFILES } from '../src/core-protocol.mjs';
import { checkCore, requestJson } from '../src/core-check.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const scratch = () => realpathSync(mkdtempSync(join(tmpdir(), 'feature-core-generator-')));
const authRoots = { python: 'implementations/python-fastapi', go: 'implementations/go-net-http', java: 'implementations/java-spring', rust: 'implementations/rust-axum' };
const markers = { python: ['feature_auth/__init__.py', 'feature_standards/__init__.py'], go: ['auth/server.go', 'authorization/policy.go'], java: ['pom.xml', 'pom.xml'], rust: ['Cargo.toml', 'src/lib.rs'] };
function sourceFixture(directory) {
  const source = join(directory, 'source checkout');
  mkdirSync(source);
  for (const file of ['features/catalog.json', 'feature-standards.json', 'features/authorization/catalog.json', 'features/listing/catalog.json']) {
    mkdirSync(dirname(join(source, file)), { recursive: true });
    copyFileSync(join(ROOT, file), join(source, file));
  }
  mkdirSync(join(source, 'packages/feature-standards/src'), { recursive: true });
  writeFileSync(join(source, 'packages/feature-standards/package.json'), JSON.stringify({ name: 'feature-standards', version: '0.4.0', featureStandards: { coreStarterProtocolVersion: 1 } }));
  writeFileSync(join(source, 'packages/feature-standards/src/core-generator.mjs'), 'export function generateCore() {}\n');
  for (const stack of Object.keys(authRoots)) {
    for (const [base, marker] of [[authRoots[stack], markers[stack][0]], ['libraries/' + stack, markers[stack][1]]]) {
      mkdirSync(dirname(join(source, base, marker)), { recursive: true });
      if (stack === 'java') copyFileSync(join(ROOT, base, marker), join(source, base, marker));
      else writeFileSync(join(source, base, marker), 'source marker\n');
    }
  }
  return source;
}
const options = (directory, source, overrides = {}) => ({ source, stack: 'python', profile: 'browser-session-v1', dest: join(directory, 'generated app'), ...overrides });

test('core selection resolves both real source dependencies and fingerprints every selected catalog', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const plan = inspectCore(options(directory, source));
    assert.equal(plan.source, source);
    assert.equal(resolve(plan.destination, plan.dependencies.auth.path), join(source, authRoots.python));
    assert.equal(resolve(plan.destination, plan.dependencies.core.path), join(source, 'libraries/python'));
    assert.deepEqual(Object.keys(plan.sourceManifestsSha256).sort(), ['features/catalog.json', 'feature-standards.json', 'features/authorization/catalog.json', 'features/listing/catalog.json'].sort());
    for (const digest of Object.values(plan.sourceManifestsSha256)) assert.match(digest, /^[a-f0-9]{64}$/);
    assert.equal(existsSync(plan.destination), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('unsupported core stacks and profiles fail before creating a destination', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    for (const stack of ['react', 'typescript', 'other']) assert.throws(() => generateCore(options(directory, source, { stack })), /unsupported-core-stack/);
    for (const profile of ['browser-session-v2', 'browser-session-v3', 'postgres-list-v1']) assert.throws(() => generateCore(options(directory, source, { profile })), /unsupported-core-profile/);
    assert.throws(() => generateCore(options(directory, source, { feature: 'auth' })), /ambiguous-core-selection/);
    assert.equal(existsSync(join(directory, 'generated app')), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('a source without the explicit core starter capability is refused', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    writeFileSync(join(source, 'packages/feature-standards/package.json'), JSON.stringify({ name: 'feature-standards', version: '0.4.0' }));
    assert.throws(() => generateCore(options(directory, source)), /unsupported-core-source-capability/);
    assert.equal(existsSync(join(directory, 'generated app')), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('tampered core catalog roots are refused before any project write', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const catalogPath = join(source, 'features/listing/catalog.json');
    const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
    catalog.stacks.find(stack => stack.id === 'python').root = '../outside';
    writeFileSync(catalogPath, JSON.stringify(catalog));
    assert.throws(() => generateCore(options(directory, source)), /unsupported-core-source-manifest/);
    assert.equal(existsSync(join(directory, 'generated app')), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('existing directories, files and dangling links remain untouched', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const destination = join(directory, 'generated app');
    mkdirSync(destination); writeFileSync(join(destination, 'mine'), 'keep');
    assert.throws(() => generateCore(options(directory, source)), /destination-already-exists/);
    assert.equal(readFileSync(join(destination, 'mine'), 'utf8'), 'keep');
    const file = join(directory, 'existing'); writeFileSync(file, 'original');
    assert.throws(() => generateCore(options(directory, source, { dest: file })), /destination-already-exists/);
    assert.equal(readFileSync(file, 'utf8'), 'original');
    const link = join(directory, 'dangling'); symlinkSync(join(directory, 'missing'), link);
    assert.throws(() => generateCore(options(directory, source, { dest: link })), /destination-already-exists/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('symlinked source paths and output parents cannot redirect the generation', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const link = join(directory, 'linked-source'); symlinkSync(source, link, 'dir');
    assert.throws(() => generateCore(options(directory, link)), /source-must-be-a-physical-directory/);
    const output = join(directory, 'output'); mkdirSync(output);
    const parent = join(directory, 'linked-parent'); symlinkSync(output, parent, 'dir');
    assert.throws(() => generateCore(options(directory, source, { dest: join(parent, 'app') })), /destination-parent-must-be-a-physical-directory/);
    assert.deepEqual(readdirSync(output), []);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('selected library symlink escapes and destinations inside source are refused', () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    assert.throws(() => generateCore(options(directory, source, { dest: join(source, 'app') })), /destination-inside-source/);
    const marker = join(source, 'libraries/python/feature_standards/__init__.py');
    rmSync(marker); symlinkSync(join(ROOT, 'libraries/python/feature_standards/__init__.py'), marker);
    assert.throws(() => generateCore(options(directory, source)), /source-file-must-be-a-regular-file/);
    assert.equal(existsSync(join(directory, 'generated app')), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('check environment discards inherited runtime, database and account configuration', () => {
  const inherited = { PATH: '/safe/bin', AUTH_STORE: 'postgres', AUTH_DATABASE_URL: 'private', AUTH_ACCOUNT_LIFECYCLE: 'true', AUTH_USER_EMAIL: 'existing', PORT: '9999', PGHOST: 'private', DATABASE_URL: 'private', FEATURE_STANDARDS_TEST_DATABASE_URL: 'private' };
  const runtime = coreEnvironment('check', inherited, 'http://127.0.0.1:18555');
  assert.equal(runtime.PATH, '/safe/bin');
  assert.equal(runtime.AUTH_STORE, 'memory');
  assert.equal(runtime.AUTH_ACCOUNT_LIFECYCLE, 'false');
  assert.equal(runtime.AUTH_DATABASE_URL, undefined);
  assert.equal(runtime.DATABASE_URL, undefined);
  assert.equal(runtime.PORT, undefined);
  assert.equal(runtime.PGHOST, undefined);
  assert.equal(runtime.FEATURE_STANDARDS_TEST_DATABASE_URL, undefined);
  assert.equal(runtime.AUTH_HOST, '127.0.0.1');
  assert.equal(runtime.AUTH_PORT, '18555');
  assert.equal(runtime.AUTH_DEMO, 'true');
  assert.equal(runtime.AUTH_COOKIE_SECURE, 'false');
  assert.equal(runtime.AUTH_ALLOWED_ORIGIN, 'http://127.0.0.1:18555');
  assert.deepEqual(inherited.AUTH_DATABASE_URL, 'private');
});

test('ordinary start selects secure non-demo memory mode; demo forcibly binds to loopback', () => {
  const start = coreEnvironment('start', { AUTH_DEMO: 'true', AUTH_COOKIE_SECURE: 'false', AUTH_STORE: 'postgres', AUTH_ACCOUNT_LIFECYCLE: 'true', AUTH_HOST: '0.0.0.0', AUTH_ALLOWED_ORIGIN: 'https://app.example', AUTH_USER_EMAIL: 'user@example.com', AUTH_USER_PASSWORD: 'private', AUTH_DATABASE_URL: 'private', PORT: '9000' });
  assert.equal(start.AUTH_DEMO, 'false'); assert.equal(start.AUTH_COOKIE_SECURE, 'true');
  assert.equal(start.AUTH_STORE, 'memory'); assert.equal(start.AUTH_ACCOUNT_LIFECYCLE, 'false');
  assert.equal(start.AUTH_HOST, '0.0.0.0'); assert.equal(start.AUTH_USER_EMAIL, 'user@example.com');
  assert.equal(start.AUTH_DATABASE_URL, undefined); assert.equal(start.PORT, undefined);
  const demo = coreEnvironment('demo', { AUTH_HOST: '0.0.0.0', AUTH_ALLOWED_ORIGIN: 'https://external.example', AUTH_USER_PASSWORD: 'private' });
  assert.equal(demo.AUTH_HOST, '127.0.0.1'); assert.equal(demo.AUTH_ALLOWED_ORIGIN, 'http://127.0.0.1:5173');
  assert.equal(demo.AUTH_DEMO, 'true'); assert.equal(demo.AUTH_COOKIE_SECURE, 'false');
  assert.equal(demo.AUTH_USER_PASSWORD, 'correct-horse-battery-staple');
});

test('metadata failures reject a check before invoking builds or creating output', async () => {
  const directory = scratch();
  try {
    writeFileSync(join(directory, 'feature-core.json'), JSON.stringify({ template: 'core', stack: 'python', profile: 'browser-session-v2' }));
    await assert.rejects(runProject('check', directory), /invalid-core-project-metadata/);
    assert.deepEqual(readdirSync(directory), ['feature-core.json']);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('all backends generate thin relative consumers and copy only runner helpers', async () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const original = readFileSync(join(source, 'feature-standards.json'), 'utf8');
    for (const stack of Object.keys(authRoots)) {
      const destination = join(directory, stack + ' app');
      const result = generateCore(options(directory, source, { stack, dest: destination }));
      const metadata = JSON.parse(readFileSync(join(destination, 'feature-core.json'), 'utf8'));
      assert.equal(result.template, 'core'); assert.equal(metadata.generator, 'feature-standards');
      assert.equal(metadata.coreCheckProtocolVersion, 1); assert.equal(metadata.stack, stack);
      assert.deepEqual(metadata.features, CORE_FEATURES); assert.deepEqual(metadata.profiles, CORE_PROFILES);
      assert.equal(resolve(destination, metadata.source), source);
      assert.equal(resolve(destination, metadata.dependencies.auth.path), join(source, authRoots[stack]));
      assert.equal(resolve(destination, metadata.dependencies.core.path), join(source, 'libraries/' + stack));
      for (const file of ['project.mjs', 'core-check.mjs', 'core-process.mjs', 'core-source.mjs', 'core-protocol.mjs']) assert.ok(result.files.includes(file));
      for (const file of ['feature-auth.json', '.env', 'node_modules', '.venv', 'target', 'implementations', 'libraries']) assert.equal(existsSync(join(destination, file)), false);
      const manifestFile = { python: 'pyproject.toml', go: 'go.mod', java: 'pom.xml', rust: 'Cargo.toml' }[stack];
      const dependency = readFileSync(join(destination, manifestFile), 'utf8');
      assert.ok(!dependency.includes('{{')); assert.ok(!dependency.includes(source));
      assert.match(readFileSync(join(destination, '.env.example'), 'utf8'), /AUTH_DEMO=false/);
      const runner = await import(new URL('../src/core-project.mjs', import.meta.url));
      const damaged = { ...metadata, features: ['auth'] };
      writeFileSync(join(destination, 'feature-core.json'), JSON.stringify(damaged));
      await assert.rejects(runner.runProject('check', destination), /invalid-core-project-metadata/);
    }
    assert.equal(readFileSync(join(source, 'feature-standards.json'), 'utf8'), original);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('recorded catalog changes and dependency redirection fail before build artifacts', async () => {
  const directory = scratch();
  try {
    const source = sourceFixture(directory);
    const destination = join(directory, 'generated app');
    generateCore(options(directory, source));
    const manifest = join(source, 'features/listing/catalog.json');
    const original = readFileSync(manifest, 'utf8');
    writeFileSync(manifest, original + '\n');
    await assert.rejects(runProject('check', destination), /core-source-manifests-changed/);
    writeFileSync(manifest, original);
    const metadataPath = join(destination, 'feature-core.json');
    const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'));
    metadata.dependencies.core.path = '.';
    writeFileSync(metadataPath, JSON.stringify(metadata));
    await assert.rejects(runProject('check', destination), /invalid-core-project-dependencies/);
    assert.equal(existsSync(join(destination, '.venv')), false);
    assert.equal(existsSync(join(destination, '.feature-core')), false);
    assert.equal(existsSync(join(destination, 'target')), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('the HTTP check transport stays on loopback, omits Origin explicitly, and never follows redirects', async () => {
  let requests = 0;
  const server = createServer((request, response) => {
    requests++;
    assert.equal(request.headers.origin, undefined);
    response.writeHead(302, { Location: 'https://external.example', 'Content-Type': 'application/json' });
    response.end('{"redirected":false}');
  });
  await new Promise(resolveListen => server.listen(0, '127.0.0.1', resolveListen));
  try {
    const base = 'http://127.0.0.1:' + server.address().port;
    const result = await requestJson(base, '/check', { origin: null });
    assert.equal(result.status, 302); assert.deepEqual(result.value, { redirected: false }); assert.equal(requests, 1);
    assert.throws(() => requestJson('http://external.example:8000', '/check'), /unsafe-core-check-address/);
  } finally { await new Promise(resolveClose => server.close(resolveClose)); }
});

test('the checker refuses incomplete SDK-origin proof before starting any server', async () => {
  let started = false;
  await assert.rejects(checkCore({ coreCheckProtocolVersion: 1, directory: ROOT, dependencies: { auth: '/expected/auth', core: '/expected/core' } }, {}, {
    coreEnvironment,
    build: async () => {},
    dependencyOrigins: async () => ({ auth: { kind: 'source', expectedPath: '/expected/auth', resolvedPath: '/expected/auth', verified: true } }),
    startCommand: () => { started = true; throw new Error('must-not-start'); },
  }));
  assert.equal(started, false);
});
