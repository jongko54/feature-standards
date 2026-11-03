import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { generate } from '../src/cli.mjs';
import { validateTestDatabaseURL } from '../src/check-fixture.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = resolve(PACKAGE, '../..');
const ignored = new Set(['.venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'target', '.mvn', 'node_modules']);
function fingerprint(path, prefix = '') {
  return readdirSync(path, { withFileTypes: true }).flatMap(entry => {
    if (ignored.has(entry.name)) return [];
    const name = prefix + entry.name;
    if (entry.isDirectory()) return fingerprint(join(path, entry.name), name + '/');
    if (!entry.isFile()) return [];
    return [[name, createHash('sha256').update(readFileSync(join(path, entry.name))).digest('hex')]];
  });
}

const before = fingerprint(join(ROOT, 'implementations'));
const memoryOnly = process.argv.slice(2).join(' ') === '--memory-only';
if (process.argv.length > 2 && !memoryOnly) throw new Error('usage: generated.mjs [--memory-only]');
const profiles = memoryOnly ? ['browser-session-v1'] : ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'];
// Fail before writing generated projects or invoking any compiler.
if (!memoryOnly) validateTestDatabaseURL(process.env.FEATURE_STANDARDS_TEST_DATABASE_URL, process.env);
const directory = realpathSync(mkdtempSync(join(tmpdir(), 'feature-auth-generated-')));
const receipts = [];
try {
  if (!memoryOnly) {
    const environment = { ...process.env };
    delete environment.UV_PROJECT_ENVIRONMENT;
    const fixtureCheck = spawnSync('uv', ['run', '--frozen', '--project', join(ROOT, 'tools'), 'python', join(PACKAGE, 'test/check_db.py')], { env: environment, stdio: 'inherit', timeout: 120000 });
    assert.equal(fixtureCheck.status, 0, 'private database fixture safety checks failed');
  }
  for (const stack of ['python', 'go', 'java', 'rust']) {
    const destination = join(directory, stack);
    generate({ source: ROOT, stack, profile: profiles[0], dest: destination });
    const runner = await import(pathToFileURL(join(destination, 'project.mjs')).href);
    for (const profile of profiles) {
      // Profile selection is runtime metadata. Reuse this owned build directory so
      // every check still invokes a real build, with incremental compiler caches.
      const metadata = JSON.parse(readFileSync(join(destination, 'feature-auth.json'), 'utf8'));
      writeFileSync(join(destination, 'feature-auth.json'), JSON.stringify({ ...metadata, profile }, null, 2) + '\n');
      const receipt = await runner.runProject('check', destination);
      assert.equal(receipt.schemaVersion, 1);
      assert.equal(receipt.stack, stack);
      assert.equal(receipt.profile, profile);
      assert.equal(receipt.passed, true);
      assert.ok(receipt.checks.length > 0);
      assert.equal(receipt.database.used, profile !== 'browser-session-v1');
      if (receipt.database.used) {
        assert.equal(receipt.database.isolated, true);
        assert.equal(receipt.database.dropped, true);
        assert.equal(receipt.database.existingDatabaseModified, false);
      }
      receipts.push(receipt);
      console.log(JSON.stringify(receipt));
    }
  }
  assert.deepEqual(fingerprint(join(ROOT, 'implementations')), before, 'source implementation files must remain unchanged');
  console.log(JSON.stringify({ generatedConsumers: 4, selectedProfileChecks: receipts.length, realBuildInvocations: receipts.length, incrementalBuildDirectories: 4, sourceFingerprintsUnchanged: true, coldBuildForEveryProfile: false }));
} finally { rmSync(directory, { recursive: true, force: true }); }
