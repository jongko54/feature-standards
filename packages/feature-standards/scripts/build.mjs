// Build-time only: no implementation source, binaries or execution traces are copied.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, lstatSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const ROOT = resolve(PACKAGE, '../..');
const REPOSITORY = 'https://github.com/jongko54/feature-standards';
// Deliberately enumerate every source file. Never copy source directories recursively.
export const SOURCE_FILES = Object.freeze([
  'feature-standards.json',
  'features/catalog.json',
  'README.md',
  'SECURITY.md',
  'features/auth/catalog.schema.json',
  'features/auth/specification.md',
  'features/auth/postgres-session-v2.md',
  'features/auth/account-session-v3.md',
  'features/auth/mail-delivery-v1.md',
  'features/auth/openapi.json',
  'features/auth/openapi-v2.json',
  'features/auth/openapi-v3.json',
  'features/auth/scenarios.json',
  'features/auth/scenarios-v2.json',
  'features/auth/scenarios-v3.json',
  'features/auth/mail-scenarios.json',
  'features/auth/postgres/001_initial.sql',
  'features/auth/postgres/002_accounts.sql',
  'features/auth/postgres/003_mail_delivery.sql',
  'features/authorization/catalog.json',
  'features/authorization/specification.md',
  'features/authorization/openapi.json',
  'features/authorization/scenarios.json',
  'features/listing/catalog.json',
  'features/listing/specification.md',
  'features/listing/openapi.json',
  'features/listing/scenarios.json',
  'features/listing/postgres-list-v1.md',
  'features/listing/openapi-postgres.json',
  'features/listing/scenarios-postgres.json',
  'docs/ai-integration.md',
  'docs/create-feature-auth.md',
  'docs/postgres-v2.md',
  'docs/account-v3.md',
  'docs/smtp-delivery.md',
  'docs/versioning.md',
  'docs/core-standards.md',
  'docs/postgres-listing.md',
  'docs/core-release-0.1.0.json',
  'libraries/python/README.md',
  'libraries/go/README.md',
  'libraries/java/README.md',
  'libraries/rust/README.md',
  'libraries/typescript/README.md',
  'examples/core-python/README.md',
  'examples/core-python-postgres/README.md',
  'examples/core-go/README.md',
  'examples/core-java/README.md',
  'examples/core-rust/README.md',
  'skills/integrate-core/SKILL.md',
  'implementations/python-fastapi/README.md',
  'implementations/go-net-http/README.md',
  'implementations/java-spring/README.md',
  'implementations/rust-axum/README.md',
  'clients/react/README.md',
  'examples/consumer-python-react/README.md',
  'examples/consumer-python-react/PROFILE_TESTS.md',
  'examples/consumer-go/README.md',
  'examples/consumer-java/README.md',
  'examples/consumer-rust/README.md',
  'skills/integrate-auth/SKILL.md',
  'skills/integrate-auth/references/postgres.md',
  'skills/integrate-auth/references/accounts.md',
  'skills/integrate-auth/references/mail.md',
]);
const STACKS = ['python', 'go', 'java', 'rust', 'react'];
const PROFILES = ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'];
const FEATURES = Object.freeze({ auth: PROFILES, authorization: ['rbac-v1'], listing: ['offset-list-v1', 'postgres-list-v1'] });
const supportedProfiles = (feature, stack) => FEATURES[feature].filter(profile => profile !== 'postgres-list-v1' || stack === 'python');
const allowed = new Set(SOURCE_FILES);
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

function regularSource(sourcePath) {
  if (isAbsolute(sourcePath) || sourcePath.split('/').includes('..')) throw new Error('invalid-source-path');
  const candidate = join(ROOT, sourcePath);
  // Refuse links in every ancestor, including links to other files inside the repo.
  let current = ROOT;
  for (const part of sourcePath.split('/')) {
    current = join(current, part);
    if (lstatSync(current).isSymbolicLink()) throw new Error('source-symlink: ' + sourcePath);
  }
  const physical = realpathSync(candidate);
  const distance = relative(ROOT, physical);
  if (isAbsolute(distance) || distance === '..' || distance.startsWith('..' + sep) || !lstatSync(physical).isFile()) {
    throw new Error('source-file-escape: ' + sourcePath);
  }
  return physical;
}

function git(argv, allowMissing = false) {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (key.startsWith('GIT_')) delete env[key];
  const result = spawnSync('git', ['-C', ROOT, ...argv], {
    env, timeout: 5000, maxBuffer: 8 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (result.error || (result.status !== 0 && !allowMissing)) throw new Error('source-git-metadata-unavailable');
  return result;
}

function requireDocument(path) {
  if (!allowed.has(path)) throw new Error('manifest-document-not-allowlisted: ' + path);
}

function exactIds(entries, expected, label) {
  if (!Array.isArray(entries) || entries.length !== expected.length ||
      [...entries.map(entry => entry.id)].sort().join() !== [...expected].sort().join()) {
    throw new Error('unsupported-manifest-' + label);
  }
}

function validateManifest(manifest, sources, feature) {
  if (manifest.schema_version !== 1 || manifest.feature !== feature || !Object.hasOwn(FEATURES, feature)) throw new Error('unsupported-manifest-feature');
  const profiles = FEATURES[feature];
  exactIds(manifest.profiles, profiles, 'profiles');
  exactIds(manifest.stacks, STACKS, 'stacks');
  for (const profile of manifest.profiles) {
    for (const name of ['specification', 'openapi', 'scenarios', 'guide']) requireDocument(profile[name]);
    if (!Array.isArray(profile.migrations)) throw new Error('unsupported-manifest-migrations');
    profile.migrations.forEach(requireDocument);
    const api = JSON.parse(sources.get(profile.openapi));
    const scenarios = JSON.parse(sources.get(profile.scenarios));
    const apiProfile = feature === 'auth'
      ? api.paths?.['/healthz']?.get?.responses?.['200']?.content?.['application/json']?.schema?.properties?.profile?.const
      : api['x-feature-standards-profile'];
    if (apiProfile !== profile.id || scenarios.profile !== profile.id) {
      throw new Error('manifest-contract-profile-mismatch: ' + profile.id);
    }
    const overrides = profile.stack_overrides ?? {};
    const expectedOverrides = profile.id === 'postgres-list-v1' ? ['python'] : [];
    if (Object.keys(overrides).sort().join() !== expectedOverrides.join()) throw new Error('unsupported-profile-source-bindings');
    for (const override of Object.values(overrides)) {
      if (Object.keys(override).sort().join() !== 'consumer,entrypoints') throw new Error('unsupported-profile-override');
      requireDocument(override.consumer + '/README.md');
      if (!Array.isArray(override.entrypoints) || override.entrypoints.length === 0) throw new Error('missing-source-entrypoints');
      for (const entrypoint of override.entrypoints) regularSource(entrypoint.path);
    }
  }
  for (const stack of manifest.stacks) {
    requireDocument(stack.guide);
    requireDocument(stack.consumer + '/README.md');
    if (!Array.isArray(stack.profiles) || [...stack.profiles].sort().join() !== [...supportedProfiles(feature, stack.id)].sort().join()) {
      throw new Error('unsupported-manifest-stack-profiles: ' + stack.id);
    }
    if (!Array.isArray(stack.entrypoints) || stack.entrypoints.length === 0) throw new Error('missing-source-entrypoints');
    for (const entrypoint of stack.entrypoints) regularSource(entrypoint.path);
  }
  for (const addon of manifest.addons) {
    for (const name of ['specification', 'guide', 'scenarios']) requireDocument(addon[name]);
    regularSource(addon.entrypoint);
  }
}

function validateIndex(index, sources) {
  if (index.schema_version !== 1) throw new Error('unsupported-feature-index');
  exactIds(index.features, Object.keys(FEATURES), 'features');
  for (const feature of index.features) {
    for (const name of ['catalog', 'integration_skill', 'integration_guide']) requireDocument(feature[name]);
    if (feature.default_profile !== FEATURES[feature.id][0] || typeof feature.description !== 'string' || !feature.description.trim()) {
      throw new Error('invalid-feature-index-entry: ' + feature.id);
    }
    validateManifest(JSON.parse(sources.get(feature.catalog)), sources, feature.id);
  }
}

export function buildSnapshot() {
  // Read and validate every input before replacing this package's generated directory.
  const sources = new Map(SOURCE_FILES.map(path => [path, readFileSync(regularSource(path))]));
  validateIndex(JSON.parse(sources.get('features/catalog.json')), sources);
  const sourceCommit = git(['rev-parse', 'HEAD']).stdout.toString('utf8').trim();
  if (!/^[a-f0-9]{40,64}$/.test(sourceCommit)) throw new Error('invalid-source-commit');
  const files = Object.fromEntries([...sources].map(([path, bytes]) => {
    const committed = git(['show', sourceCommit + ':' + path], true);
    return [path, {
      sha256: sha256(bytes),
      sourceModified: committed.status !== 0 || !committed.stdout.equals(bytes),
    }];
  }));
  const provenance = {
    schemaVersion: 1,
    repositoryUrl: REPOSITORY,
    sourceCommit,
    sourceDirty: git(['status', '--porcelain=v1', '--untracked-files=normal']).stdout.length > 0,
    snapshotDirty: Object.values(files).some(file => file.sourceModified),
    capturedAt: new Date().toISOString(),
    sourceUrlMeaning: 'URLs point to the captured HEAD. Files marked sourceModified include local changes not present at that URL; SHA-256 identifies the packaged bytes.',
    files,
  };
  const destination = join(PACKAGE, 'snapshot');
  rmSync(destination, { recursive: true, force: true });
  mkdirSync(destination, { recursive: true });
  for (const [path, bytes] of sources) {
    const target = join(destination, path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, bytes, { mode: 0o644 });
  }
  writeFileSync(join(destination, 'provenance.json'), JSON.stringify(provenance, null, 2) + '\n');
  chmodSync(join(PACKAGE, 'src/cli.mjs'), 0o755);
  return provenance;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { buildSnapshot(); }
  catch (error) { console.error('feature-standards build: ' + error.message); process.exitCode = 1; }
}
