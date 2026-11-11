// Check the release artifact directly; this bootstrap has no runtime behavior to test.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPT = join(PACKAGE, 'scripts/pack-bootstrap.mjs');
const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-standards-bootstrap-check-')));
const mainBefore = readFileSync(join(PACKAGE, 'package.json'));
const main = JSON.parse(mainBefore);
const run = args => spawnSync(process.execPath, [SCRIPT, ...args], {
  cwd: scratch, encoding: 'utf8', timeout: 30000,
  env: { ...process.env, NPM_TOKEN: 'bootstrap-check-must-not-copy-this-value', NODE_AUTH_TOKEN: 'bootstrap-check-must-not-copy-this-value' },
});
const tar = args => {
  const result = spawnSync('tar', args, { encoding: 'utf8', timeout: 10000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
};

try {
  const output = join(scratch, 'output');
  mkdirSync(output, { mode: 0o700 });
  const result = run(['--out-dir', output]);
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.package, 'feature-standards');
  assert.equal(receipt.version, '0.0.0-bootstrap');
  assert.equal(receipt.tag, 'bootstrap');
  assert.equal(receipt.published, false);
  assert.match(receipt.sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(readdirSync(output), ['feature-standards-0.0.0-bootstrap.tgz']);
  const artifact = join(output, receipt.filename);
  const before = readFileSync(artifact);
  assert.deepEqual(tar(['-tzf', artifact]).trim().split('\n').sort(), ['package/LICENSE', 'package/README.md', 'package/package.json']);
  const metadataText = tar(['-xOf', artifact, 'package/package.json']);
  const metadata = JSON.parse(metadataText);
  assert.deepEqual(Object.keys(metadata).sort(), ['author', 'description', 'keywords', 'license', 'name', 'publishConfig', 'repository', 'version']);
  for (const key of ['author', 'keywords', 'repository', 'license']) assert.deepEqual(metadata[key], main[key]);
  assert.equal(metadata.name, main.name);
  assert.equal(metadata.version, '0.0.0-bootstrap');
  assert.equal(metadata.publishConfig.tag, 'bootstrap');
  assert.equal(metadata.publishConfig.registry, 'https://registry.npmjs.org/');
  for (const key of ['scripts', 'bin', 'exports', 'main', 'dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies']) assert.equal(metadata[key], undefined);
  assert.ok(!metadataText.includes(scratch) && !metadataText.includes(PACKAGE));
  assert.ok(!metadataText.includes('bootstrap-check-must-not-copy-this-value'));
  const readme = tar(['-xOf', artifact, 'package/README.md']);
  assert.match(readme, /temporary namespace and trusted-publisher bootstrap/);
  assert.match(readme, /feature-standards@0\.1\.0/);
  assert.match(readme, /no CLI, module exports, runtime/);
  assert.equal(tar(['-xOf', artifact, 'package/LICENSE']), readFileSync(join(PACKAGE, 'LICENSE'), 'utf8'));
  const repeated = run(['--out-dir', output]);
  assert.equal(repeated.status, 1);
  assert.match(repeated.stderr, /output-directory-not-empty/);
  assert.deepEqual(readFileSync(artifact), before);
  const nonempty = join(scratch, 'nonempty');
  mkdirSync(nonempty);
  writeFileSync(join(nonempty, 'keep.txt'), 'preserve');
  assert.equal(run(['--out-dir', nonempty]).status, 1);
  assert.equal(readFileSync(join(nonempty, 'keep.txt'), 'utf8'), 'preserve');
  const physical = join(scratch, 'physical');
  mkdirSync(physical);
  const link = join(scratch, 'link');
  symlinkSync(physical, link, 'dir');
  assert.equal(run(['--out-dir', link]).status, 1);
  assert.deepEqual(readdirSync(physical), []);
  assert.equal(run(['--out-dir', join(scratch, 'missing')]).status, 1);
  for (const args of [[], ['--publish'], ['--out-dir'], ['--out-dir', physical, '--publish']]) assert.equal(run(args).status, 1);
  assert.equal(run(['--help']).status, 0);
  assert.deepEqual(readFileSync(join(PACKAGE, 'package.json')), mainBefore);
  assert.match(main.version, /^\d+\.\d+\.\d+$/);
  assert.deepEqual(main.files, ['src/cli.mjs', 'src/index.mjs', 'src/workflow.mjs', 'src/core-generator.mjs', 'src/core-project.mjs', 'src/core-protocol.mjs', 'src/core-source.mjs', 'src/core-process.mjs', 'src/core-check.mjs', 'templates/core', 'snapshot', 'README.md', 'LICENSE']);
  console.log(JSON.stringify({ package: receipt.package, version: receipt.version, tag: receipt.tag, files: 3, artifactVerified: true, noRuntimeOrSecrets: true, preservesExistingOutput: true, mainVersion: main.version, mainPackWhitelistChecked: true, published: false, sha256: receipt.sha256 }, null, 2));
} finally { rmSync(scratch, { recursive: true, force: true }); }
