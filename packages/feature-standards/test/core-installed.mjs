// Real tarball + fresh installation + generated TCP applications; no publication.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = resolve(PACKAGE, '../..');
const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-core-installed-')));
const arguments_ = process.argv.slice(2);
assert.ok(arguments_.length === 0 || (arguments_.length === 2 && arguments_[0] === '--stack' && ['python', 'go', 'java', 'rust', 'all'].includes(arguments_[1])), 'use --stack python|go|java|rust|all');
function run(command, args, cwd, timeout = 180000) {
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', timeout, maxBuffer: 16 * 1024 * 1024 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr + '\n' + result.stdout);
  return result.stdout;
}
try {
  const packed = JSON.parse(run('npm', ['pack', '--json', '--pack-destination', scratch], PACKAGE))[0];
  const artifact = join(scratch, packed.filename);
  const consumer = join(scratch, 'consumer');
  mkdirSync(consumer);
  writeFileSync(join(consumer, 'package.json'), JSON.stringify({ private: true }));
  run('npm', ['install', '--offline', '--ignore-scripts', '--no-audit', '--no-fund', artifact], consumer);
  const cli = realpathSync(join(consumer, 'node_modules/.bin/feature-standards'));
  const result = run(process.execPath, [join(PACKAGE, 'test/core-generated.mjs'), '--cli', cli, '--source', ROOT, ...arguments_], consumer, 1800000);
  process.stdout.write(result);
  console.log(JSON.stringify({ package: 'feature-standards', freshOfflineInstall: true, realCoreGeneratedApplications: true,
    artifactSha256: createHash('sha256').update(readFileSync(artifact)).digest('hex'), registryPublished: false }));
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
