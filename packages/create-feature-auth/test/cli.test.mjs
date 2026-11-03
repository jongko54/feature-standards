import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { generate, inspect, parseArguments, PROFILES, STACKS } from '../src/cli.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const scratch = () => realpathSync(mkdtempSync(join(tmpdir(), 'feature-auth-cli-unit-')));
const options = (directory, values = {}) => ({ source: ROOT, stack: 'python', profile: 'browser-session-v1', dest: join(directory, 'app'), ...values });
const files = directory => readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(directory, entry.name)).map(path => entry.name + '/' + path) : [entry.name]);

test('all stacks and profiles generate only thin, relative consumers without contacting a database', () => {
  const directory = scratch();
  try {
    for (const stack of Object.keys(STACKS)) for (const profile of PROFILES) {
      const target = join(directory, stack + '-' + profile);
      const result = generate(options(directory, { stack, profile, dest: target }));
      const metadata = JSON.parse(readFileSync(join(target, 'feature-auth.json'), 'utf8'));
      assert.equal(metadata.profile, profile);
      assert.equal(metadata.generatorVersion, JSON.parse(readFileSync(join(ROOT, 'packages/create-feature-auth/package.json'), 'utf8')).version);
      assert.equal(resolve(target, metadata.source), ROOT);
      assert.match(metadata.sourceManifestSha256, /^[a-f0-9]{64}$/);
      assert.ok(result.files.includes('project.mjs'));
      assert.ok(!files(target).some(path => /(^|\/)(feature_auth|auth|tests|target|node_modules|__pycache__)(\/|$)/.test(path)));
      assert.ok(!files(target).includes('.env'));
      assert.match(readFileSync(join(target, '.env.example'), 'utf8'), /AUTH_DEMO=false/);
      const dependencyFile = { python: 'pyproject.toml', go: 'go.mod', java: 'pom.xml', rust: 'Cargo.toml' }[stack];
      const dependency = readFileSync(join(target, dependencyFile), 'utf8');
      assert.ok(!dependency.includes('"' + ROOT) && !dependency.includes('>' + ROOT));
      if (stack === 'java') assert.match(readFileSync(join(target, 'pom.xml'), 'utf8'), /io\.github\.jongko54/);
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('existing directory and file remain byte-for-byte unchanged', () => {
  const directory = scratch();
  try {
    const target = join(directory, 'app'); mkdirSync(target);
    writeFileSync(join(target, 'mine.txt'), 'keep');
    assert.throws(() => generate(options(directory)), /destination-already-exists/);
    assert.deepEqual(files(target), ['mine.txt']);
    assert.equal(readFileSync(join(target, 'mine.txt'), 'utf8'), 'keep');
    const file = join(directory, 'file'); writeFileSync(file, 'original');
    assert.throws(() => generate(options(directory, { dest: file })), /destination-already-exists/);
    assert.equal(readFileSync(file, 'utf8'), 'original');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('dangling destination and symlinked parent are refused', () => {
  const directory = scratch();
  try {
    symlinkSync(join(directory, 'missing'), join(directory, 'app'));
    assert.throws(() => generate(options(directory)), /destination-already-exists/);
    const outside = join(directory, 'outside'); mkdirSync(outside);
    const link = join(directory, 'link'); symlinkSync(outside, link, 'dir');
    assert.throws(() => generate(options(directory, { dest: join(link, 'new') })), /destination-symlink/);
    assert.deepEqual(readdirSync(outside), []);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('source traversal and destination inside the checkout cannot write files', () => {
  const directory = scratch();
  try {
    assert.throws(() => inspect(options(directory, { dest: join(ROOT, 'generated-must-not-exist') })), /destination-inside-source/);
    assert.ok(!existsSync(join(ROOT, 'generated-must-not-exist')));
    const source = join(directory, 'source'); mkdirSync(source);
    copyFileSync(join(ROOT, 'feature-standards.json'), join(source, 'feature-standards.json'));
    mkdirSync(join(source, 'implementations/python-fastapi'), { recursive: true });
    const outside = join(directory, 'outside'); mkdirSync(outside); writeFileSync(join(outside, '__init__.py'), 'outside');
    symlinkSync(outside, join(source, 'implementations/python-fastapi/feature_auth'), 'dir');
    assert.throws(() => generate(options(directory, { source })), /source-file-escape/);
    assert.ok(!existsSync(join(directory, 'app')));
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('unsupported selections and malformed manifest fail before creating a target', () => {
  const directory = scratch();
  try {
    assert.throws(() => generate(options(directory, { stack: 'react' })), /unsupported-stack/);
    assert.throws(() => generate(options(directory, { profile: 'custom' })), /unsupported-profile/);
    assert.throws(() => generate(options(directory, { dest: 'bad\npath' })), /invalid-path/);
    const source = join(directory, 'source'); mkdirSync(source);
    writeFileSync(join(source, 'feature-standards.json'), JSON.stringify({ feature: 'auth', schema_version: 1, stacks: [{ id: 'python', root: STACKS.python }], profiles: [{ id: PROFILES[0] }] }));
    assert.throws(() => generate(options(directory, { source })), /unsupported-source-manifest/);
    assert.ok(!existsSync(join(directory, 'app')));
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('CLI parsing requires an explicit source and rejects ambiguous arguments', () => {
  assert.throws(() => parseArguments(['--stack', 'go', '--dest', 'app']), /source-stack-dest-required/);
  assert.throws(() => parseArguments(['--source', '--stack', 'go']), /missing-argument-value/);
  assert.throws(() => parseArguments(['--yes']), /unknown-argument/);
  assert.throws(() => parseArguments(['--source', 'a', '--source', 'b']), /duplicate-argument/);
  assert.equal(parseArguments(['--source', 'a', '--stack', 'go', '--dest', 'app']).profile, PROFILES[0]);
  assert.deepEqual(parseArguments(['--help']), { help: true });
});

test('npm-style symlink executable actually runs the CLI and creates its project', () => {
  const directory = scratch();
  try {
    const executable = join(directory, 'create-feature-auth');
    symlinkSync(join(ROOT, 'packages/create-feature-auth/src/cli.mjs'), executable);
    const result = spawnSync(process.execPath, [executable, '--source', ROOT, '--stack', 'go', '--dest', join(directory, 'app')], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.ok(existsSync(join(directory, 'app/main.go')), 'symlink entry must generate the app');
    assert.equal(JSON.parse(result.stdout).stack, 'go');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
