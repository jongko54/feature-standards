#!/usr/bin/env node
import { realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { checkProject, getContext, initFeature, listFeatures } from './index.mjs';

const HELP = `feature-standards list
feature-standards context --stack python|go|java|rust|react [--feature auth|authorization|listing] [--profile PROFILE]
feature-standards init --source CHECKOUT --stack python|go|java|rust --dest NEW_DIRECTORY [--feature auth] [--profile browser-session-v1|browser-session-v2|browser-session-v3] [--check]
feature-standards check --project GENERATED_DIRECTORY

Read-only list/context select feature contracts and AI integration context, emitted as JSON.
Available features: auth (browser-session-v1/v2/v3), authorization (rbac-v1), listing (offset-list-v1).
Feature defaults to auth; profile defaults to the selected feature's first profile.
Packaged document read paths are separate from source-checkout API entrypoints and command guidance.
Explicit init supports auth only and creates a new project through a trusted source checkout's generator >=0.2.0.
Explicit check or init --check executes trusted project code and toolchains for the selected profile.
Database checks require FEATURE_STANDARDS_TEST_DATABASE_URL and use a new isolated test database.
list/context never execute checks, migrations, installation, generation or project edits.
`;

export function parseArguments(argv) {
  if (argv.length === 0 || (argv.length === 1 && ['-h', '--help'].includes(argv[0]))) return { help: true };
  const [command, ...rest] = argv;
  if (!['list', 'context', 'init', 'check'].includes(command)) throw new Error('unknown-command: use list, context, init or check; see --help');
  if (rest.length === 1 && ['-h', '--help'].includes(rest[0])) return { help: true };
  if (command === 'list') {
    if (rest.length) throw new Error('unknown-argument: list takes no selection flags');
    return { command };
  }
  const result = { command };
  const flags = command === 'check' ? ['--project'] : ['--feature', '--stack', '--profile', ...(command === 'init' ? ['--source', '--dest'] : [])];
  for (let index = 0; index < rest.length; index++) {
    const argument = rest[index];
    if (command === 'init' && argument === '--check') {
      if (Object.hasOwn(result, 'check')) throw new Error('duplicate-argument: --check');
      result.check = true;
      continue;
    }
    if (!flags.includes(argument)) throw new Error('unknown-argument: see --help');
    const key = argument.slice(2);
    if (Object.hasOwn(result, key)) throw new Error('duplicate-argument: ' + argument);
    const value = rest[++index];
    if (!value || value.startsWith('-')) throw new Error('missing-argument-value: ' + argument);
    result[key] = value;
  }
  if (command === 'check') {
    if (!Object.hasOwn(result, 'project')) throw new Error('project-required: choose an existing generated directory');
  } else if (!Object.hasOwn(result, 'stack')) throw new Error('stack-required: choose python|go|java|rust|react');
  if (command === 'init' && (!Object.hasOwn(result, 'source') || !Object.hasOwn(result, 'dest'))) throw new Error('source-and-dest-required');
  return result;
}

export async function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  if (options.help) { console.log(HELP); return; }
  const { command, ...selection } = options;
  const result = command === 'list' ? listFeatures() : command === 'context' ? getContext(selection)
    : command === 'init' ? await initFeature(selection) : await checkProject(selection);
  console.log(JSON.stringify(result, null, 2));
}

function directlyInvoked() {
  if (!process.argv[1]) return false;
  try { return import.meta.url === pathToFileURL(realpathSync(resolve(process.argv[1]))).href; }
  catch { return false; }
}

if (directlyInvoked()) {
  main().catch(error => { console.error('feature-standards: ' + error.message); process.exitCode = 1; });
}
