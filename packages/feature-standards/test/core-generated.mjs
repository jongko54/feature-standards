import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstatSync, mkdtempSync, readFileSync, readdirSync, readlinkSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CORE_CHECK_PROTOCOL_VERSION, CORE_FEATURES, CORE_PROFILES, CORE_REQUIRED_CHECKS, CORE_STACKS } from '../src/core-protocol.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const options = { source: ROOT, cli: join(ROOT, 'packages/feature-standards/src/cli.mjs'), stack: 'all' };
const seen = new Set();
for (let index = 2; index < process.argv.length; index++) {
  const argument = process.argv[index];
  const value = process.argv[++index];
  if (!['--source', '--cli', '--stack'].includes(argument) || !value || value.startsWith('--') || seen.has(argument)) throw new Error('usage: core-generated.mjs [--cli PHYSICAL_CLI] [--source CHECKOUT] [--stack python|go|java|rust|all]');
  seen.add(argument); options[argument.slice(2)] = value;
}
if (![...CORE_STACKS, 'all'].includes(options.stack)) throw new Error('unsupported-core-stack');
for (const field of ['source', 'cli']) {
  const requested = resolve(options[field]);
  if (realpathSync(requested) !== requested || lstatSync(requested).isSymbolicLink()) throw new Error(field + '-must-be-physical');
  options[field] = requested;
}
if (!lstatSync(options.source).isDirectory() || !lstatSync(options.cli).isFile()) throw new Error('invalid-core-integration-input');

const ignored = new Set(['.venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'target', 'node_modules']);
function fingerprint(path, prefix = '') {
  return readdirSync(path, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name)).flatMap(entry => {
    if (ignored.has(entry.name)) return [];
    const name = prefix + entry.name;
    if (entry.isDirectory()) return fingerprint(join(path, entry.name), name + '/');
    if (entry.isSymbolicLink()) return [[name, 'link:' + readlinkSync(join(path, entry.name))]];
    if (!entry.isFile()) throw new Error('unsupported-core-source-entry');
    return [[name, createHash('sha256').update(readFileSync(join(path, entry.name))).digest('hex')]];
  });
}
const before = Object.fromEntries(['implementations', 'libraries'].map(directory => [directory, fingerprint(join(options.source, directory))]));
const directory = realpathSync(mkdtempSync(join(tmpdir(), 'feature-core-generated-')));
const receipts = [];
function cli(argv) {
  const child = spawnSync(process.execPath, [options.cli, ...argv], { encoding: 'utf8', env: process.env, stdio: ['ignore', 'pipe', 'inherit'], timeout: 1200000, maxBuffer: 16 * 1024 * 1024 });
  assert.equal(child.status, 0, 'core CLI command failed: ' + argv[0]);
  // Native tool output can precede the final structured CLI result.
  for (let offset = child.stdout.lastIndexOf('{'); offset >= 0; offset = offset === 0 ? -1 : child.stdout.lastIndexOf('{', offset - 1)) {
    try { return JSON.parse(child.stdout.slice(offset)); } catch { /* Try the enclosing final object. */ }
  }
  throw new Error('core-cli-json-result-missing');
}
try {
  for (const stack of options.stack === 'all' ? CORE_STACKS : [options.stack]) {
    const destination = join(directory, stack + ' app');
    const generated = cli(['init', '--template', 'core', '--source', options.source, '--stack', stack, '--dest', destination]);
    assert.equal(generated.template, 'core'); assert.equal(generated.stack, stack);
    assert.equal(generated.check?.executed, false);
    const receipt = cli(['check', '--project', destination]);
    assert.equal(receipt.schemaVersion, 1); assert.equal(receipt.template, 'core');
    assert.equal(receipt.coreCheckProtocolVersion, CORE_CHECK_PROTOCOL_VERSION); assert.equal(receipt.stack, stack);
    assert.equal(receipt.profile, CORE_PROFILES.auth); assert.deepEqual(receipt.features, CORE_FEATURES); assert.deepEqual(receipt.profiles, CORE_PROFILES);
    assert.equal(receipt.passed, true); assert.equal(receipt.executed, true);
    assert.equal(receipt.database.used, false); assert.equal(receipt.database.isolated, false);
    assert.ok(CORE_REQUIRED_CHECKS.every(check => receipt.checks.includes(check)));
    for (const dependency of ['auth', 'core']) {
      const origin = receipt.dependencyOrigins[dependency];
      assert.equal(origin.kind, 'source'); assert.equal(origin.verified, true); assert.equal(origin.expectedPath, origin.resolvedPath);
    }
    receipts.push(receipt);
    console.log(JSON.stringify(receipt));
  }
} finally {
  try {
    for (const entry of ['implementations', 'libraries']) assert.deepEqual(fingerprint(join(options.source, entry)), before[entry], entry + ' source fingerprints changed');
  } finally { rmSync(directory, { recursive: true, force: true }); }
}
console.log(JSON.stringify({ template: 'core', cli: options.cli, source: options.source, generatedConsumers: receipts.length, realBuildAndHttpChecks: receipts.length, sourceFingerprintsUnchanged: true, browserChecked: false, databaseUsed: false }));
