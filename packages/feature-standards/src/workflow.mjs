import { lstatSync, readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, join, dirname, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { CORE_CHECK_PROTOCOL_VERSION, CORE_FEATURES, CORE_PROFILES, CORE_REQUIRED_CHECKS } from './core-protocol.mjs';
import { coreSelection, inspectProject as inspectCoreProject, inspectSource as inspectCoreSource } from './core-source.mjs';

const GENERATOR = '@ugauga/create-feature-auth';
const STACKS = ['python', 'go', 'java', 'rust'];
const PROFILES = ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'];
const within = (parent, child) => {
  const distance = relative(parent, child);
  return distance === '' || (!isAbsolute(distance) && distance !== '..' && !distance.startsWith('..' + sep));
};

function optionsObject(options, allowed) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) throw new Error('invalid-workflow-options');
  if (Object.keys(options).some(key => !allowed.includes(key))) throw new Error('unknown-workflow-option');
}

function pathText(value) {
  if (typeof value !== 'string' || !value || /[\0-\x1f\x7f]/.test(value)) throw new Error('invalid-workflow-path');
  return value;
}

function directory(value, label) {
  const requested = resolve(pathText(value));
  try {
    const information = lstatSync(requested);
    if (information.isSymbolicLink() || !information.isDirectory() || realpathSync(requested) !== requested) {
      throw new Error();
    }
  } catch { throw new Error(label + '-must-be-a-physical-directory'); }
  return requested;
}

function regularFile(root, path, label) {
  const candidate = join(root, path);
  try {
    if (!within(root, candidate)) throw new Error();
    const physical = realpathSync(candidate);
    if (physical !== candidate || !within(root, physical) || !lstatSync(candidate).isFile()) throw new Error();
  } catch { throw new Error(label + '-must-be-a-regular-file'); }
  return candidate;
}

function readJson(path, label) {
  try { return JSON.parse(readFileSync(path, 'utf8')); }
  catch { throw new Error('invalid-' + label); }
}

function currentGenerator(version) {
  if (typeof version !== 'string' || !/^\d+\.\d+\.\d+$/.test(version)) return false;
  const [major, minor, patch] = version.split('.').map(Number);
  return [major, minor, patch].every(Number.isSafeInteger) && (major > 0 || minor >= 2);
}

function selection(options) {
  const feature = options.feature ?? 'auth';
  const profile = options.profile ?? 'browser-session-v1';
  if (feature !== 'auth') throw new Error('unsupported-feature: init/check support auth only; use context for authorization or listing integration guidance');
  if (!STACKS.includes(options.stack)) throw new Error('unsupported-generation-stack: choose python|go|java|rust');
  if (!PROFILES.includes(profile)) throw new Error('unsupported-profile: choose ' + PROFILES.join('|'));
  return { feature, stack: options.stack, profile };
}

function sourceCheckout(value, selected) {
  const source = directory(value, 'source');
  const metadata = readJson(regularFile(source, 'packages/create-feature-auth/package.json', 'generator-metadata'), 'generator-metadata');
  if (metadata?.name !== GENERATOR) throw new Error('generator-identity-mismatch');
  if (!currentGenerator(metadata.version)) throw new Error('generator-version-unsupported: source requires create-feature-auth >=0.2.0');
  const manifest = readJson(regularFile(source, 'feature-standards.json', 'source-manifest'), 'source-manifest');
  if (manifest?.schema_version !== 1 || manifest.feature !== 'auth'
      || !Array.isArray(manifest.profiles) || !manifest.profiles.some(profile => profile?.id === selected.profile)
      || !Array.isArray(manifest.stacks) || !manifest.stacks.some(stack => stack?.id === selected.stack && Array.isArray(stack.profiles) && stack.profiles.includes(selected.profile))) {
    throw new Error('unsupported-source-manifest');
  }
  const entrypoint = regularFile(source, 'packages/create-feature-auth/src/cli.mjs', 'generator-entrypoint');
  return { source, entrypoint };
}

function destination(value, source) {
  const target = resolve(pathText(value));
  directory(dirname(target), 'destination-parent');
  if (within(source, target)) throw new Error('destination-inside-source');
  try { lstatSync(target); }
  catch (error) { if (error.code === 'ENOENT') return target; throw new Error('invalid-destination'); }
  throw new Error('destination-already-exists');
}

function generatedProject(value) {
  const project = directory(value, 'project');
  const present = name => {
    try { lstatSync(join(project, name)); return true; }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
  };
  const core = present('feature-core.json');
  if (core && present('feature-auth.json')) throw new Error('ambiguous-project-metadata');
  if (core) return { project, core: inspectCoreProject(project), runner: regularFile(project, 'project.mjs', 'project-runner') };
  const metadata = readJson(regularFile(project, 'feature-auth.json', 'project-metadata'), 'project-metadata');
  if (!metadata || metadata.generator !== GENERATOR || !currentGenerator(metadata.generatorVersion) || metadata.checkProtocolVersion !== 1) {
    throw new Error('project-check-protocol-unsupported: regenerate with create-feature-auth >=0.2.0');
  }
  const selected = selection(metadata);
  const relativeSource = pathText(metadata.source);
  if (isAbsolute(relativeSource)) throw new Error('project-source-must-be-relative');
  const checkout = sourceCheckout(resolve(project, relativeSource), selected);
  const runner = regularFile(project, 'project.mjs', 'project-runner');
  return { project, metadata, selected, checkout, runner };
}

function checkReceipt(receipt, selected) {
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)
      || receipt.schemaVersion !== 1 || receipt.stack !== selected.stack || receipt.profile !== selected.profile
      || receipt.passed !== true || !Array.isArray(receipt.checks) || receipt.checks.length === 0
      || !receipt.checks.every(check => typeof check === 'string' && check.length > 0)
      || !receipt.database || typeof receipt.database !== 'object') throw new Error('invalid-check-receipt');
  if (selected.profile === 'browser-session-v1') {
    if (receipt.database.used !== false || receipt.database.isolated !== false) throw new Error('invalid-check-receipt');
  } else if (receipt.database.used !== true || receipt.database.isolated !== true
      || receipt.database.created !== true || receipt.database.dropped !== true || receipt.database.existingDatabaseModified !== false) {
    throw new Error('invalid-check-receipt');
  }
  return receipt;
}

function coreReceipt(receipt, selected) {
  const invalid = () => { throw new Error('invalid-core-check-receipt'); };
  if (!receipt || receipt.schemaVersion !== 1 || receipt.template !== 'core'
      || receipt.coreCheckProtocolVersion !== CORE_CHECK_PROTOCOL_VERSION
      || receipt.stack !== selected.stack || receipt.profile !== CORE_PROFILES.auth || receipt.passed !== true
      || JSON.stringify(receipt.features) !== JSON.stringify(CORE_FEATURES)
      || !receipt.profiles || Object.keys(receipt.profiles).length !== CORE_FEATURES.length
      || CORE_FEATURES.some(feature => receipt.profiles[feature] !== CORE_PROFILES[feature])
      || !Array.isArray(receipt.checks) || receipt.checks.some(check => typeof check !== 'string' || !check)
      || new Set(receipt.checks).size !== receipt.checks.length
      || CORE_REQUIRED_CHECKS.some(check => !receipt.checks.includes(check))
      || receipt.database?.used !== false || receipt.database?.isolated !== false
      || !receipt.dependencyOrigins || Object.keys(receipt.dependencyOrigins).length !== 2) invalid();
  for (const name of ['auth', 'core']) {
    const origin = receipt.dependencyOrigins[name];
    if (!origin || origin.kind !== 'source' || origin.verified !== true
        || origin.expectedPath !== selected.dependencies[name] || origin.resolvedPath !== selected.dependencies[name]
        || typeof origin.method !== 'string' || !origin.method) invalid();
  }
  return receipt;
}

/** Explicitly execute a generated project's trusted runner. Never called by list/context. */
export async function checkProject(options) {
  optionsObject(options, ['project']);
  const inspected = generatedProject(options.project);
  const runner = await import(pathToFileURL(inspected.runner).href);
  if (typeof runner.runProject !== 'function') throw new Error('project-runner-api-unavailable');
  if (inspected.core) {
    const receipt = coreReceipt(await runner.runProject('check', inspected.project), inspected.core);
    return { ...receipt, executed: true, project: inspected.project };
  }
  const receipt = checkReceipt(await runner.runProject('check', inspected.project), inspected.selected);
  return { ...receipt, feature: 'auth', executed: true, project: inspected.project };
}

/** Explicitly create an application using a trusted source checkout's existing generator. */
export async function initFeature(options) {
  optionsObject(options, ['feature', 'stack', 'profile', 'source', 'dest', 'check', 'template']);
  if (options.template !== undefined) return initCore(options);
  const selected = selection(options);
  if (options.check !== undefined && typeof options.check !== 'boolean') throw new Error('invalid-check-option');
  const checkout = sourceCheckout(options.source, selected);
  const target = destination(options.dest, checkout.source);
  const generator = await import(pathToFileURL(checkout.entrypoint).href);
  if (typeof generator.generate !== 'function') throw new Error('generator-api-unavailable');
  const result = await generator.generate({ source: checkout.source, stack: selected.stack, profile: selected.profile, dest: target });
  if (!result || result.destination !== target || result.stack !== selected.stack || result.profile !== selected.profile
      || !Array.isArray(result.files) || !result.files.every(file => typeof file === 'string')) throw new Error('invalid-generation-result');
  const created = generatedProject(target);
  if (created.checkout.source !== checkout.source || created.selected.stack !== selected.stack || created.selected.profile !== selected.profile) {
    throw new Error('generated-project-selection-mismatch');
  }
  const checked = options.check ? await checkProject({ project: target }) : { executed: false };
  return { schemaVersion: 1, feature: selected.feature, ...result, check: checked };
}

async function initCore(options) {
  const selected = coreSelection(options);
  if (options.check !== undefined && typeof options.check !== 'boolean') throw new Error('invalid-check-option');
  const checkout = inspectCoreSource(options.source, selected.stack);
  const target = destination(options.dest, checkout.source);
  const generator = await import(pathToFileURL(regularFile(checkout.source, 'packages/feature-standards/src/core-generator.mjs', 'core-generator-entrypoint')).href);
  if (typeof generator.generateCore !== 'function') throw new Error('core-generator-api-unavailable');
  const result = await generator.generateCore({ ...selected, source: checkout.source, dest: target });
  if (!result || result.destination !== target || result.stack !== selected.stack || result.profile !== selected.profile
      || result.template !== 'core' || JSON.stringify(result.features) !== JSON.stringify(CORE_FEATURES)
      || JSON.stringify(result.profiles) !== JSON.stringify(CORE_PROFILES)
      || !Array.isArray(result.files) || !result.files.every(file => typeof file === 'string')) throw new Error('invalid-core-generation-result');
  const created = generatedProject(target);
  if (!created.core || created.core.source !== checkout.source || created.core.stack !== selected.stack) throw new Error('generated-core-selection-mismatch');
  const checked = options.check ? await checkProject({ project: target }) : { executed: false };
  return { schemaVersion: 1, ...result, check: checked };
}
