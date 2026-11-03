import { mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export function fixtureReceipt(stack = 'python', profile = 'browser-session-v1') {
  const database = profile === 'browser-session-v1'
    ? { used: false, isolated: false }
    : { used: true, isolated: true, created: true, dropped: true, existingDatabaseModified: false };
  return { schemaVersion: 1, stack, profile, passed: true, checks: ['selected-profile', 'login', 'logout'], database };
}

export function fixtureSource(directory, { version = '0.2.0', receipt } = {}) {
  mkdirSync(directory, { recursive: true });
  const source = realpathSync(directory);
  const packageDirectory = join(source, 'packages/create-feature-auth');
  mkdirSync(join(packageDirectory, 'src'), { recursive: true });
  writeFileSync(join(packageDirectory, 'package.json'), JSON.stringify({ name: '@ugauga/create-feature-auth', version, type: 'module' }));
  writeFileSync(join(source, 'feature-standards.json'), JSON.stringify({
    schema_version: 1, feature: 'auth',
    stacks: ['python', 'go', 'java', 'rust'].map(id => ({ id, profiles: ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'] })),
    profiles: ['browser-session-v1', 'browser-session-v2', 'browser-session-v3'].map(id => ({ id })),
  }));
  writeFileSync(join(packageDirectory, 'src/cli.mjs'), `
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
const source = ${JSON.stringify(source)};
writeFileSync(join(source, 'generator-imported.txt'), 'explicit init imported the selected generator');
export function generate(options) {
  mkdirSync(options.dest);
  const metadata = { generator: '@ugauga/create-feature-auth', generatorVersion: ${JSON.stringify(version)}, checkProtocolVersion: 1,
    stack: options.stack, profile: options.profile, source: relative(options.dest, source) };
  writeFileSync(join(options.dest, 'feature-auth.json'), JSON.stringify(metadata));
  const database = options.profile === 'browser-session-v1' ? { used: false, isolated: false }
    : { used: true, isolated: true, created: true, dropped: true, existingDatabaseModified: false };
  const receipt = ${receipt ? JSON.stringify(receipt) : 'undefined'} ?? { schemaVersion: 1, stack: options.stack, profile: options.profile,
    passed: true, checks: ['selected-profile', 'login', 'logout'], database };
  const runner = "import { writeFileSync } from 'node:fs'; import { join } from 'node:path';\\n"
    + "export async function runProject(mode, directory) { if (mode !== 'check') throw new Error('unexpected-mode'); writeFileSync(join(directory, 'check-ran.txt'), 'explicit check'); return " + JSON.stringify(receipt) + "; }\\n";
  writeFileSync(join(options.dest, 'project.mjs'), runner);
  return { stack: options.stack, profile: options.profile, destination: options.dest, files: ['feature-auth.json', 'project.mjs'] };
}
`);
  return source;
}
