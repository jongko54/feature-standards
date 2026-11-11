#!/usr/bin/env node
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { inspectProject, within } from './core-source.mjs';
import { command, processEnvironment } from './core-process.mjs';
import { checkCore } from './core-check.mjs';

const TEST_PASSWORD = 'correct-horse-battery-staple';

export function coreEnvironment(mode, inherited = process.env, base) {
  if (!['build', 'start', 'demo', 'check', 'normal-check'].includes(mode)) throw new Error('unsupported-core-runtime-mode');
  const environment = { ...inherited };
  for (const key of Object.keys(environment)) if (/^(AUTH_|PG|FEATURE_STANDARDS_|DB_|DATABASE_|ACCOUNT_|SMTP_|MAIL_|SPRING_|SERVER_|PORT$|JAVA_TOOL_OPTIONS$|JDK_JAVA_OPTIONS$|_JAVA_OPTIONS$)/.test(key)) delete environment[key];
  Object.assign(environment, { AUTH_STORE: 'memory', AUTH_ACCOUNT_LIFECYCLE: 'false', AUTH_DEMO: 'false', AUTH_COOKIE_SECURE: 'true' });
  if (mode === 'start') {
    for (const key of ['AUTH_HOST', 'AUTH_PORT', 'AUTH_ALLOWED_ORIGIN', 'AUTH_USER_EMAIL', 'AUTH_USER_PASSWORD', 'AUTH_SESSION_TTL_SECONDS', 'AUTH_RATE_LIMIT_MAX', 'AUTH_RATE_LIMIT_WINDOW_SECONDS']) {
      if (inherited[key] !== undefined) environment[key] = inherited[key];
    }
  } else if (mode === 'demo') {
    Object.assign(environment, { AUTH_DEMO: 'true', AUTH_COOKIE_SECURE: 'false', AUTH_HOST: '127.0.0.1', AUTH_PORT: inherited.AUTH_PORT || '8000', AUTH_ALLOWED_ORIGIN: 'http://127.0.0.1:5173', AUTH_USER_EMAIL: 'demo@example.com', AUTH_USER_PASSWORD: TEST_PASSWORD });
  } else if (mode === 'check' || mode === 'normal-check') {
    let address;
    try { address = new URL(base); } catch { throw new Error('unsafe-core-check-address'); }
    if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' || !address.port || address.username || address.password || address.pathname !== '/' || address.search || address.hash) throw new Error('unsafe-core-check-address');
    Object.assign(environment, { AUTH_HOST: '127.0.0.1', AUTH_PORT: address.port,
      AUTH_ALLOWED_ORIGIN: mode === 'normal-check' ? 'https://core-starter-check.invalid' : address.origin,
      AUTH_DEMO: String(mode === 'check'), AUTH_COOKIE_SECURE: String(mode !== 'check'),
      AUTH_USER_EMAIL: mode === 'check' ? 'demo@example.com' : 'core-starter@example.com', AUTH_USER_PASSWORD: TEST_PASSWORD,
      AUTH_SESSION_TTL_SECONDS: '1800', AUTH_RATE_LIMIT_MAX: '1000', AUTH_RATE_LIMIT_WINDOW_SECONDS: '60' });
  }
  return environment;
}

const xml = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

function javaCoordinates(library) {
  const pom = readFileSync(join(library, 'pom.xml'), 'utf8');
  const header = pom.replace(/<!--[\s\S]*?-->/g, '').replace(/<parent>[\s\S]*?<\/parent>/, '').split('<dependencies>')[0];
  const result = {};
  for (const field of ['groupId', 'artifactId', 'version']) {
    const match = header.match(new RegExp('<' + field + '>([^<]+)</' + field + '>'));
    if (!match || !/^[A-Za-z0-9_.-]+$/.test(match[1])) throw new Error('unsupported-core-maven-coordinate');
    result[field] = match[1];
  }
  return result;
}

async function build(config, environment) {
  const directory = config.directory;
  if (config.stack === 'python') return command('uv', ['sync', '--project', directory], directory, environment);
  if (config.stack === 'go') {
    await command('go', ['mod', 'tidy'], directory, environment);
    mkdirSync(join(directory, '.feature-core'), { recursive: true });
    return command('go', ['build', '-o', join(directory, '.feature-core', process.platform === 'win32' ? 'server.exe' : 'server'), '.'], directory, environment);
  }
  if (config.stack === 'rust') return command('cargo', ['build', '--locked'], directory, environment);
  const wrapper = join(config.dependencies.auth, process.platform === 'win32' ? 'mvnw.cmd' : 'mvnw');
  const repository = join(directory, '.feature-core/m2');
  for (const name of ['auth', 'core']) {
    const library = config.dependencies[name];
    const staging = join(directory, '.feature-core', 'java-' + name);
    mkdirSync(staging, { recursive: true });
    let pom = readFileSync(join(library, 'pom.xml'), 'utf8');
    if (!pom.includes('<build>') || pom.includes('<sourceDirectory>') || pom.includes('<directory>../')) throw new Error('unsupported-core-java-source-layout');
    // All outputs and the Maven repository stay under this generated app. The SDK
    // source and resources are referenced directly, never copied or edited.
    pom = pom.replace(/<resources>[\s\S]*?<\/resources>/, '').replace('<build>', `<build>
      <directory>${xml(join(staging, 'target'))}</directory>
      <sourceDirectory>${xml(join(library, 'src/main/java'))}</sourceDirectory>
      <resources>
        <resource><directory>${xml(join(library, 'src/main/resources'))}</directory></resource>
        <resource><directory>${xml(library)}</directory><targetPath>META-INF</targetPath><includes><include>LICENSE</include></includes></resource>
      </resources>`);
    writeFileSync(join(staging, 'pom.xml'), pom);
    await command(wrapper, ['-q', '-f', join(staging, 'pom.xml'), '-Dmaven.test.skip=true', '-Dmaven.repo.local=' + repository, 'install'], directory, environment);
  }
  return command(wrapper, ['-q', '-f', join(directory, 'pom.xml'), '-Dmaven.repo.local=' + repository, 'package'], directory, environment);
}

function startCommand(config, environment) {
  const directory = config.directory;
  if (config.stack === 'python') return ['uv', ['run', '--frozen', '--project', directory, 'uvicorn', 'app:app', '--no-proxy-headers', '--host', environment.AUTH_HOST || '127.0.0.1', '--port', environment.AUTH_PORT || '8000']];
  if (config.stack === 'go') return [join(directory, '.feature-core', process.platform === 'win32' ? 'server.exe' : 'server'), []];
  if (config.stack === 'rust') return [join(directory, 'target/debug', process.platform === 'win32' ? 'feature-core-generated.exe' : 'feature-core-generated'), []];
  const java = environment.JAVA_HOME ? join(environment.JAVA_HOME, 'bin', process.platform === 'win32' ? 'java.exe' : 'java') : 'java';
  return [java, ['-jar', join(directory, 'target/generated-core-app.jar')]];
}

async function dependencyOrigins(config, environment) {
  const origins = {};
  const record = (name, resolved, method, runtimeOrigin) => {
    const physical = realpathSync(resolved);
    const expectedPath = realpathSync(config.dependencies[name]);
    if (physical !== expectedPath) throw new Error('core-sdk-origin-mismatch: ' + name);
    origins[name] = { kind: 'source', expectedPath, resolvedPath: physical, verified: true, method, ...(runtimeOrigin ? { runtimeOrigin } : {}) };
  };
  if (config.stack === 'python') {
    const output = await command('uv', ['run', '--frozen', '--project', config.directory, 'python', '-c', 'import json, feature_auth, feature_standards; print(json.dumps({"auth":feature_auth.__file__,"core":feature_standards.__file__}))'], config.directory, environment, { capture: true });
    const paths = JSON.parse(output);
    for (const name of ['auth', 'core']) {
      if (typeof paths[name] !== 'string' || !within(config.dependencies[name], realpathSync(paths[name]))) throw new Error('core-sdk-origin-mismatch: ' + name);
      record(name, dirname(dirname(realpathSync(paths[name]))), 'python-import', paths[name]);
    }
  } else if (config.stack === 'go') {
    for (const [name, module] of [['auth', 'github.com/jongko54/feature-standards/implementations/go-net-http'], ['core', 'github.com/jongko54/feature-standards/libraries/go']]) {
      const result = JSON.parse(await command('go', ['list', '-m', '-json', module], config.directory, environment, { capture: true }));
      if (result.Path !== module || typeof result.Dir !== 'string') throw new Error('core-sdk-origin-mismatch: ' + name);
      record(name, result.Dir, 'go-module');
    }
  } else if (config.stack === 'rust') {
    const metadata = JSON.parse(await command('cargo', ['metadata', '--locked', '--format-version', '1'], config.directory, environment, { capture: true }));
    for (const [name, packageName] of [['auth', 'feature-standards-auth'], ['core', 'feature-standards-core']]) {
      const packages = metadata.packages.filter(item => item.name === packageName && item.source === null);
      if (packages.length !== 1) throw new Error('core-sdk-origin-mismatch: ' + name);
      record(name, dirname(packages[0].manifest_path), 'cargo-metadata', packages[0].manifest_path);
    }
  } else {
    const [program, args] = startCommand(config, environment);
    const result = JSON.parse(await command(program, [...args, '--sdk-origins'], config.directory, environment, { capture: true }));
    const applicationJar = join(config.directory, 'target/generated-core-app.jar').replaceAll('\\', '/');
    for (const name of ['auth', 'core']) {
      const coords = javaCoordinates(config.dependencies[name]);
      const filename = `${coords.artifactId}-${coords.version}${name === 'auth' ? '-library' : ''}.jar`;
      const runtime = name === 'auth' ? result.auth : result.authorization;
      if (typeof runtime !== 'string' || !decodeURIComponent(runtime).includes(applicationJar) || !runtime.includes(filename)
          || (name === 'core' && result.authorization !== result.listing)) throw new Error('core-sdk-origin-mismatch: ' + name);
      const stagedPom = readFileSync(join(config.directory, '.feature-core/java-' + name, 'pom.xml'), 'utf8');
      if (!stagedPom.includes('<sourceDirectory>' + xml(join(config.dependencies[name], 'src/main/java')) + '</sourceDirectory>')) throw new Error('core-sdk-origin-mismatch: ' + name);
      record(name, config.dependencies[name], 'java-runtime-code-source', runtime);
    }
  }
  return origins;
}

export async function runProject(mode, directory = dirname(fileURLToPath(import.meta.url))) {
  if (!['build', 'start', 'demo', 'check'].includes(mode)) throw new Error('usage: node project.mjs build|start|demo|check');
  const config = inspectProject(directory);
  const environment = processEnvironment(config.directory, coreEnvironment(mode === 'check' ? 'build' : mode));
  if (mode === 'build') { await build(config, environment); return; }
  if (mode === 'check') return checkCore(config, environment, { build, startCommand, dependencyOrigins, coreEnvironment });
  const [program, args] = startCommand(config, environment);
  return command(program, args, config.directory, environment, { timeout: 0 });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runProject(process.argv[2]).then(result => { if (result) console.log(JSON.stringify(result, null, 2)); })
    .catch(error => { console.error('feature-core project: ' + error.message); process.exitCode = 1; });
}
