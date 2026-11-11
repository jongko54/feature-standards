import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { lstatSync, readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';
import { CORE_AUTH_ROOTS, CORE_CHECK_PROTOCOL_VERSION, CORE_FEATURES, CORE_MANIFESTS, CORE_PROFILES, CORE_STACKS } from './core-protocol.mjs';

export function within(parent, child) {
  const distance = relative(parent, child);
  return distance === '' || (!isAbsolute(distance) && distance !== '..' && !distance.startsWith('..' + sep));
}

export function pathText(value) {
  if (typeof value !== 'string' || !value || /[\0-\x1f\x7f]/.test(value)) throw new Error('invalid-core-path');
  return value;
}

export function physicalDirectory(value, label) {
  const path = resolve(pathText(value));
  try {
    if (lstatSync(path).isSymbolicLink() || !lstatSync(path).isDirectory() || realpathSync(path) !== path) throw new Error();
  } catch { throw new Error(label + '-must-be-a-physical-directory'); }
  return path;
}

export function regularFile(root, path, label = 'source-file') {
  const candidate = resolve(root, path);
  try {
    if (!within(root, candidate) || realpathSync(candidate) !== candidate || !lstatSync(candidate).isFile()) throw new Error();
  } catch { throw new Error(label + '-must-be-a-regular-file'); }
  return candidate;
}

export function readJson(path, label) {
  try { return JSON.parse(readFileSync(path, 'utf8')); }
  catch { throw new Error('invalid-' + label); }
}

export function coreSelection(options) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) throw new Error('invalid-core-options');
  if (options.feature !== undefined || (options.template !== undefined && options.template !== 'core')) throw new Error('ambiguous-core-selection');
  if (!CORE_STACKS.includes(options.stack)) throw new Error('unsupported-core-stack');
  const profile = options.profile ?? CORE_PROFILES.auth;
  if (profile !== CORE_PROFILES.auth) throw new Error('unsupported-core-profile');
  return { template: 'core', stack: options.stack, profile };
}

export function inspectSource(value, stack) {
  const source = physicalDirectory(value, 'source');
  const metadata = readJson(regularFile(source, 'packages/feature-standards/package.json'), 'core-source-package');
  if (metadata?.name !== 'feature-standards' || !/^\d+\.\d+\.\d+$/.test(metadata.version ?? '')
      || metadata.featureStandards?.coreStarterProtocolVersion !== CORE_CHECK_PROTOCOL_VERSION) throw new Error('unsupported-core-source-capability');
  regularFile(source, 'packages/feature-standards/src/core-generator.mjs');
  const manifests = {};
  const sourceManifestsSha256 = {};
  for (const file of CORE_MANIFESTS) {
    const contents = readFileSync(regularFile(source, file), 'utf8');
    try { manifests[file] = JSON.parse(contents); } catch { throw new Error('unsupported-core-source-manifest'); }
    sourceManifestsSha256[file] = createHash('sha256').update(contents).digest('hex');
  }
  const catalog = manifests['features/catalog.json'];
  if (catalog?.schema_version !== 1 || !Array.isArray(catalog.features)) throw new Error('unsupported-core-source-manifest');
  for (const feature of CORE_FEATURES) {
    const file = feature === 'auth' ? 'feature-standards.json' : `features/${feature}/catalog.json`;
    const selections = catalog.features.filter(entry => entry?.id === feature);
    const manifest = manifests[file];
    const root = feature === 'auth' ? CORE_AUTH_ROOTS[stack] : 'libraries/' + stack;
    const stacks = Array.isArray(manifest?.stacks) ? manifest.stacks.filter(entry => entry?.id === stack) : [];
    if (selections.length !== 1 || selections[0].catalog !== file || manifest?.schema_version !== 1 || manifest.feature !== feature
        || !Array.isArray(manifest.profiles) || !manifest.profiles.some(profile => profile?.id === CORE_PROFILES[feature])
        || !Array.isArray(stacks) || stacks.length !== 1 || stacks[0].root !== root
        || !Array.isArray(stacks[0].profiles) || !stacks[0].profiles.includes(CORE_PROFILES[feature])) throw new Error('unsupported-core-source-manifest');
    physicalDirectory(join(source, root), 'source-library');
  }
  const markers = {
    python: [CORE_AUTH_ROOTS.python + '/feature_auth/__init__.py', 'libraries/python/feature_standards/__init__.py'],
    go: [CORE_AUTH_ROOTS.go + '/auth/server.go', 'libraries/go/authorization/policy.go'],
    java: [CORE_AUTH_ROOTS.java + '/pom.xml', 'libraries/java/pom.xml'],
    rust: [CORE_AUTH_ROOTS.rust + '/Cargo.toml', 'libraries/rust/src/lib.rs'],
  };
  for (const marker of markers[stack]) regularFile(source, marker);
  return { source, sourceManifestsSha256, sourceVersion: metadata.version };
}

export function sourceCommit(source) {
  const environment = { ...process.env };
  for (const key of Object.keys(environment)) if (key.startsWith('GIT_')) delete environment[key];
  const result = spawnSync('git', ['-C', source, 'rev-parse', 'HEAD'], { env: environment, encoding: 'utf8', timeout: 3000, stdio: ['ignore', 'pipe', 'ignore'] });
  const commit = result.status === 0 ? result.stdout.trim() : '';
  return /^[0-9a-f]{40,64}$/.test(commit) ? commit : null;
}

export function inspectProject(value) {
  const directory = physicalDirectory(value, 'project');
  let metadata;
  try { metadata = readJson(regularFile(directory, 'feature-core.json', 'core-project-metadata'), 'core-project-metadata'); }
  catch { throw new Error('invalid-core-project-metadata'); }
  if (!metadata || metadata.generator !== 'feature-standards' || metadata.template !== 'core'
      || metadata.coreCheckProtocolVersion !== CORE_CHECK_PROTOCOL_VERSION || !CORE_STACKS.includes(metadata.stack)
      || metadata.profile !== CORE_PROFILES.auth || JSON.stringify(metadata.features) !== JSON.stringify(CORE_FEATURES)
      || !metadata.profiles || Object.keys(metadata.profiles).length !== CORE_FEATURES.length
      || CORE_FEATURES.some(feature => metadata.profiles[feature] !== CORE_PROFILES[feature])
      || typeof metadata.source !== 'string' || !metadata.source || isAbsolute(metadata.source)
      || /[\0-\x1f\x7f]/.test(metadata.source)) throw new Error('invalid-core-project-metadata');
  const inspected = inspectSource(resolve(directory, metadata.source), metadata.stack);
  if (!metadata.sourceManifestsSha256 || Object.keys(metadata.sourceManifestsSha256).length !== CORE_MANIFESTS.length
      || CORE_MANIFESTS.some(file => metadata.sourceManifestsSha256[file] !== inspected.sourceManifestsSha256[file])) throw new Error('core-source-manifests-changed');
  if (!metadata.dependencies || Object.keys(metadata.dependencies).length !== 2) throw new Error('invalid-core-project-dependencies');
  const dependencies = {};
  for (const [name, root] of [['auth', CORE_AUTH_ROOTS[metadata.stack]], ['core', 'libraries/' + metadata.stack]]) {
    const path = metadata.dependencies[name]?.path;
    if (typeof path !== 'string' || !path || isAbsolute(path) || /[\0-\x1f\x7f]/.test(path)
        || resolve(directory, path) !== join(inspected.source, root)) throw new Error('invalid-core-project-dependencies');
    dependencies[name] = physicalDirectory(resolve(directory, path), 'source-library');
  }
  return { ...metadata, ...inspected, directory, dependencies };
}
