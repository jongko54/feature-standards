// Release engineering only. This script never authenticates or publishes a package.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, constants, copyFileSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VERSION = '0.0.0-bootstrap';
const FILENAME = 'feature-standards-' + VERSION + '.tgz';
const FILES = ['LICENSE', 'README.md', 'package.json'];
const KEYS = ['name', 'version', 'description', 'license', 'author', 'keywords', 'repository', 'publishConfig'];
const README = `# Feature Standards publisher bootstrap

This is a temporary namespace and trusted-publisher bootstrap release:
\`feature-standards@0.0.0-bootstrap\`, intended only for the \`bootstrap\` dist-tag.

It creates the npm package record needed before configuring the GitHub Actions
trusted publisher for the full release. It contains only package metadata,
this README, and the MIT license. It provides no CLI, module exports, runtime
code, or authentication implementation.

For reusable contracts and the JSON context CLI, use
\`feature-standards@0.1.0\` once its full publication is verified. See the
[main project](https://github.com/jongko54/feature-standards) for release status.
The bootstrap version does not represent the full package's behavior or tests.

Creating this archive is a local, offline packaging operation. Publishing it
under the bootstrap dist-tag is a separate explicit release action.

Created by [jongko54](https://github.com/jongko54). Licensed under MIT.
`;

function checkedMetadata(main) {
  assert.equal(main.name, 'feature-standards', 'unexpected-main-package-name');
  assert.match(main.version, /^\d+\.\d+\.\d+$/, 'unexpected-main-package-version');
  assert.equal(main.license, 'MIT', 'unexpected-main-license');
  assert.deepEqual(main.author, { name: 'jongko54', url: 'https://github.com/jongko54' });
  assert.deepEqual(main.repository, {
    type: 'git', url: 'git+https://github.com/jongko54/feature-standards.git', directory: 'packages/feature-standards',
  });
  assert.ok(Array.isArray(main.keywords) && main.keywords.every(value => typeof value === 'string' && /^[a-z0-9-]{1,64}$/.test(value)), 'unexpected-main-keywords');
  for (const keyword of ['jongko54', 'ai', 'cross-language', 'contracts']) assert.ok(main.keywords.includes(keyword), 'missing-main-keyword');
  // Enumerate output metadata: never spread the full main package or copy configs.
  const metadata = {
    name: main.name,
    version: VERSION,
    description: 'Temporary npm namespace and trusted-publisher bootstrap; use the full feature-standards@0.1.0 release.',
    license: main.license,
    author: { name: main.author.name, url: main.author.url },
    keywords: [...main.keywords],
    repository: { type: main.repository.type, url: main.repository.url, directory: main.repository.directory },
    publishConfig: { access: 'public', registry: 'https://registry.npmjs.org/', tag: 'bootstrap' },
  };
  assert.deepEqual(Object.keys(metadata), KEYS);
  const serialized = JSON.stringify(metadata);
  assert.ok(!/(?:npm_[a-z0-9]{20,}|gh[pousr]_[a-z0-9]{20,}|_auth|password|authorization|file:|\/Users\/|\/home\/|[a-z]:\\)/i.test(serialized), 'disallowed-bootstrap-metadata');
  return metadata;
}

function outputDirectory(value) {
  if (typeof value !== 'string' || !value || /[\0-\x1f\x7f]/.test(value)) throw new Error('invalid-output-directory');
  const requested = resolve(value);
  let info;
  try { info = lstatSync(requested); }
  catch (error) { if (error.code === 'ENOENT') throw new Error('output-directory-must-already-exist'); throw error; }
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error('output-must-be-a-physical-directory');
  if (typeof process.getuid === 'function' && info.uid !== process.getuid()) throw new Error('output-directory-not-owned-by-current-user');
  const physical = realpathSync(requested);
  if (readdirSync(physical).length !== 0) throw new Error('output-directory-not-empty');
  return physical;
}

function localCommand(command, argv, options = {}) {
  const result = spawnSync(command, argv, { encoding: 'utf8', timeout: 30000, maxBuffer: 1024 * 1024, ...options });
  if (result.error || result.status !== 0) throw new Error('bootstrap-local-' + command + '-failed');
  return result.stdout;
}

export function packBootstrap(directory) {
  const output = outputDirectory(directory);
  const mainBytes = readFileSync(join(PACKAGE, 'package.json'));
  const metadata = checkedMetadata(JSON.parse(mainBytes));
  const license = readFileSync(join(PACKAGE, 'LICENSE'));
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-standards-bootstrap-')));
  chmodSync(scratch, 0o700);
  try {
    const stage = join(scratch, 'package');
    const packedDirectory = join(scratch, 'packed');
    mkdirSync(stage, { mode: 0o700 });
    mkdirSync(packedDirectory, { mode: 0o700 });
    writeFileSync(join(stage, 'package.json'), JSON.stringify(metadata, null, 2) + '\n', { flag: 'wx' });
    writeFileSync(join(stage, 'README.md'), README, { flag: 'wx' });
    writeFileSync(join(stage, 'LICENSE'), license, { flag: 'wx' });
    const userConfig = join(scratch, 'user.npmrc');
    const globalConfig = join(scratch, 'global.npmrc');
    writeFileSync(userConfig, '', { flag: 'wx', mode: 0o600 });
    writeFileSync(globalConfig, '', { flag: 'wx', mode: 0o600 });
    const env = { ...process.env };
    for (const key of Object.keys(env)) {
      if (/^npm_/i.test(key) || ['NODE_AUTH_TOKEN', 'YARN_NPM_AUTH_TOKEN'].includes(key)) delete env[key];
    }
    const results = JSON.parse(localCommand('npm', [
      'pack', '--offline', '--ignore-scripts', '--json', '--cache', join(scratch, 'cache'),
      '--userconfig', userConfig, '--globalconfig', globalConfig, '--pack-destination', packedDirectory,
    ], { cwd: stage, env }));
    assert.equal(results.length, 1);
    const [packed] = results;
    assert.equal(packed.name, metadata.name);
    assert.equal(packed.version, VERSION);
    assert.equal(packed.filename, FILENAME);
    assert.deepEqual(packed.files.map(file => file.path).sort(), FILES);
    const archive = join(packedDirectory, FILENAME);
    // Inspect the actual archive, not just npm's reported inventory.
    assert.deepEqual(localCommand('tar', ['-tzf', archive]).trim().split('\n').sort(), FILES.map(file => 'package/' + file));
    const contents = name => localCommand('tar', ['-xOf', archive, 'package/' + name]);
    const actualMetadata = JSON.parse(contents('package.json'));
    assert.deepEqual(actualMetadata, metadata);
    assert.equal(contents('README.md'), README);
    assert.equal(contents('LICENSE'), license.toString('utf8'));
    for (const content of [contents('package.json'), README]) {
      assert.ok(!content.includes(PACKAGE) && !content.includes(scratch), 'local-path-in-bootstrap');
    }
    assert.deepEqual(readFileSync(join(PACKAGE, 'package.json')), mainBytes, 'main-package-metadata-changed');
    // Recheck the output and copy exclusively: never replace an existing artifact.
    assert.equal(outputDirectory(output), output);
    const target = join(output, FILENAME);
    copyFileSync(archive, target, constants.COPYFILE_EXCL);
    const bytes = readFileSync(target);
    return {
      package: metadata.name, version: VERSION, tag: 'bootstrap', filename: FILENAME,
      outputPath: target, files: FILES, bytes: bytes.length,
      sha256: createHash('sha256').update(bytes).digest('hex'), integrity: packed.integrity,
      published: false,
    };
  } finally { rmSync(scratch, { recursive: true, force: true }); }
}

export function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) {
    console.log('pack-bootstrap --out-dir EXISTING_EMPTY_TASK_OWNED_DIRECTORY\nCreates only feature-standards@0.0.0-bootstrap metadata, README and LICENSE; never publishes.');
    return;
  }
  if (argv.length !== 2 || argv[0] !== '--out-dir' || !argv[1] || argv[1].startsWith('-')) throw new Error('usage: pack-bootstrap --out-dir EXISTING_EMPTY_TASK_OWNED_DIRECTORY');
  console.log(JSON.stringify(packBootstrap(argv[1]), null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { main(); }
  catch (error) { console.error('feature-standards bootstrap: ' + error.message); process.exitCode = 1; }
}
