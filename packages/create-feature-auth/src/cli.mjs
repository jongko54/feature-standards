#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import {
  chmodSync, lstatSync, mkdirSync, readFileSync, readdirSync,
  realpathSync, writeFileSync,
} from 'node:fs';
import { dirname, isAbsolute, join, parse, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PACKAGE_VERSION = JSON.parse(readFileSync(join(PACKAGE, 'package.json'), 'utf8')).version;
export const STACKS = Object.freeze({
  python: 'implementations/python-fastapi',
  go: 'implementations/go-net-http',
  java: 'implementations/java-spring',
  rust: 'implementations/rust-axum',
});
export const PROFILES = Object.freeze(['browser-session-v1', 'browser-session-v2', 'browser-session-v3']);

export function within(parent, child) {
  const distance = relative(parent, child);
  return distance === '' || (!isAbsolute(distance) && distance !== '..' && !distance.startsWith('..' + sep));
}

function pathText(value) {
  if (typeof value !== 'string' || !value || /[\0-\x1f\x7f]/.test(value)) throw new Error('invalid-path');
  return value;
}

function noDestinationLinks(path) {
  let current = parse(path).root;
  for (const part of path.slice(current.length).split(sep).filter(Boolean)) {
    current = join(current, part);
    if (lstatSync(current).isSymbolicLink()) throw new Error('destination-symlink');
  }
}

function regularSource(root, relativePath) {
  const candidate = join(root, relativePath);
  const physical = realpathSync(candidate);
  if (!within(root, physical) || !lstatSync(physical).isFile()) throw new Error('source-file-escape');
  return physical;
}

function mavenCoordinates(source) {
  const pom = readFileSync(regularSource(source, 'implementations/java-spring/pom.xml'), 'utf8');
  const header = pom.replace(/<!--[\s\S]*?-->/g, '').replace(/<parent>[\s\S]*?<\/parent>/, '').split('<dependencies>')[0];
  const result = {};
  for (const [field, key] of [['groupId', 'JAVA_GROUP'], ['artifactId', 'JAVA_ARTIFACT'], ['version', 'JAVA_VERSION']]) {
    const match = header.match(new RegExp('<' + field + '>([^<]+)</' + field + '>'));
    if (!match || !/^[A-Za-z0-9_.-]+$/.test(match[1])) throw new Error('unsupported-maven-coordinate');
    result[key] = match[1];
  }
  return result;
}

function gitOrigin(source) {
  const environment = { ...process.env };
  for (const key of Object.keys(environment)) if (key.startsWith('GIT_')) delete environment[key];
  const result = spawnSync('git', ['-C', source, 'rev-parse', 'HEAD'], { encoding: 'utf8', env: environment, timeout: 3000, stdio: ['ignore', 'pipe', 'ignore'] });
  const commit = result.status === 0 ? result.stdout.trim() : '';
  return /^[0-9a-f]{40,64}$/.test(commit) ? commit : null;
}

export function inspect(options) {
  if (!Object.hasOwn(STACKS, options.stack)) throw new Error('unsupported-stack');
  if (!PROFILES.includes(options.profile)) throw new Error('unsupported-profile');
  const source = realpathSync(resolve(pathText(options.source)));
  if (!lstatSync(source).isDirectory()) throw new Error('source-not-directory');
  const manifestPath = regularSource(source, 'feature-standards.json');
  const contents = readFileSync(manifestPath, 'utf8');
  const manifest = JSON.parse(contents);
  if (manifest.feature !== 'auth' || manifest.schema_version !== 1
    || !Array.isArray(manifest.stacks) || !Array.isArray(manifest.profiles)
    || !manifest.profiles.some(profile => profile.id === options.profile)
    || !manifest.stacks.some(stack => stack.id === options.stack && stack.root === STACKS[options.stack] && Array.isArray(stack.profiles) && stack.profiles.includes(options.profile))) {
    throw new Error('unsupported-source-manifest');
  }
  const markers = { python: 'feature_auth/__init__.py', go: 'auth/server.go', java: 'pom.xml', rust: 'Cargo.toml' };
  regularSource(source, STACKS[options.stack] + '/' + markers[options.stack]);
  const destination = resolve(pathText(options.dest));
  const parent = dirname(destination);
  noDestinationLinks(parent);
  if (!lstatSync(parent).isDirectory()) throw new Error('destination-parent-not-directory');
  try { lstatSync(destination); throw new Error('destination-already-exists'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (within(source, destination)) throw new Error('destination-inside-source');
  return {
    source, destination,
    sourceRelative: relative(destination, source).split(sep).join('/'),
    libraryRelative: relative(destination, join(source, STACKS[options.stack])).split(sep).join('/'),
    sourceCommit: gitOrigin(source),
    manifestSha256: createHash('sha256').update(contents).digest('hex'),
  };
}

function templateFiles(directory, prefix = '') {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const name = prefix ? prefix + '/' + entry.name : entry.name;
    if (entry.isSymbolicLink()) throw new Error('template-symlink');
    if (entry.isDirectory()) return templateFiles(join(directory, entry.name), name);
    if (!entry.isFile()) throw new Error('unsupported-template-entry');
    return [name];
  });
}

function environmentExample(profile) {
  const database = profile !== 'browser-session-v1';
  return `# Read this file and explicitly export the settings you need. No dotenv loader is used.
AUTH_STORE=${database ? 'postgres' : 'memory'}
AUTH_ACCOUNT_LIFECYCLE=${profile === 'browser-session-v3'}
AUTH_HOST=127.0.0.1
AUTH_PORT=8000
AUTH_ALLOWED_ORIGIN=https://your-app.example
AUTH_COOKIE_SECURE=true
AUTH_DEMO=false
${database ? '# Set AUTH_DATABASE_URL in your environment; never commit credentials.\n' : '# Set AUTH_USER_EMAIL and AUTH_USER_PASSWORD in your environment.\n'}`;
}

function generatedReadme(stack, profile, sourceRelative) {
  return `# Generated authentication consumer

This ${stack} project imports the Feature Standards authentication library and owns only a thin adapter for GET /api/profile. Selected profile: \`${profile}\`.

The explicit source checkout is \`${sourceRelative}\`. Keep its relative location stable, or update feature-auth.json and the language dependency path together. Originating commit and manifest fingerprint are recorded in feature-auth.json. This is a source dependency, not an automatic update mechanism.

\`\`\`sh
node project.mjs build
node project.mjs check
# Configure the selected profile, then start the app:
node project.mjs start
\`\`\`

The memory check uses a unique loopback port, public demo credentials, a local Origin and non-Secure cookies. It verifies anonymous rejection, login, protected identity, CSRF rejection, logout, and rejection of the copied old cookie. **It always exercises memory v1, even when this project selects v2 or v3.** It does not validate PostgreSQL or account lifecycle behavior. \`node project.mjs demo\` explicitly allows local HTTP while preserving the selected profile; database profiles still require your own database configuration.

Review .env.example and export settings explicitly. Normal start keeps Secure cookies enabled by default and requires configuration appropriate to your origin. The runner does not read .env automatically.

For v2/v3, provision a dedicated database and explicitly run the source checkout's database tool. v2 uses \`migrate\`; v3 uses \`migrate-accounts\` and schema 2. The generator and runner never migrate, seed, or inspect a database. Use the source profile specification before changing an existing database. Add a reverse proxy and HTTPS for production use.

\`check\` builds only this project and reads the chosen library source. Java uses a generated Maven overlay that references source directories without copying authentication source, with build output and its Maven repository under .feature-auth/. No source checkout files are edited. Building can download public language dependencies. Commands run code from your explicitly selected checkout; this tool is not a sandbox for untrusted code.
`;
}

export function generate(options) {
  const plan = inspect(options);
  const values = { SOURCE_PATH: JSON.stringify(plan.libraryRelative) };
  if (options.stack === 'java') Object.assign(values, mavenCoordinates(plan.source));
  const directory = join(PACKAGE, 'templates', options.stack);
  const prepared = new Map(templateFiles(directory).map(name => {
    let contents = readFileSync(join(directory, name), 'utf8');
    for (const [key, value] of Object.entries(values)) contents = contents.replaceAll('{{' + key + '}}', value);
    if (/\{\{[A-Z_]+\}\}/.test(contents)) throw new Error('unresolved-template-variable');
    return [name, contents];
  }));
  prepared.set('project.mjs', readFileSync(join(PACKAGE, 'src/project.mjs'), 'utf8'));
  prepared.set('feature-auth.json', JSON.stringify({
    generator: '@ugauga/create-feature-auth', generatorVersion: PACKAGE_VERSION, stack: options.stack,
    profile: options.profile, source: plan.sourceRelative, sourceCommit: plan.sourceCommit,
    sourceManifestSha256: plan.manifestSha256,
  }, null, 2) + '\n');
  prepared.set('.env.example', environmentExample(options.profile));
  prepared.set('.gitignore', '.env\n.env.*\n!.env.example\n.venv/\n__pycache__/\n.feature-auth/\ntarget/\nnode_modules/\n');
  prepared.set('README.md', generatedReadme(options.stack, options.profile, plan.sourceRelative));
  // Atomic mkdir and exclusive writes preserve existing user files, including dangling links.
  mkdirSync(plan.destination, { mode: 0o755 });
  for (const [name, contents] of prepared) {
    const target = join(plan.destination, name);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, contents, { flag: 'wx', mode: 0o644 });
  }
  chmodSync(join(plan.destination, 'project.mjs'), 0o755);
  return { stack: options.stack, profile: options.profile, destination: plan.destination, files: [...prepared.keys()].sort() };
}

export function parseArguments(argv) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) return { help: true };
  const result = { profile: 'browser-session-v1', check: false };
  for (let index = 0; index < argv.length; index++) {
    const argument = argv[index];
    if (argument === '--check') {
      if (result.check) throw new Error('duplicate-argument');
      result.check = true;
    } else if (['--source', '--stack', '--profile', '--dest'].includes(argument)) {
      const name = argument.slice(2);
      if (Object.hasOwn(result, '_' + name)) throw new Error('duplicate-argument');
      const value = argv[++index];
      if (!value || value.startsWith('--')) throw new Error('missing-argument-value');
      result[name] = value; result['_' + name] = true;
    } else throw new Error('unknown-argument');
  }
  if (!result.source || !result.stack || !result.dest) throw new Error('source-stack-dest-required');
  return result;
}

export async function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  if (options.help) {
    console.log('create-feature-auth --source CHECKOUT --stack python|go|java|rust --dest NEW_DIRECTORY [--profile browser-session-v1|browser-session-v2|browser-session-v3] [--check]');
    return;
  }
  const result = generate(options);
  if (options.check) {
    const runner = await import(pathToFileURL(join(result.destination, 'project.mjs')).href);
    await runner.runProject('check', result.destination);
    result.check = 'memory-v1-http-pass';
  }
  console.log(JSON.stringify(result, null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(resolve(process.argv[1]))).href) {
  main().catch(error => { console.error('create-feature-auth: ' + error.message); process.exitCode = 1; });
}
