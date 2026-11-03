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

test('list describes auth as the current feature with five stack roles and three profiles', () => {
  const result = listFeatures();
  assert.equal(result.features.length, 1);
  assert.equal(result.features[0].id, 'auth');
  assert.deepEqual(result.features[0].profiles, PROFILES);
  assert.deepEqual(result.features[0].stacks.map(stack => stack.id), STACKS);
  assert.equal(result.features[0].stacks.find(stack => stack.id === 'react').role, 'client');
  assert.match(result.provenance.sourceCommit, /^[a-f0-9]{40,64}$/);
  assert.equal(typeof result.provenance.sourceDirty, 'boolean');
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
  for (const args of [
    ['init'], ['context'], ['context', '--stack'], ['context', '--stack', '--help'],
    ['context', '--stack', 'go', '--execute'], ['context', '--stack', 'go', '--stack', 'python'],
    ['context', '--stack', 'go', '--feature', 'billing'], ['context', '--stack', 'go', '--profile', 'unknown'],
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
    for (const stack of STACKS) for (const profile of PROFILES) {
      const result = run(['context', '--feature', 'auth', '--stack', stack, '--profile', profile], { cwd: caller, env: { ...process.env, PATH: '' } });
      assert.equal(result.status, 0, result.stderr);
      assert.equal(JSON.parse(result.stdout).feature, 'auth');
    }
    assert.deepEqual(readdirSync(caller).map(name => [name, readFileSync(join(caller, name), 'utf8')]), before);
  } finally { rmSync(caller, { recursive: true, force: true }); }
});
