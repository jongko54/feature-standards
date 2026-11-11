import { chmodSync, lstatSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { CORE_AUTH_ROOTS, CORE_CHECK_PROTOCOL_VERSION, CORE_FEATURES, CORE_PROFILES } from './core-protocol.mjs';
import { coreSelection, inspectSource, pathText, physicalDirectory, regularFile, sourceCommit, within } from './core-source.mjs';

const PACKAGE = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PACKAGE_VERSION = JSON.parse(readFileSync(join(PACKAGE, 'package.json'), 'utf8')).version;
const slashRelative = (from, to) => relative(from, to).split(sep).join('/');

export function inspectCore(options) {
  const selected = coreSelection(options);
  const inspected = inspectSource(options.source, selected.stack);
  const destination = resolve(pathText(options.dest));
  physicalDirectory(dirname(destination), 'destination-parent');
  try { lstatSync(destination); throw new Error('destination-already-exists'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (within(inspected.source, destination)) throw new Error('destination-inside-source');
  return {
    ...selected, ...inspected, destination, sourceRelative: slashRelative(destination, inspected.source), sourceCommit: sourceCommit(inspected.source),
    dependencies: { auth: { path: slashRelative(destination, join(inspected.source, CORE_AUTH_ROOTS[selected.stack])) }, core: { path: slashRelative(destination, join(inspected.source, 'libraries/' + selected.stack)) } },
  };
}

function templateFiles(directory, prefix = '') {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const name = prefix ? prefix + '/' + entry.name : entry.name;
    if (entry.isSymbolicLink()) throw new Error('core-template-symlink');
    if (entry.isDirectory()) return templateFiles(join(directory, entry.name), name);
    if (!entry.isFile()) throw new Error('unsupported-core-template-entry');
    return [name];
  });
}

function javaCoordinates(source, root, prefix) {
  const pom = readFileSync(regularFile(source, root + '/pom.xml'), 'utf8');
  const header = pom.replace(/<!--[\s\S]*?-->/g, '').replace(/<parent>[\s\S]*?<\/parent>/, '').split('<dependencies>')[0];
  const result = {};
  for (const [field, suffix] of [['groupId', 'GROUP_ID'], ['artifactId', 'ARTIFACT_ID'], ['version', 'VERSION']]) {
    const match = header.match(new RegExp('<' + field + '>([^<]+)</' + field + '>'));
    if (!match || !/^[A-Za-z0-9_.-]+$/.test(match[1])) throw new Error('unsupported-core-maven-coordinate');
    result[prefix + '_' + suffix] = match[1];
  }
  return result;
}

function readme(plan) {
  return `# Feature Standards core starter

Requires Node.js 22.12+ and the selected toolchain: Python 3.12+ with uv, Go 1.26+, JDK 21+ with the checkout's Maven wrapper, or Rust 1.93.1+ with Cargo. Select a JDK explicitly with JAVA_HOME when needed.

This ${plan.stack} app connects an authenticated session to current server-owned membership, authorization policy, visibility, raw-query validation, and a paginated response. It imports the authentication and core packages from your explicit source checkout without copying SDK runtime code.

Selected profiles: browser-session-v1 / rbac-v1 / offset-list-v1. The source checkout is \`${plan.sourceRelative}\`. feature-core.json records its commit, manifest fingerprints, and both relative SDK dependency paths. This source reference does not provide automatic updates or immutable vendoring. Review changes and regenerate when the recorded manifests change.

\`\`\`sh
node project.mjs build
node project.mjs check
node project.mjs demo
\`\`\`

check starts its own loopback HTTP processes using public synthetic fixtures and stops them after success or failure. Its JSON receipt covers normal-start default denial, login, Origin/CSRF, owner and tenant isolation, totals after visibility, typed filters, sorting, pagination, invalid raw queries, logout cookie replay, and actual origins of both SDK dependencies. Database, SMTP, browser UI, production deployment, and security audits require separate verification.

demo explicitly enables loopback HTTP, a sample account, documents, and viewer membership. For normal startup, review .env.example and explicitly export its settings before running the command below. The runner does not load .env files.

\`\`\`sh
node project.mjs start
\`\`\`

Normal start uses Secure cookies and non-demo memory/v1 authentication. It supplies no sample membership or documents, so authenticated users are denied document access by default. Connect your trusted current-membership provider, product document store, and explicit grants before granting access. Never derive roles, tenant, or subject from request headers, bodies, or queries. The provider receives a copy of the original session identity and cannot redefine it. Public document fields are id/name/score/active; tenant and owner scope fields stay on the server.

Routes are GET /api/profile, GET /api/documents, and GET /api/documents/{id}. Listing uses a bounded materialized dataset. Database adapters, migrations, account registration, and email are outside this starter's scope.

Generation does not install dependencies, compile, start servers, or contact a database. build/check execute code from the explicit trusted checkout and language tools; public dependencies can be downloaded. Outputs stay in this app. Java uses generated POM overlays referencing the two original source directories, with an app-local Maven repository and build outputs. SDK source files are not edited. Keep the source checkout and generated app in the same relative layout.
`;
}

export function generateCore(options) {
  const plan = inspectCore(options);
  const values = { AUTH_PATH: JSON.stringify(plan.dependencies.auth.path), CORE_PATH: JSON.stringify(plan.dependencies.core.path) };
  if (plan.stack === 'java') Object.assign(values, javaCoordinates(plan.source, CORE_AUTH_ROOTS.java, 'AUTH'), javaCoordinates(plan.source, 'libraries/java', 'CORE'));
  const templates = join(PACKAGE, 'templates/core', plan.stack);
  const prepared = new Map(templateFiles(templates).map(name => {
    let contents = readFileSync(join(templates, name), 'utf8');
    for (const [key, value] of Object.entries(values)) contents = contents.replaceAll('{{' + key + '}}', value);
    if (/\{\{[A-Z_]+\}\}/.test(contents)) throw new Error('unresolved-core-template-variable');
    return [name, contents];
  }));
  for (const file of ['core-protocol.mjs', 'core-source.mjs', 'core-process.mjs', 'core-check.mjs']) prepared.set(file, readFileSync(join(PACKAGE, 'src', file), 'utf8'));
  prepared.set('project.mjs', readFileSync(join(PACKAGE, 'src/core-project.mjs'), 'utf8'));
  prepared.set('feature-core.json', JSON.stringify({ generator: 'feature-standards', generatorVersion: PACKAGE_VERSION, template: 'core', coreCheckProtocolVersion: CORE_CHECK_PROTOCOL_VERSION,
    stack: plan.stack, profile: plan.profile, features: CORE_FEATURES, profiles: CORE_PROFILES, source: plan.sourceRelative, sourceCommit: plan.sourceCommit,
    sourceManifestsSha256: plan.sourceManifestsSha256, dependencies: plan.dependencies }, null, 2) + '\n');
  prepared.set('README.md', readme(plan));
  prepared.set('.env.example', '# Export explicitly; no dotenv loader is used.\nAUTH_STORE=memory\nAUTH_ACCOUNT_LIFECYCLE=false\nAUTH_DEMO=false\nAUTH_COOKIE_SECURE=true\nAUTH_HOST=127.0.0.1\nAUTH_PORT=8000\nAUTH_ALLOWED_ORIGIN=https://your-app.example\n# Set AUTH_USER_EMAIL and AUTH_USER_PASSWORD; never commit credentials.\n# Connect a trusted current membership provider and product documents before granting access.\n');
  prepared.set('.gitignore', '.env\n.env.*\n!.env.example\n.venv/\n__pycache__/\n.feature-core/\ntarget/\nnode_modules/\n');
  mkdirSync(plan.destination, { mode: 0o755 });
  for (const [name, contents] of prepared) {
    const target = join(plan.destination, name);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, contents, { flag: 'wx', mode: 0o644 });
  }
  chmodSync(join(plan.destination, 'project.mjs'), 0o755);
  return { template: 'core', stack: plan.stack, profile: plan.profile, features: CORE_FEATURES, profiles: CORE_PROFILES, destination: plan.destination, files: [...prepared.keys()].sort() };
}
