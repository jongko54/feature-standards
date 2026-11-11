import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { command, processEnvironment } from '../src/core-process.mjs';
import { coreEnvironment } from '../src/core-project.mjs';

test('ambient JVM launch options cannot override the fixture address or port', () => {
  const inherited = { PATH: '/safe/bin', JAVA_HOME: '/selected-jdk', _JAVA_OPTIONS: '-Dserver.address=0.0.0.0', JAVA_TOOL_OPTIONS: '-Dserver.port=9999', JDK_JAVA_OPTIONS: '-Dserver.port=9998' };
  for (const mode of ['build', 'start', 'demo', 'check', 'normal-check']) {
    const environment = coreEnvironment(mode, inherited, 'http://127.0.0.1:18555');
    for (const key of ['_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS']) assert.equal(environment[key], undefined, mode + '/' + key);
    assert.equal(environment.JAVA_HOME, inherited.JAVA_HOME);
  }
  const processEnv = processEnvironment('/owned-app', inherited);
  for (const key of ['_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS']) assert.equal(processEnv[key], undefined);
  assert.equal(inherited._JAVA_OPTIONS, '-Dserver.address=0.0.0.0');
});

test('captured JSON waits for stdout closure after the original process exits', { skip: process.platform === 'win32', timeout: 10000 }, async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), 'core-command-drain-')));
  try {
    const suffix = `setTimeout(() => process.stdout.write('complete"}'), 80);`;
    const parent = `const {spawn}=require('node:child_process'); process.stdout.write('{"value":"'); spawn(process.execPath,['-e',${JSON.stringify(suffix)}],{stdio:'inherit'}); process.exit(0);`;
    const output = await command(process.execPath, ['-e', parent], directory, process.env, { capture: true, timeout: 5000 });
    assert.deepEqual(JSON.parse(output), { value: 'complete' });
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('large SDK metadata output is captured completely without truncating its JSON tail', { timeout: 10000 }, async () => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), 'core-command-large-')));
  try {
    const output = await command(process.execPath, ['-e', `process.stdout.write(JSON.stringify({payload:'x'.repeat(1024*1024),tail:'done'}));`], directory, process.env, { capture: true, timeout: 5000 });
    const data = JSON.parse(output);
    assert.equal(data.payload.length, 1024 * 1024);
    assert.equal(data.tail, 'done');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
