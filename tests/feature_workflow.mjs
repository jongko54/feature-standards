// Exercise the installed main package through real generated applications.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
assert.equal(argv.length, 2, 'usage: node tests/feature_workflow.mjs --tarball ABSOLUTE_ARCHIVE');
assert.equal(argv[0], '--tarball');
assert.ok(isAbsolute(argv[1]) && existsSync(argv[1]), 'provide the exact reviewed tarball');
assert.ok(process.env.FEATURE_STANDARDS_TEST_DATABASE_URL, 'an explicit dedicated test database URL is required');
const archive = realpathSync(argv[1]);
const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-workflow-installed-')));

function run(program, args, cwd, timeout = 600_000) {
  const result = spawnSync(program, args, {
    cwd, env: process.env, encoding: 'utf8', timeout, maxBuffer: 8 * 1024 * 1024,
  });
  // Build/runtime diagnostics can contain private configuration. Never echo them.
  assert.ok(!result.error && result.status === 0,
    `installed workflow command failed: ${program === 'npm' ? 'installation' : args[0]} (exit ${result.status})`);
  return result.stdout;
}

function finalJson(output) {
  for (let offset = output.length - 1; offset >= 0; offset--) {
    if (output[offset] !== '{') continue;
    try { return JSON.parse(output.slice(offset)); } catch { /* Skip inner objects/build output. */ }
  }
  throw new Error('workflow did not emit a final JSON result');
}

function sourceFingerprint() {
  const tracked = run('git', ['ls-files', '-z', '--', 'implementations'], ROOT, 10_000);
  return tracked.split('\0').filter(Boolean).map(path => [
    path, createHash('sha256').update(readFileSync(join(ROOT, path))).digest('hex'),
  ]);
}

try {
  const before = sourceFingerprint();
  const consumer = join(scratch, 'consumer');
  mkdirSync(consumer);
  writeFileSync(join(consumer, 'package.json'), JSON.stringify({ name: 'installed-feature-workflow', private: true, type: 'module' }));
  run('npm', ['install', '--offline', '--ignore-scripts', '--no-audit', '--no-fund', '--cache', join(scratch, 'empty-cache'), archive], consumer, 120_000);
  const binary = join(consumer, 'node_modules', '.bin', 'feature-standards');
  const catalog = finalJson(run(binary, ['list'], consumer, 10_000));
  assert.equal(catalog.features[0].id, 'auth');
  let generated = 0;
  const projects = new Map();
  for (const stack of ['python', 'go', 'java', 'rust']) {
    for (const profile of ['browser-session-v1', 'browser-session-v2', 'browser-session-v3']) {
      const destination = join(scratch, stack + '-' + profile);
      run(binary, ['init', '--feature', 'auth', '--source', ROOT, '--stack', stack, '--profile', profile, '--dest', destination], consumer, 30_000);
      const metadata = JSON.parse(readFileSync(join(destination, 'feature-auth.json'), 'utf8'));
      assert.equal(metadata.stack, stack);
      assert.equal(metadata.profile, profile);
      assert.equal(metadata.checkProtocolVersion, 1);
      projects.set(stack + ':' + profile, destination);
      generated++;
    }
  }
  const checked = [];
  for (const [stack, profile] of [
    ['python', 'browser-session-v1'], ['go', 'browser-session-v2'], ['python', 'browser-session-v3'],
  ]) {
    const result = finalJson(run(binary, ['check', '--project', projects.get(stack + ':' + profile)], consumer));
    assert.equal(result.schemaVersion, 1);
    assert.equal(result.stack, stack);
    assert.equal(result.profile, profile);
    assert.equal(result.passed, true);
    assert.ok(Array.isArray(result.checks) && result.checks.length > 0);
    checked.push({ stack, profile, checks: result.checks });
  }
  assert.deepEqual(sourceFingerprint(), before, 'installed workflow modified server library sources');
  console.log(JSON.stringify({ installedPackage: 'feature-standards', freshOfflineInstall: true, generated, checked, sourceImplementationsUnchanged: true }, null, 2));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
