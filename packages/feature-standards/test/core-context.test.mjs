import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { getCompactContext, getContext } from '../src/index.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CLI = join(PACKAGE, 'src/cli.mjs');
const STACKS = ['python', 'go', 'java', 'rust'];
const SELECTIONS = [['auth', 'browser-session-v1'], ['authorization', 'rbac-v1'], ['listing', 'offset-list-v1']];
const run = (args, options = {}) => spawnSync(process.execPath, [CLI, ...args], { encoding: 'utf8', timeout: 10000, ...options });

test('backend v1, RBAC and materialized contexts lead with the packaged SDK connection card', () => {
  for (const stack of STACKS) for (const [feature, profile] of SELECTIONS) {
    const full = getContext({ feature, stack, profile });
    const card = full.packagedDocuments.sdkConnectionCard;
    assert.ok(card, `${feature}/${stack}/${profile} includes the SDK connection card`);
    assert.ok(existsSync(card.readPath));
    assert.equal(card.readPath, join(PACKAGE, card.packagePath));
    assert.ok(card.packagePath.startsWith('snapshot/'));
    assert.match(card.sha256, /^[a-f0-9]{64}$/);
    assert.equal(createHash('sha256').update(readFileSync(card.readPath)).digest('hex'), card.sha256);
    const compact = getCompactContext({ feature, stack, profile });
    assert.equal(compact.readOnly, true);
    assert.equal(compact.readFirst[0].readPath, card.readPath);
    assert.equal(compact.readFirst[0].sha256, card.sha256);
    assert.equal(compact.source.required, true);
  }
});

test('core context guidance invokes the explicitly selected source CLI and stays separate from auth generation', () => {
  for (const stack of STACKS) for (const [feature, profile] of SELECTIONS) {
    const full = getContext({ feature, stack, profile });
    const starter = full.sourceCheckout.coreStarter;
    assert.ok(starter, `${feature}/${stack}/${profile}`);
    assert.equal(starter.supportedForStack, true);
    assert.equal(starter.template, 'core');
    assert.equal(starter.scope, 'source-checkout');
    assert.equal(starter.cwd, '.');
    assert.equal(starter.executed, false);
    assert.equal(full.sourceCheckout.required, true);
    assert.deepEqual(starter.argv, ['node', 'packages/feature-standards/src/cli.mjs', 'init', '--template', 'core', '--source', '<absolute-checkout>', '--stack', stack, '--dest', '<new-directory-outside-checkout>']);
    assert.match(starter.note, /coreStarterProtocolVersion\s+1/);
    assert.deepEqual(getCompactContext({ feature, stack, profile }).coreStarter, starter);
    assert.equal(full.sourceCheckout.generator.supportedForStack, feature === 'auth');
    if (feature === 'auth') {
      assert.ok(full.sourceCheckout.generator.argv.includes('packages/create-feature-auth/src/cli.mjs'));
      assert.ok(!full.sourceCheckout.generator.argv.includes('--template'));
    }
  }
});

test('database auth, React and PostgreSQL listing contexts do not advertise the memory core starter', () => {
  const unsupported = [
    ...STACKS.flatMap(stack => ['browser-session-v2', 'browser-session-v3'].map(profile => ({ feature: 'auth', stack, profile }))),
    ...SELECTIONS.map(([feature, profile]) => ({ feature, stack: 'react', profile })),
    ...['browser-session-v2', 'browser-session-v3'].map(profile => ({ feature: 'auth', stack: 'react', profile })),
    { feature: 'listing', stack: 'python', profile: 'postgres-list-v1' },
  ];
  for (const options of unsupported) {
    const full = getContext(options);
    assert.equal(full.packagedDocuments.sdkConnectionCard, undefined, JSON.stringify(options));
    assert.equal(full.sourceCheckout.coreStarter, undefined, JSON.stringify(options));
    const compact = getCompactContext(options);
    assert.equal(compact.coreStarter, undefined, JSON.stringify(options));
    assert.deepEqual(compact.readFirst.map(document => document.readPath), [full.packagedDocuments.apiGuide, full.packagedDocuments.consumerGuide, full.packagedDocuments.integrationSkill].map(document => document.readPath));
    if (options.feature === 'auth') assert.equal(full.sourceCheckout.generator.supportedForStack, options.stack !== 'react');
  }
});

test('core context and compact cards only read packaged documents with an empty command PATH', () => {
  const caller = realpathSync(mkdtempSync(join(tmpdir(), 'feature-core-context-')));
  try {
    writeFileSync(join(caller, 'feature-core.json'), '{"generator":"must-not-read-or-execute-caller"}');
    writeFileSync(join(caller, 'mine.txt'), 'keep');
    const before = readdirSync(caller).sort().map(name => [name, readFileSync(join(caller, name), 'utf8')]);
    const documents = new Map();
    for (const stack of STACKS) for (const [feature, profile] of SELECTIONS) for (const compact of [false, true]) {
      const result = run(['context', '--feature', feature, '--stack', stack, '--profile', profile, ...(compact ? ['--compact'] : [])], { cwd: caller, env: { ...process.env, PATH: '' } });
      assert.equal(result.status, 0, result.stderr);
      const output = JSON.parse(result.stdout);
      const starter = compact ? output.coreStarter : output.sourceCheckout.coreStarter;
      assert.equal(starter.executed, false);
      const card = compact ? output.readFirst[0] : output.packagedDocuments.sdkConnectionCard;
      assert.ok(card.readPath.startsWith(join(PACKAGE, 'snapshot') + '/'));
      const bytes = readFileSync(card.readPath);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), card.sha256);
      if (documents.has(card.readPath)) assert.deepEqual(bytes, documents.get(card.readPath));
      else documents.set(card.readPath, bytes);
    }
    const rejectedSource = run(['context', '--stack', 'python', '--source', caller], { cwd: caller, env: { ...process.env, PATH: '' } });
    assert.equal(rejectedSource.status, 1, 'context does not accept an executable source checkout');
    assert.equal(rejectedSource.stdout, '');
    assert.deepEqual(readdirSync(caller).sort().map(name => [name, readFileSync(join(caller, name), 'utf8')]), before);
    for (const [path, bytes] of documents) assert.deepEqual(readFileSync(path), bytes);
  } finally { rmSync(caller, { recursive: true, force: true }); }
});
