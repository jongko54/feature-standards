import assert from 'node:assert/strict';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { CORE_AUTH_ROOTS, CORE_MANIFESTS } from '../src/core-protocol.mjs';
import { fixtureReceipt, fixtureSource } from './workflow-fixture.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = resolve(PACKAGE, '../..');
const CLI = join(PACKAGE, 'src/cli.mjs');
// Keep the externally promised selections and checks independent of the runner's
// own list so removing a required behavior cannot make its rejection test vanish.
const CORE_STACKS = ['python', 'go', 'java', 'rust'];
const CORE_FEATURES = ['auth', 'authorization', 'listing'];
const CORE_PROFILES = { auth: 'browser-session-v1', authorization: 'rbac-v1', listing: 'offset-list-v1' };
const CORE_REQUIRED_CHECKS = [
  'selected-profile-health', 'actual-sdk-dependency-origins', 'normal-start-denies-sample-access',
  'anonymous-and-forged-protected-access', 'login-shared-protected-identity', 'independent-sessions',
  'origin-and-csrf-rejection', 'owner-and-tenant-isolation', 'authorization-before-list-totals',
  'typed-filter-sort-pagination', 'strict-raw-query-errors', 'logout-revokes-copied-cookie',
];
const run = (args, cwd) => spawnSync(process.execPath, [CLI, ...args], { cwd, encoding: 'utf8', timeout: 10000 });
const temporary = body => {
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-core-workflow-')));
  try { return body(scratch); }
  finally { rmSync(scratch, { recursive: true, force: true }); }
};
const initArgs = (source, dest, stack = 'python') => ['init', '--template', 'core', '--source', source, '--stack', stack, '--dest', dest];
const imported = source => join(source, 'core-generator-imported.txt');

function coreReceipt(source, stack = 'python') {
  const dependencyOrigins = Object.fromEntries([
    ['auth', join(source, CORE_AUTH_ROOTS[stack])], ['core', join(source, 'libraries/' + stack)],
  ].map(([name, expectedPath]) => [name, { kind: 'source', expectedPath, resolvedPath: expectedPath, verified: true, method: 'isolated CLI boundary fixture' }]));
  return { schemaVersion: 1, template: 'core', coreCheckProtocolVersion: 1, features: CORE_FEATURES, profiles: CORE_PROFILES,
    stack, profile: CORE_PROFILES.auth, passed: true, checks: CORE_REQUIRED_CHECKS, dependencyOrigins, database: { used: false, isolated: false } };
}

// This fake boundary proves CLI delegation and receipt validation only. It does
// not build SDKs, start an HTTP listener, or provide runtime-conformance evidence.
function coreSource(directory, options = {}) {
  const source = fixtureSource(directory);
  for (const file of CORE_MANIFESTS) {
    mkdirSync(dirname(join(source, file)), { recursive: true });
    copyFileSync(join(ROOT, file), join(source, file));
  }
  const main = join(source, 'packages/feature-standards');
  mkdirSync(join(main, 'src'), { recursive: true });
  writeFileSync(join(main, 'package.json'), JSON.stringify({ name: 'feature-standards', version: '0.4.0', type: 'module', featureStandards: { coreStarterProtocolVersion: 1 }, ...options.packageMetadata }));
  const markers = { python: ['feature_auth/__init__.py', 'feature_standards/__init__.py'], go: ['auth/server.go', 'authorization/policy.go'], java: ['pom.xml', 'pom.xml'], rust: ['Cargo.toml', 'src/lib.rs'] };
  for (const stack of CORE_STACKS) for (const [base, marker] of [[CORE_AUTH_ROOTS[stack], markers[stack][0]], ['libraries/' + stack, markers[stack][1]]]) {
    mkdirSync(dirname(join(source, base, marker)), { recursive: true });
    writeFileSync(join(source, base, marker), 'fixture source marker\n');
  }
  writeFileSync(join(main, 'src/core-generator.mjs'), `
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
const source = ${JSON.stringify(source)};
const roots = ${JSON.stringify(CORE_AUTH_ROOTS)};
const features = ${JSON.stringify(CORE_FEATURES)};
const profiles = ${JSON.stringify(CORE_PROFILES)};
const manifests = ${JSON.stringify(CORE_MANIFESTS)};
writeFileSync(join(source, 'core-generator-imported.txt'), 'selected core generator imported');
export function generateCore(options) {
  mkdirSync(options.dest);
  const dependencies = { auth: { path: relative(options.dest, join(source, roots[options.stack])) }, core: { path: relative(options.dest, join(source, 'libraries/' + options.stack)) } };
  const sourceManifestsSha256 = Object.fromEntries(manifests.map(file => [file, createHash('sha256').update(readFileSync(join(source, file))).digest('hex')]));
  const metadata = { generator: 'feature-standards', generatorVersion: '0.4.0', template: 'core', coreCheckProtocolVersion: 1,
    stack: options.stack, profile: 'browser-session-v1', features, profiles, source: relative(options.dest, source), sourceCommit: null, sourceManifestsSha256, dependencies };
  writeFileSync(join(options.dest, 'feature-core.json'), JSON.stringify(metadata));
  const dependencyOrigins = Object.fromEntries(Object.entries(dependencies).map(([name, dependency]) => {
    const expectedPath = join(source, name === 'auth' ? roots[options.stack] : 'libraries/' + options.stack);
    return [name, { kind: 'source', expectedPath, resolvedPath: expectedPath, verified: true, method: 'isolated CLI boundary fixture' }];
  }));
  const receipt = ${options.receipt ? JSON.stringify(options.receipt) : 'undefined'} ?? { schemaVersion: 1, template: 'core', coreCheckProtocolVersion: 1,
    stack: options.stack, profile: 'browser-session-v1', features, profiles, passed: true, checks: ${JSON.stringify(CORE_REQUIRED_CHECKS)}, dependencyOrigins, database: { used: false, isolated: false } };
  const runner = "import {writeFileSync} from 'node:fs'; import {join} from 'node:path'; import {fileURLToPath} from 'node:url';\\n"
    + "writeFileSync(fileURLToPath(new URL('./runner-imported.txt', import.meta.url)), 'explicit runner import');\\n"
    + "export async function runProject(mode, directory) { if (mode !== 'check') throw new Error('unexpected-mode'); writeFileSync(join(directory, 'check-ran.txt'), 'explicit core check'); return " + JSON.stringify(receipt) + "; }\\n";
  writeFileSync(join(options.dest, 'project.mjs'), runner);
  return { template: 'core', stack: options.stack, profile: 'browser-session-v1', features, profiles, destination: options.dest, files: ['feature-core.json', 'project.mjs'] };
}
`);
  return source;
}

test('core init delegates to the selected source generator without checking by default', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source checkout'));
  const dest = join(scratch, 'new core app');
  const result = run(initArgs(source, dest), scratch);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.template, 'core');
  assert.deepEqual(output.features, CORE_FEATURES);
  assert.deepEqual(output.profiles, CORE_PROFILES);
  assert.equal(output.check.executed, false);
  assert.ok(existsSync(imported(source)));
  assert.ok(!existsSync(join(source, 'generator-imported.txt')), 'auth-only generator remains unused');
  assert.ok(existsSync(join(dest, 'feature-core.json')));
  assert.ok(!existsSync(join(dest, 'feature-auth.json')));
  assert.ok(!existsSync(join(dest, 'check-ran.txt')));
  assert.ok(!existsSync(join(dest, 'runner-imported.txt')));
}));

test('explicit core checks accept all three features and the complete checked SDK origins', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source'));
  for (const stack of CORE_STACKS) {
    const dest = join(scratch, stack + '-app');
    const initialized = run([...initArgs(source, dest, stack), '--profile', CORE_PROFILES.auth, '--check'], scratch);
    assert.equal(initialized.status, 0, initialized.stderr);
    const output = JSON.parse(initialized.stdout);
    assert.equal(output.check.executed, true);
    assert.equal(output.check.template, 'core');
    assert.equal(output.check.stack, stack);
    assert.deepEqual(output.check.features, CORE_FEATURES);
    assert.deepEqual(output.check.profiles, CORE_PROFILES);
    assert.deepEqual(output.check.checks, CORE_REQUIRED_CHECKS);
    assert.deepEqual(output.check.database, { used: false, isolated: false });
    for (const [name, root] of [['auth', CORE_AUTH_ROOTS[stack]], ['core', 'libraries/' + stack]]) {
      assert.equal(output.check.dependencyOrigins[name].verified, true);
      assert.equal(output.check.dependencyOrigins[name].expectedPath, join(source, root));
      assert.equal(output.check.dependencyOrigins[name].resolvedPath, join(source, root));
    }
    const checked = run(['check', '--project', dest], scratch);
    assert.equal(checked.status, 0, checked.stderr);
    assert.equal(JSON.parse(checked.stdout).template, 'core');
    assert.ok(existsSync(join(dest, 'check-ran.txt')));
  }
}));

test('invalid or ambiguous core selections fail before source import or destination creation', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source'));
  const dest = join(scratch, 'not-created');
  for (const args of [
    [...initArgs(source, dest), '--feature', 'auth'],
    [...initArgs(source, dest), '--feature', 'authorization'],
    [...initArgs(source, dest), '--profile', 'browser-session-v2'],
    [...initArgs(source, dest), '--profile', 'browser-session-v3'],
    [...initArgs(source, dest), '--profile', 'postgres-list-v1'],
    initArgs(source, dest, 'react'),
    ['init', '--template', 'other', '--source', source, '--stack', 'python', '--dest', dest],
    [...initArgs(source, dest), '--template', 'core'],
    [...initArgs(source, dest), '--check', '--check'],
  ]) {
    const result = run(args, scratch);
    assert.equal(result.status, 1, args.join(' '));
    assert.equal(result.stdout, '');
    assert.ok(!existsSync(imported(source)));
    assert.ok(!existsSync(join(source, 'generator-imported.txt')));
    assert.ok(!existsSync(dest));
  }
}));

test('core source identity and protocol capability are required before import', () => temporary(scratch => {
  const invalid = [
    { name: 'another-package' },
    { featureStandards: undefined },
    { featureStandards: { coreStarterProtocolVersion: 0 } },
    { featureStandards: { coreStarterProtocolVersion: 2 } },
  ];
  invalid.forEach((packageMetadata, index) => {
    const source = coreSource(join(scratch, 'source-' + index), { packageMetadata });
    const dest = join(scratch, 'not-created-' + index);
    const result = run(initArgs(source, dest), scratch);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /capability/);
    assert.equal(result.stdout, '');
    assert.ok(!existsSync(imported(source)));
    assert.ok(!existsSync(dest));
  });
}));

test('core destinations preserve existing files and refuse source descendants or linked parents', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source'));
  const existing = join(scratch, 'existing-app');
  mkdirSync(existing); writeFileSync(join(existing, 'mine.txt'), 'preserve');
  const file = join(scratch, 'existing-file'); writeFileSync(file, 'original');
  const dangling = join(scratch, 'dangling'); symlinkSync(join(scratch, 'missing'), dangling);
  const physical = join(scratch, 'physical-parent'); mkdirSync(physical);
  const linked = join(scratch, 'linked-parent'); symlinkSync(physical, linked, 'dir');
  for (const dest of [existing, file, dangling, join(source, 'inside'), join(linked, 'app')]) {
    const result = run(initArgs(source, dest), scratch);
    assert.equal(result.status, 1);
    assert.equal(result.stdout, '');
    assert.ok(!existsSync(imported(source)));
  }
  assert.equal(readFileSync(join(existing, 'mine.txt'), 'utf8'), 'preserve');
  assert.equal(readFileSync(file, 'utf8'), 'original');
  assert.ok(!existsSync(join(source, 'inside')));
  assert.ok(!existsSync(join(physical, 'app')));
}));

test('linked core source generators cannot redirect the CLI into outside code', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source'));
  const outside = join(scratch, 'outside.mjs');
  const outsideMarker = join(scratch, 'outside-imported.txt');
  writeFileSync(outside, `import {writeFileSync} from 'node:fs'; writeFileSync(${JSON.stringify(outsideMarker)}, 'must not run');`);
  const generator = join(source, 'packages/feature-standards/src/core-generator.mjs');
  rmSync(generator); symlinkSync(outside, generator);
  const dest = join(scratch, 'not-created');
  const result = run(initArgs(source, dest), scratch);
  assert.equal(result.status, 1);
  assert.ok(!existsSync(outsideMarker));
  assert.ok(!existsSync(dest));
}));

test('ambiguous auth and core project metadata is refused before importing its runner', () => temporary(scratch => {
  const source = coreSource(join(scratch, 'source'));
  const dest = join(scratch, 'new-app');
  const initialized = run(initArgs(source, dest), scratch);
  assert.equal(initialized.status, 0, initialized.stderr);
  writeFileSync(join(dest, 'feature-auth.json'), JSON.stringify({ generator: '@ugauga/create-feature-auth', generatorVersion: '0.2.0', checkProtocolVersion: 1,
    stack: 'python', profile: CORE_PROFILES.auth, source: relative(dest, source) }));
  const result = run(['check', '--project', dest], scratch);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /ambiguous/);
  assert.ok(!existsSync(join(dest, 'runner-imported.txt')));
  assert.ok(!existsSync(join(dest, 'check-ran.txt')));
}));

test('auth-only and incomplete core receipts cannot establish a three-feature check', () => temporary(scratch => {
  const cases = [
    ['auth-only', () => fixtureReceipt()],
    ['wrong-template', base => ({ ...base, template: 'auth' })],
    ['wrong-profile', base => ({ ...base, profile: 'browser-session-v2' })],
    ['wrong-stack', base => ({ ...base, stack: 'go' })],
    ['not-passed', base => ({ ...base, passed: false })],
    ['missing-feature', base => ({ ...base, features: ['auth', 'authorization'] })],
    ['wrong-feature-profile', base => ({ ...base, profiles: { ...base.profiles, listing: 'postgres-list-v1' } })],
    ['database-claim', base => ({ ...base, database: { used: true, isolated: true } })],
    ...CORE_REQUIRED_CHECKS.map(name => ['missing-' + name, base => ({ ...base, checks: base.checks.filter(check => check !== name) })]),
  ];
  for (const [name, change] of cases) {
    const sourcePath = join(scratch, 'source-' + name);
    const receipt = change(coreReceipt(sourcePath));
    const source = coreSource(sourcePath, { receipt });
    const dest = join(scratch, 'app-' + name);
    const result = run([...initArgs(source, dest), '--check'], scratch);
    assert.equal(result.status, 1, name);
    assert.match(result.stderr, /receipt/, name);
    assert.equal(result.stdout, '', name);
    assert.ok(existsSync(join(dest, 'check-ran.txt')), 'only the explicit fake check ran');
    assert.ok(existsSync(join(dest, 'feature-core.json')), 'a failed check preserves the generated project');
  }
}));

test('SDK origin receipts must be verified and match the recorded source dependencies', () => temporary(scratch => {
  const cases = [
    ['auth-unverified', base => ({ ...base.dependencyOrigins, auth: { ...base.dependencyOrigins.auth, verified: false } })],
    ['core-unverified', base => ({ ...base.dependencyOrigins, core: { ...base.dependencyOrigins.core, verified: false } })],
    ['auth-resolved-elsewhere', base => ({ ...base.dependencyOrigins, auth: { ...base.dependencyOrigins.auth, resolvedPath: join(scratch, 'other-sdk') } })],
    ['core-resolved-elsewhere', base => ({ ...base.dependencyOrigins, core: { ...base.dependencyOrigins.core, resolvedPath: join(scratch, 'other-sdk') } })],
    ['forged-matching-origin', base => ({ ...base.dependencyOrigins, auth: { ...base.dependencyOrigins.auth, expectedPath: scratch, resolvedPath: scratch } })],
    ['registry-origin', base => ({ ...base.dependencyOrigins, core: { ...base.dependencyOrigins.core, kind: 'registry' } })],
    ['missing-core-origin', base => ({ auth: base.dependencyOrigins.auth })],
  ];
  for (const [name, change] of cases) {
    const sourcePath = join(scratch, 'source-' + name);
    const receipt = coreReceipt(sourcePath);
    receipt.dependencyOrigins = change(receipt);
    const source = coreSource(sourcePath, { receipt });
    const dest = join(scratch, 'app-' + name);
    const result = run([...initArgs(source, dest), '--check'], scratch);
    assert.equal(result.status, 1, name);
    assert.match(result.stderr, /receipt/, name);
    assert.equal(result.stdout, '', name);
    assert.ok(existsSync(join(dest, 'check-ran.txt')));
  }
}));

test('changed core dependency metadata and source manifests fail before runner import', () => temporary(scratch => {
  for (const change of ['dependency', 'manifest']) {
    const source = coreSource(join(scratch, 'source-' + change));
    const dest = join(scratch, 'app-' + change);
    const initialized = run(initArgs(source, dest), scratch);
    assert.equal(initialized.status, 0, initialized.stderr);
    if (change === 'dependency') {
      const file = join(dest, 'feature-core.json');
      const metadata = JSON.parse(readFileSync(file, 'utf8'));
      metadata.dependencies.core.path = relative(dest, join(source, CORE_AUTH_ROOTS.python));
      writeFileSync(file, JSON.stringify(metadata));
    } else {
      const file = join(source, 'features/listing/catalog.json');
      writeFileSync(file, readFileSync(file, 'utf8') + '\n');
    }
    const result = run(['check', '--project', dest], scratch);
    assert.equal(result.status, 1, change);
    assert.ok(!existsSync(join(dest, 'runner-imported.txt')));
    assert.ok(!existsSync(join(dest, 'check-ran.txt')));
  }
}));
