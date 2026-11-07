import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { getContext, listFeatures } from '../src/index.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CLI = join(PACKAGE, 'src/cli.mjs');
const STACKS = ['python', 'go', 'java', 'rust', 'react'];
const PROFILES = ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'];
const run = (args, options = {}) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', ...options });

test('database listing context selects Python-only API and exposes supported stack profiles', () => {
  const selected = getContext({ feature: 'listing', stack: 'python', profile: 'postgres-list-v1' });
  assert.equal(selected.sourceCheckout.consumer.checkoutPath, 'examples/core-python-postgres');
  assert.equal(selected.sourceCheckout.entrypoints[0].checkoutPath, 'libraries/python/feature_standards/postgres_listing.py');
  assert.equal(selected.sourceCheckout.packageMetadata.published, false);
  const listing = listFeatures().features.find(feature => feature.id === 'listing');
  assert.deepEqual(listing.stacks.find(stack => stack.id === 'python').profiles, ['offset-list-v1', 'postgres-list-v1']);
  for (const stack of STACKS.filter(stack => stack !== 'python')) {
    assert.deepEqual(listing.stacks.find(entry => entry.id === stack).profiles, ['offset-list-v1']);
    assert.throws(() => getContext({ feature: 'listing', stack, profile: 'postgres-list-v1' }), /unsupported-profile/);
  }
});

test('compact context routes to selected documents without emitting the full command inventory', () => {
  const full = run(['context', '--feature', 'authorization', '--stack', 'go']);
  const compact = run(['context', '--feature', 'authorization', '--stack', 'go', '--compact']);
  assert.equal(full.status, 0, full.stderr);
  assert.equal(compact.status, 0, compact.stderr);
  const original = JSON.parse(full.stdout);
  const card = JSON.parse(compact.stdout);
  assert.equal(card.mode, 'compact');
  assert.equal(card.readOnly, true);
  assert.equal(card.profile, original.profile);
  assert.deepEqual(card.readFirst.map(doc => doc.readPath), [
    original.packagedDocuments.apiGuide.readPath,
    original.packagedDocuments.consumerGuide.readPath,
    original.packagedDocuments.integrationSkill.readPath,
  ]);
  for (const doc of [...card.readFirst, ...Object.values(card.contract)]) {
    assert.ok(existsSync(doc.readPath));
    assert.match(doc.sha256, /^[a-f0-9]{64}$/);
  }
  assert.deepEqual(card.source.entrypoints, original.sourceCheckout.entrypoints.map(({ checkoutPath, symbol }) => ({ checkoutPath, symbol })));
  assert.equal(card.packageMetadata.registryStatusVerifiedByThisTool, false);
  assert.equal(card.commands, undefined);
  assert.equal(card.source.install, undefined);
  assert.ok(Buffer.byteLength(compact.stdout) < Buffer.byteLength(full.stdout) * 0.65);
  for (const args of [['list', '--compact'], ['context', '--stack', 'go', '--compact', '--compact'], ['init', '--compact']]) {
    assert.notEqual(run(args).status, 0);
  }
});

test('list describes three implemented features with five stack roles and their profiles', () => {
  const result = listFeatures();
  assert.deepEqual(result.features.map(feature => feature.id), ['auth', 'authorization', 'listing']);
  assert.equal(result.features[0].id, 'auth');
  assert.deepEqual(result.features[0].profiles, PROFILES);
  assert.deepEqual(result.features[0].stacks.map(stack => stack.id), STACKS);
  assert.equal(result.features[0].stacks.find(stack => stack.id === 'react').role, 'client');
  for (const [index, profiles] of [[1, ['rbac-v1']], [2, ['offset-list-v1', 'postgres-list-v1']]]) {
    assert.deepEqual(result.features[index].profiles, profiles);
    assert.deepEqual(result.features[index].stacks.map(stack => stack.id), STACKS);
  }
  assert.match(result.provenance.sourceCommit, /^[a-f0-9]{40,64}$/);
  assert.equal(typeof result.provenance.sourceDirty, 'boolean');
});

test('new core features select ten real source contexts without enabling auth workflows', () => {
  for (const [feature, profile] of [['authorization', 'rbac-v1'], ['listing', 'offset-list-v1']]) for (const stack of STACKS) {
    const context = getContext({ feature, stack });
    assert.equal(context.feature, feature);
    assert.equal(context.profile, profile);
    assert.equal(context.stack.id, stack);
    for (const name of ['manifest', 'specification', 'openapi', 'scenarios', 'apiGuide', 'consumerGuide', 'integrationSkill', 'integrationGuide']) {
      const doc = context.packagedDocuments[name];
      assert.ok(existsSync(doc.readPath), name);
      assert.equal(doc.readPath, join(PACKAGE, doc.packagePath));
      assert.match(doc.sha256, /^[a-f0-9]{64}$/);
    }
    assert.equal(JSON.parse(readFileSync(context.packagedDocuments.scenarios.readPath, 'utf8')).profile, profile);
    const manifest = JSON.parse(readFileSync(context.packagedDocuments.manifest.readPath, 'utf8'));
    assert.equal(context.sourceCheckout.packageMetadata.published, manifest.stacks.find(entry => entry.id === stack).package.published);
    assert.equal(context.sourceCheckout.packageMetadata.registryStatusVerifiedByThisTool, false);
    assert.equal(context.sourceCheckout.generator.supportedForStack, false);
    if (feature === 'authorization' && stack === 'react') assert.ok(context.limits.some(limit => /presentation advice only/.test(limit)));
    assert.deepEqual(context.optionalAddons, []);
    assert.ok(context.sourceCheckout.entrypoints.length > 0);
    for (const entry of context.sourceCheckout.entrypoints) {
      assert.ok(entry.checkoutPath.startsWith('libraries/'));
      assert.ok(!existsSync(join(PACKAGE, 'snapshot', entry.checkoutPath)));
    }
    const conformance = context.sourceCheckout.checks.find(command => command.argv.includes('tools/check_core_features.py'));
    assert.ok(conformance, 'source conformance command');
    assert.ok(conformance.argv.includes(feature));
    assert.ok(conformance.argv.includes(stack));
    assert.equal(conformance.executed, false);
    assert.throws(() => getContext({ feature, stack, profile: 'browser-session-v1' }), /unsupported-profile/);
  }
});

test('all 15 contexts select the requested contract and keep runtime paths outside the package', () => {
  for (const stack of STACKS) for (const profile of PROFILES) {
    const context = getContext({ feature: 'auth', stack, profile });
    assert.equal(context.feature, 'auth');
    assert.equal(context.profile, profile);
    assert.equal(context.stack.id, stack);
    const documents = context.packagedDocuments;
    for (const name of ['manifest', 'specification', 'openapi', 'scenarios', 'apiGuide', 'consumerGuide', 'integrationSkill', 'integrationGuide']) {
      const doc = documents[name];
      assert.ok(doc.packagePath.startsWith('snapshot/'), name);
      assert.equal(doc.readPath, join(PACKAGE, doc.packagePath));
      assert.ok(existsSync(doc.readPath), name);
      assert.match(doc.sha256, /^[a-f0-9]{64}$/);
      assert.ok(doc.sourceUrl.startsWith(context.provenance.repositoryUrl + '/blob/' + context.provenance.sourceCommit + '/'));
      assert.equal(typeof doc.sourceModified, 'boolean');
    }
    const api = JSON.parse(readFileSync(documents.openapi.readPath, 'utf8'));
    assert.equal(api.paths['/healthz'].get.responses['200'].content['application/json'].schema.properties.profile.const, profile);
    assert.equal(JSON.parse(readFileSync(documents.scenarios.readPath, 'utf8')).profile, profile);
    assert.equal(documents.migrations.length, PROFILES.indexOf(profile));
    assert.equal(context.sourceCheckout.required, true);
    assert.equal(context.sourceCheckout.packageMetadata.registryStatusVerifiedByThisTool, false);
    assert.equal(context.sourceCheckout.entrypoints.length, 1);
    for (const entry of context.sourceCheckout.entrypoints) {
      assert.ok(entry.checkoutPath);
      assert.equal(entry.readPath, undefined);
      assert.equal(entry.packagePath, undefined);
      assert.ok(!existsSync(join(PACKAGE, 'snapshot', entry.checkoutPath)));
    }
    for (const command of [...context.sourceCheckout.install, ...context.sourceCheckout.checks]) {
      assert.equal(command.scope, 'source-checkout');
      assert.equal(command.executed, false);
      assert.ok(Array.isArray(command.argv) && command.argv.length > 0);
    }
    assert.equal(context.sourceCheckout.generator.supportedForStack, stack !== 'react');
    assert.equal(context.optionalAddons.length, profile === 'browser-session-v3' ? 1 : 0);
  }
});

test('defaults select auth v1 and unsupported selections never fall back', () => {
  const selected = getContext({ stack: 'go' });
  assert.equal(selected.feature, 'auth');
  assert.equal(selected.profile, 'browser-session-v1');
  assert.throws(() => getContext({ stack: 'go', feature: 'billing' }), /unsupported-feature/);
  assert.throws(() => getContext({ stack: 'node' }), /unsupported-stack/);
  assert.throws(() => getContext({ stack: '__proto__' }), /unsupported-stack/);
  assert.throws(() => getContext({ stack: '../../secrets' }), /unsupported-stack/);
  assert.throws(() => getContext({ stack: 'rust', profile: 'browser-session-v4' }), /unsupported-profile/);
  assert.throws(() => getContext({ stack: 'rust', feature: '' }), /unsupported-feature/);
  assert.throws(() => getContext({ stack: 'rust', profile: '' }), /unsupported-profile/);
  assert.throws(() => getContext(), /stack-required/);
});

test('CLI emits JSON and refuses unknown commands, flags, missing values and ambiguous duplicates', () => {
  const listed = run(['list']);
  assert.equal(listed.status, 0, listed.stderr);
  assert.equal(JSON.parse(listed.stdout).features[0].id, 'auth');
  const selected = run(['context', '--stack', 'react', '--profile', 'browser-session-v3']);
  assert.equal(selected.status, 0, selected.stderr);
  assert.equal(JSON.parse(selected.stdout).stack.role, 'client');
  for (const [feature, profile] of [['authorization', 'rbac-v1'], ['listing', 'offset-list-v1']]) {
    const result = run(['context', '--feature', feature, '--stack', 'react']);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(JSON.parse(result.stdout).profile, profile);
  }
  for (const args of [
    ['init'], ['context'], ['context', '--stack'], ['context', '--stack', '--help'],
    ['context', '--stack', 'go', '--execute'], ['context', '--stack', 'go', '--stack', 'python'],
    ['context', '--stack', 'go', '--feature', 'billing'], ['context', '--stack', 'go', '--profile', 'unknown'],
    ['context', '--stack', 'go', '--feature', 'listing', '--profile', 'rbac-v1'],
    ['list', '--stack', 'go'], ['--help', '--execute'],
  ]) {
    const result = run(args);
    assert.equal(result.status, 1, args.join(' '));
    assert.equal(result.stdout, '', args.join(' '));
    assert.match(result.stderr, /^feature-standards: /);
  }
});

test('help is safe and does not require a selection', () => {
  for (const args of [[], ['--help'], ['-h'], ['list', '--help'], ['context', '--help']]) {
    const result = run(args);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /feature-standards context/);
    assert.match(result.stdout, /Read-only/);
  }
});

test('context only reads package data, even from an unrelated caller directory with no command PATH', () => {
  const caller = mkdtempSync(join(tmpdir(), 'feature-standards-readonly-'));
  try {
    writeFileSync(join(caller, 'feature-standards.json'), '{"feature":"do-not-read-caller"}');
    writeFileSync(join(caller, 'mine.txt'), 'keep');
    const before = readdirSync(caller).map(name => [name, readFileSync(join(caller, name), 'utf8')]);
    for (const feature of listFeatures().features) for (const stack of feature.stacks) for (const profile of stack.profiles) for (const format of [[], ['--compact']]) {
      const result = run(['context', '--feature', feature.id, '--stack', stack.id, '--profile', profile, ...format], { cwd: caller, env: { ...process.env, PATH: '' } });
      assert.equal(result.status, 0, result.stderr);
      assert.equal(JSON.parse(result.stdout).feature, feature.id);
    }
    assert.deepEqual(readdirSync(caller).map(name => [name, readFileSync(join(caller, name), 'utf8')]), before);
  } finally { rmSync(caller, { recursive: true, force: true }); }
});
