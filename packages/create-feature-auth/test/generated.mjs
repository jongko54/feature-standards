import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = resolve(PACKAGE, '../..');
const directory = realpathSync(mkdtempSync(join(tmpdir(), 'feature-auth-generated-')));
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
try {
  for (const stack of ['python', 'go', 'java', 'rust']) {
    // Exercise one selected DB profile too; --check must still use memory and never touch a DB.
    const profile = stack === 'go' ? 'browser-session-v3' : 'browser-session-v1';
    const result = spawnSync(process.execPath, [join(PACKAGE, 'src/cli.mjs'), '--source', ROOT, '--stack', stack, '--profile', profile, '--dest', join(directory, stack), '--check'], { stdio: 'inherit', env: process.env, timeout: 600000 });
    assert.equal(result.status, 0, stack + ' generated consumer failed: ' + (result.error?.code || 'command exit'));
  }
  assert.deepEqual(fingerprint(join(ROOT, 'implementations')), before, 'source implementation files must remain unchanged');
  console.log('All four generated consumers passed builds and memory HTTP lifecycle; source fingerprints unchanged.');
} finally { rmSync(directory, { recursive: true, force: true }); }
