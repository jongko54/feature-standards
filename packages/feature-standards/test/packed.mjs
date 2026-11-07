import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SOURCE_FILES } from '../scripts/build.mjs';
import { fixtureSource } from './workflow-fixture.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-standards-pack-')));
const expectedFiles = ['package.json', 'README.md', 'LICENSE', 'src/cli.mjs', 'src/index.mjs', 'src/workflow.mjs', 'snapshot/provenance.json', ...SOURCE_FILES.map(path => 'snapshot/' + path)].sort();
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const run = (command, argv, cwd = PACKAGE, env = process.env) => {
  const result = spawnSync(command, argv, { cwd, env, encoding: 'utf8', timeout: 120000, maxBuffer: 8 * 1024 * 1024 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, command + ' ' + argv.join(' ') + '\n' + result.stderr + '\n' + result.stdout);
  return result.stdout;
};
const files = root => readdirSync(root, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(root, entry.name)).map(path => entry.name + '/' + path) : [entry.name]);

try {
  // Stale/unexpected files in the generated tree must not survive a real prepack.
  const unexpected = join(PACKAGE, 'snapshot', 'must-not-ship.raw-trace');
  mkdirSync(dirname(unexpected), { recursive: true });
  writeFileSync(unexpected, 'not part of the allowlist');
  const [packed] = JSON.parse(run('npm', ['pack', '--json', '--pack-destination', scratch]));
  assert.deepEqual(packed.files.map(file => file.path).sort(), expectedFiles);
  assert.ok(!existsSync(unexpected));
  const tarball = join(scratch, packed.filename);
  const tarballSha256 = hash(readFileSync(tarball));
  const consumer = join(scratch, 'consumer');
  mkdirSync(consumer);
  writeFileSync(join(consumer, 'package.json'), JSON.stringify({ name: 'offline-feature-standards-consumer', private: true, type: 'module' }));
  const emptyCache = join(scratch, 'empty-cache');
  // No warm cache, registry lookup or lifecycle code is needed for this dependency-free artifact.
  run('npm', ['install', '--offline', '--ignore-scripts', '--no-audit', '--no-fund', '--cache', emptyCache, tarball], consumer);
  const installed = join(consumer, 'node_modules', 'feature-standards');
  assert.deepEqual(files(installed).sort(), expectedFiles);
  const metadata = JSON.parse(readFileSync(join(installed, 'package.json'), 'utf8'));
  assert.equal(metadata.name, 'feature-standards');
  assert.equal(metadata.version, JSON.parse(readFileSync(join(PACKAGE, 'package.json'), 'utf8')).version);
  assert.deepEqual(metadata.author, { name: 'jongko54', url: 'https://github.com/jongko54' });
  assert.equal(metadata.repository.directory, 'packages/feature-standards');
  for (const keyword of ['jongko54', 'ai', 'cross-language', 'contracts']) assert.ok(metadata.keywords.includes(keyword));
  assert.deepEqual(metadata.dependencies ?? {}, {});
  assert.deepEqual(metadata.optionalDependencies ?? {}, {});
  assert.deepEqual(metadata.peerDependencies ?? {}, {});
  const provenance = JSON.parse(readFileSync(join(installed, 'snapshot/provenance.json'), 'utf8'));
  assert.deepEqual(Object.keys(provenance.files).sort(), [...SOURCE_FILES].sort());
  for (const [path, record] of Object.entries(provenance.files)) {
    assert.equal(hash(readFileSync(join(installed, 'snapshot', path))), record.sha256);
    assert.equal(typeof record.sourceModified, 'boolean');
  }
  const bin = join(consumer, 'node_modules/.bin/feature-standards');
  const listed = JSON.parse(run(bin, ['list'], consumer));
  assert.deepEqual(listed.features.map(feature => feature.id), ['auth', 'authorization', 'listing']);
  assert.match(run(bin, ['--help'], consumer), /Read-only/);
  let contexts = 0;
  for (const feature of listed.features) for (const stack of feature.stacks) for (const profile of stack.profiles) {
    const context = JSON.parse(run(bin, ['context', '--feature', feature.id, '--stack', stack.id, '--profile', profile], consumer));
    assert.equal(context.feature, feature.id);
    assert.equal(context.stack.id, stack.id);
    assert.equal(context.profile, profile);
    assert.ok(context.packagedDocuments.specification.readPath.startsWith(installed + '/'));
    assert.ok(existsSync(context.packagedDocuments.specification.readPath));
    for (const entrypoint of context.sourceCheckout.entrypoints) assert.ok(!existsSync(join(installed, 'snapshot', entrypoint.checkoutPath)));
    contexts++;
  }
  assert.equal(contexts, 26);
  const imported = JSON.parse(run(process.execPath, ['--input-type=module', '-e', "import { listFeatures, getContext, getCompactContext } from 'feature-standards'; console.log(JSON.stringify({ feature: listFeatures().features[0].id, stack: getContext({ stack: 'rust' }).stack.id, mode: getCompactContext({ stack: 'rust' }).mode }));"], consumer));
  assert.deepEqual(imported, { feature: 'auth', stack: 'rust', mode: 'compact' });
  const source = fixtureSource(join(scratch, 'trusted-source'));
  const generated = join(scratch, 'generated-app');
  const initialized = JSON.parse(run(bin, ['init', '--source', source, '--stack', 'python', '--profile', 'browser-session-v3', '--dest', generated], consumer));
  assert.equal(initialized.profile, 'browser-session-v3');
  assert.equal(initialized.check.executed, false);
  assert.ok(!existsSync(join(generated, 'check-ran.txt')));
  const checked = JSON.parse(run(bin, ['check', '--project', generated], consumer));
  assert.equal(checked.profile, 'browser-session-v3');
  assert.equal(checked.database.used, true);
  assert.equal(checked.database.isolated, true);
  run(process.execPath, ['--input-type=module', '-e', "import assert from 'node:assert/strict'; import {initFeature,checkProject} from 'feature-standards'; assert.equal(typeof initFeature,'function'); assert.equal(typeof checkProject,'function');"], consumer);
  const refused = spawnSync(bin, ['context', '--stack', 'go', '--feature', 'unsupported'], { cwd: consumer, encoding: 'utf8' });
  assert.equal(refused.status, 1);
  assert.equal(refused.stdout, '');
  assert.match(refused.stderr, /unsupported-feature/);
  for (const feature of ['authorization', 'listing']) {
    const dest = join(scratch, 'unsupported-' + feature);
    const result = spawnSync(bin, ['init', '--feature', feature, '--stack', 'python', '--source', source, '--dest', dest], { cwd: consumer, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /unsupported-feature/);
    assert.ok(!existsSync(dest));
  }
  console.log(JSON.stringify({ package: metadata.name, version: metadata.version, files: expectedFiles.length, snapshotFiles: SOURCE_FILES.length, freshOfflineInstall: true, installedBin: true, contexts, nodeExports: true, explicitWorkflowFixture: true, realBackendTestedByThisSmoke: false, authorAndKeywords: true, sha256: tarballSha256, sourceCommit: provenance.sourceCommit, sourceDirty: provenance.sourceDirty, snapshotDirty: provenance.snapshotDirty }, null, 2));
} finally { rmSync(scratch, { recursive: true, force: true }); }
