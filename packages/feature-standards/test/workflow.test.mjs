import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { fixtureReceipt, fixtureSource } from './workflow-fixture.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CLI = join(PACKAGE, 'src/cli.mjs');
const run = (args, cwd) => spawnSync(process.execPath, [CLI, ...args], { cwd, encoding: 'utf8', timeout: 10000 });
const temporary = body => {
  const scratch = realpathSync(mkdtempSync(join(tmpdir(), 'feature-standards-workflow-')));
  try { return body(scratch); }
  finally { rmSync(scratch, { recursive: true, force: true }); }
};
const initArgs = (source, dest, profile = 'browser-session-v1') => ['init', '--feature', 'auth', '--source', source, '--stack', 'python', '--profile', profile, '--dest', dest];

test('init delegates to the explicitly selected source generator without running checks by default', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const dest = join(scratch, 'new-app');
  const result = run(initArgs(source, dest, 'browser-session-v3'), scratch);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.feature, 'auth');
  assert.equal(output.profile, 'browser-session-v3');
  assert.equal(output.check.executed, false);
  assert.ok(existsSync(join(source, 'generator-imported.txt')));
  assert.ok(existsSync(join(dest, 'project.mjs')));
  assert.ok(!existsSync(join(dest, 'check-ran.txt')));
}));

test('explicit check and init --check return the selected profile receipt', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const dest = join(scratch, 'new-app');
  const initialized = run([...initArgs(source, dest, 'browser-session-v2'), '--check'], scratch);
  assert.equal(initialized.status, 0, initialized.stderr);
  const init = JSON.parse(initialized.stdout);
  assert.equal(init.check.executed, true);
  assert.equal(init.check.profile, 'browser-session-v2');
  assert.equal(init.check.database.isolated, true);
  const checked = run(['check', '--project', dest], scratch);
  assert.equal(checked.status, 0, checked.stderr);
  const receipt = JSON.parse(checked.stdout);
  assert.equal(receipt.profile, 'browser-session-v2');
  assert.equal(receipt.passed, true);
  assert.ok(existsSync(join(dest, 'check-ran.txt')));
}));

test('invalid selectors and ambiguous flags fail before importing the generator or creating a target', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const dest = join(scratch, 'new-app');
  const prefix = ['init', '--source', source, '--dest', dest];
  for (const args of [
    [...prefix, '--stack', 'react'], [...prefix, '--stack', 'python', '--feature', 'billing'],
    [...prefix, '--stack', 'python', '--profile', 'unknown'], [...prefix, '--stack', 'python', '--check', '--check'],
    [...prefix, '--stack', 'python', '--stack', 'go'], [...prefix, '--stack'],
    [...prefix, '--stack', 'python', '--execute'], ['check', '--project', dest, '--check'],
    ['check', '--project', dest, '--project', source],
  ]) {
    const result = run(args, scratch);
    assert.equal(result.status, 1, args.join(' '));
    assert.equal(result.stdout, '');
    assert.ok(!existsSync(dest));
    assert.ok(!existsSync(join(source, 'generator-imported.txt')));
  }
}));

test('legacy source generators and generated runners are refused before executing their code', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'), { version: '0.1.1' });
  const dest = join(scratch, 'new-app');
  const oldSource = run(initArgs(source, dest), scratch);
  assert.equal(oldSource.status, 1);
  assert.match(oldSource.stderr, /generator-version-unsupported/);
  assert.ok(!existsSync(dest));
  assert.ok(!existsSync(join(source, 'generator-imported.txt')));
  mkdirSync(dest);
  writeFileSync(join(dest, 'feature-auth.json'), JSON.stringify({ generator: '@ugauga/create-feature-auth', generatorVersion: '0.1.1', stack: 'python', profile: 'browser-session-v3', source: '../source' }));
  writeFileSync(join(dest, 'project.mjs'), "throw new Error('legacy-runner-must-not-be-imported');");
  const oldProject = run(['check', '--project', dest], scratch);
  assert.equal(oldProject.status, 1);
  assert.match(oldProject.stderr, /project-check-protocol-unsupported/);
  assert.ok(!oldProject.stderr.includes('legacy-runner-must-not-be-imported'));
}));

test('symlinked sources, generator files, projects and runners are refused', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const sourceLink = join(scratch, 'source-link');
  symlinkSync(source, sourceLink, 'dir');
  assert.equal(run(initArgs(sourceLink, join(scratch, 'not-created')), scratch).status, 1);
  assert.ok(!existsSync(join(source, 'generator-imported.txt')));
  const outside = join(scratch, 'outside.mjs');
  writeFileSync(outside, "throw new Error('outside-module-must-not-run');");
  const generator = join(source, 'packages/create-feature-auth/src/cli.mjs');
  rmSync(generator); symlinkSync(outside, generator);
  const linkedGenerator = run(initArgs(source, join(scratch, 'not-created')), scratch);
  assert.equal(linkedGenerator.status, 1);
  assert.ok(!linkedGenerator.stderr.includes('outside-module-must-not-run'));
  rmSync(generator); fixtureSource(source);
  const dest = join(scratch, 'new-app');
  assert.equal(run(initArgs(source, dest), scratch).status, 0);
  const projectLink = join(scratch, 'project-link');
  symlinkSync(dest, projectLink, 'dir');
  assert.equal(run(['check', '--project', projectLink], scratch).status, 1);
  rmSync(join(dest, 'project.mjs')); symlinkSync(outside, join(dest, 'project.mjs'));
  const linkedRunner = run(['check', '--project', dest], scratch);
  assert.equal(linkedRunner.status, 1);
  assert.ok(!linkedRunner.stderr.includes('outside-module-must-not-run'));
}));

test('failed, mismatched and memory-only receipts cannot pass a selected PostgreSQL check', () => temporary(scratch => {
  const invalid = [
    { ...fixtureReceipt('python', 'browser-session-v3'), profile: 'browser-session-v1' },
    { ...fixtureReceipt('python', 'browser-session-v3'), stack: 'go' },
    { ...fixtureReceipt('python', 'browser-session-v3'), passed: false },
    { ...fixtureReceipt('python', 'browser-session-v3'), checks: [] },
    { ...fixtureReceipt('python', 'browser-session-v3'), database: { used: false, isolated: false } },
    { ...fixtureReceipt('python', 'browser-session-v3'), database: { used: true, isolated: false } },
    { ...fixtureReceipt('python', 'browser-session-v3'), database: { used: true, isolated: true, existingDatabaseModified: true } },
  ];
  invalid.forEach((receipt, index) => {
    const source = fixtureSource(join(scratch, 'source-' + index), { receipt });
    const result = run([...initArgs(source, join(scratch, 'app-' + index), 'browser-session-v3'), '--check'], scratch);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /invalid-check-receipt/);
    assert.equal(result.stdout, '');
  });
}));

test('a different generator identity or malformed manifest is rejected before import', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const metadata = join(source, 'packages/create-feature-auth/package.json');
  writeFileSync(metadata, JSON.stringify({ name: 'different-generator', version: '0.2.0', type: 'module' }));
  assert.equal(run(initArgs(source, join(scratch, 'new-app')), scratch).status, 1);
  assert.ok(!existsSync(join(source, 'generator-imported.txt')));
  fixtureSource(source);
  writeFileSync(join(source, 'feature-standards.json'), JSON.stringify({ schema_version: 1, feature: 'billing', stacks: [], profiles: [] }));
  assert.equal(run(initArgs(source, join(scratch, 'new-app')), scratch).status, 1);
  assert.ok(!existsSync(join(source, 'generator-imported.txt')));
}));

test('existing destinations, destinations inside source, and linked parents preserve files before import', () => temporary(scratch => {
  const source = fixtureSource(join(scratch, 'source'));
  const keep = join(scratch, 'keep');
  mkdirSync(keep); writeFileSync(join(keep, 'mine.txt'), 'preserve');
  const physical = join(scratch, 'physical'); mkdirSync(physical);
  const parentLink = join(scratch, 'linked-parent'); symlinkSync(physical, parentLink, 'dir');
  for (const dest of [keep, join(source, 'inside'), join(parentLink, 'new-app')]) {
    const result = run(initArgs(source, dest), scratch);
    assert.equal(result.status, 1);
    assert.ok(!existsSync(join(source, 'generator-imported.txt')));
  }
  assert.equal(readFileSync(join(keep, 'mine.txt'), 'utf8'), 'preserve');
  assert.ok(!existsSync(join(physical, 'new-app')));
}));

test('the public Node API exposes explicit workflows while rejecting invalid options before source code runs', async () => {
  const { initFeature, checkProject } = await import('../src/index.mjs');
  assert.equal(typeof initFeature, 'function'); assert.equal(typeof checkProject, 'function');
  for (const options of [null, [], { stack: 'python', execute: true }, { stack: 'python', check: 'true' }, { feature: 'billing', stack: 'python' }]) {
    await assert.rejects(initFeature(options));
  }
  for (const options of [null, [], { project: '.', check: true }, {}]) await assert.rejects(checkProject(options));
});

test('importing the CLI from stdin does not attempt to execute or resolve a nonexistent argv script', () => {
  const result = spawnSync(process.execPath, ['--input-type=module', '-'], {
    input: `import {parseArguments} from ${JSON.stringify(new URL('../src/cli.mjs', import.meta.url).href)}; console.log(parseArguments(['list']).command);`,
    encoding: 'utf8', timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, 'list\n');
});
