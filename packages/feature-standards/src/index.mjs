import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
export { initFeature, checkProject } from './workflow.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const readJson = path => JSON.parse(readFileSync(join(PACKAGE, path), 'utf8'));

function snapshot() {
  try {
    const provenance = readJson('snapshot/provenance.json');
    const index = readJson('snapshot/features/catalog.json');
    return {
      features: index.features.map(feature => ({
        ...feature,
        manifest: JSON.parse(readFileSync(document(provenance, feature.catalog).readPath, 'utf8')),
      })),
      provenance,
      packageMetadata: readJson('package.json'),
    };
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('snapshot-missing: from the source checkout, run npm --prefix packages/feature-standards run build');
    throw error;
  }
}

function origin(provenance, sourcePath, directory = false) {
  return provenance.repositoryUrl + '/' + (directory ? 'tree' : 'blob') + '/' + provenance.sourceCommit + '/' + sourcePath;
}

function document(provenance, sourcePath) {
  // Never resolve a user argument as a filesystem path or fall back to the caller's checkout.
  if (!Object.hasOwn(provenance.files, sourcePath)) throw new Error('snapshot-document-not-bundled');
  const packagePath = 'snapshot/' + sourcePath;
  return {
    packagePath, readPath: join(PACKAGE, packagePath), sourcePath,
    sourceUrl: origin(provenance, sourcePath),
    ...provenance.files[sourcePath],
  };
}

function checkoutReference(provenance, checkoutPath, directory = false) {
  return { checkoutPath, sourceUrl: origin(provenance, checkoutPath, directory) };
}

function metadata(provenance) {
  const { files, ...details } = provenance;
  return details;
}

function commands(entries) {
  return entries.map(({ cwd, argv }) => ({ scope: 'source-checkout', cwd, argv, executed: false }));
}

/** List only features actually represented by this release's contract snapshot. */
export function listFeatures() {
  const { features, provenance, packageMetadata } = snapshot();
  return {
    schemaVersion: 1,
    package: { name: packageMetadata.name, version: packageMetadata.version },
    provenance: metadata(provenance),
    features: features.map(({ manifest, description }) => ({
      id: manifest.feature,
      description,
      profiles: manifest.profiles.map(profile => profile.id),
      stacks: manifest.stacks.map(({ id, role, language, framework }) => ({ id, role, language, framework })),
    })),
  };
}

/** Select local contract documents and separate source-checkout guidance. Never execute it. */
export function getContext(options = {}) {
  if (options === null || typeof options !== 'object' || Array.isArray(options)) throw new Error('invalid-options');
  const { feature = 'auth', stack: stackId } = options;
  const { features, provenance, packageMetadata } = snapshot();
  const selected = features.find(candidate => candidate.id === feature);
  if (!selected) throw new Error('unsupported-feature: choose ' + features.map(candidate => candidate.id).join('|'));
  const { manifest } = selected;
  const { profile: profileId = selected.default_profile } = options;
  const isAuth = feature === 'auth';
  if (!stackId) throw new Error('stack-required: choose ' + manifest.stacks.map(stack => stack.id).join('|'));
  const stack = manifest.stacks.find(candidate => candidate.id === stackId);
  if (!stack) throw new Error('unsupported-stack: choose ' + manifest.stacks.map(candidate => candidate.id).join('|'));
  const profile = manifest.profiles.find(candidate => candidate.id === profileId);
  if (!profile || !stack.profiles.includes(profileId)) throw new Error('unsupported-profile: choose ' + stack.profiles.join('|'));
  const doc = path => document(provenance, path);
  const ref = (path, directory = false) => checkoutReference(provenance, path, directory);
  const profileIndex = manifest.profiles.findIndex(candidate => candidate.id === profile.id);
  return {
    schemaVersion: 1,
    package: { name: packageMetadata.name, version: packageMetadata.version },
    feature: manifest.feature,
    profile: profile.id,
    stack: { id: stack.id, role: stack.role, language: stack.language, framework: stack.framework },
    provenance: metadata(provenance),
    packagedDocuments: {
      manifest: doc(selected.catalog),
      specification: doc(profile.specification),
      relatedSpecifications: manifest.profiles.slice(0, profileIndex).map(candidate => doc(candidate.specification)),
      openapi: doc(profile.openapi),
      scenarios: doc(profile.scenarios),
      migrations: profile.migrations.map(doc),
      profileGuide: doc(profile.guide),
      apiGuide: doc(stack.guide),
      consumerGuide: doc(stack.consumer + '/README.md'),
      integrationSkill: doc(selected.integration_skill),
      integrationGuide: doc(selected.integration_guide),
      ...(isAuth ? { generatorGuide: doc('docs/create-feature-auth.md') } : {}),
      profileReferences: [
        ...(isAuth && profileIndex >= 1 ? [doc('skills/integrate-auth/references/postgres.md')] : []),
        ...(isAuth && profileIndex >= 2 ? [doc('skills/integrate-auth/references/accounts.md')] : []),
      ],
    },
    sourceCheckout: {
      required: true,
      scope: 'Paths and command working directories below are relative to a separate trusted source checkout, not this npm package. Commands are guidance only and have not been executed.',
      repositoryUrl: provenance.repositoryUrl,
      suggestedCommit: provenance.sourceCommit,
      root: ref(stack.root, true),
      consumer: ref(stack.consumer, true),
      entrypoints: stack.entrypoints.map(({ path, symbol }) => ({ ...ref(path), symbol })),
      packageMetadata: {
        ...stack.package,
        registryStatusVerifiedByThisTool: false,
        note: 'Publication fields are captured manifest metadata, not a live registry check. This npm package does not include these runtime APIs.',
      },
      environment: profile.environment,
      install: commands(stack.install),
      checks: commands([...stack.checks, ...profile.checks]),
      generator: isAuth && stack.role === 'backend' ? {
        supportedForStack: true,
        scope: 'source-checkout',
        cwd: '.',
        argv: ['node', 'packages/create-feature-auth/src/cli.mjs', '--source', '<absolute-checkout>', '--stack', stack.id, '--profile', profile.id, '--dest', '<new-directory-outside-checkout>'],
        executed: false,
        note: 'Optional existing generator. Replace the placeholders and run it explicitly from a trusted checkout. No generator or runner is included here.',
      } : {
        supportedForStack: false,
        note: isAuth ? 'The existing generator supports backend consumers. Use the React consumer guide for client integration.'
          : 'The existing generator supports auth only. Integrate these reusable APIs explicitly and run the listed source conformance checks.',
      },
    },
    optionalAddons: (isAuth ? manifest.addons : []).filter(addon => addon.requires_profile === profile.id).map(addon => ({
      id: addon.id,
      requiresProfile: addon.requires_profile,
      packagedDocuments: {
        specification: doc(addon.specification), guide: doc(addon.guide), scenarios: doc(addon.scenarios),
        schema: doc('features/auth/postgres/003_mail_delivery.sql'),
        integrationReference: doc('skills/integrate-auth/references/mail.md'),
      },
      sourceCheckout: { required: true, entrypoint: ref(addon.entrypoint) },
      note: 'Optional, requires an explicit user request and separate SMTP configuration. No worker or migration runs here.',
    })),
    limits: [
      'Read-only contract selection: no project edits, dependency installation, checks, migrations, servers or model calls.',
      'Implementation source and conformance harnesses require the source checkout; packaged guides may link to files that are not bundled.',
      'This snapshot is not an automatic update mechanism or a security certification. Test results and AI speed improvements are not established by selecting context.',
      ...(feature === 'authorization' && stack.id === 'react' ? ['Browser authorization helpers provide presentation advice only. Server-owned principals, resources and policy enforcement remain authoritative.'] : []),
    ],
  };
}
