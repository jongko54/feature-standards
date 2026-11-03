#!/usr/bin/env node
import { realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { getContext, listFeatures } from './index.mjs';

const HELP = `feature-standards list
feature-standards context --stack python|go|java|rust|react [--feature auth] [--profile browser-session-v1|browser-session-v2|browser-session-v3]

Read-only feature contracts and AI integration context, emitted as JSON.
Authentication is the first and currently available feature. Feature defaults to auth; profile defaults to browser-session-v1.
Packaged document read paths are separate from source-checkout API entrypoints and command guidance.
No checks, migrations, installation, generation or project edits are performed.
`;

export function parseArguments(argv) {
  if (argv.length === 0 || (argv.length === 1 && ['-h', '--help'].includes(argv[0]))) return { help: true };
  const [command, ...rest] = argv;
  if (!['list', 'context'].includes(command)) throw new Error('unknown-command: use list or context; see --help');
  if (rest.length === 1 && ['-h', '--help'].includes(rest[0])) return { help: true };
  if (command === 'list') {
    if (rest.length) throw new Error('unknown-argument: list takes no selection flags');
    return { command };
  }
  const result = { command };
  for (let index = 0; index < rest.length; index++) {
    const argument = rest[index];
    if (!['--feature', '--stack', '--profile'].includes(argument)) throw new Error('unknown-argument: use --feature, --stack or --profile');
    const key = argument.slice(2);
    if (Object.hasOwn(result, key)) throw new Error('duplicate-argument: ' + argument);
    const value = rest[++index];
    if (!value || value.startsWith('-')) throw new Error('missing-argument-value: ' + argument);
    result[key] = value;
  }
  if (!Object.hasOwn(result, 'stack')) throw new Error('stack-required: choose python|go|java|rust|react');
  return result;
}

export function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  if (options.help) { console.log(HELP); return; }
  console.log(JSON.stringify(options.command === 'list' ? listFeatures() : getContext(options), null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(resolve(process.argv[1]))).href) {
  try { main(); }
  catch (error) { console.error('feature-standards: ' + error.message); process.exitCode = 1; }
}
