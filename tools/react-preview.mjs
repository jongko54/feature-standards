/** Development-only React build/proxy. Serve generated files, never the checkout. */
import { createServer, request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';

const ENTRY = '<script type="module" src="/src/main.tsx"></script>';
const LOOPBACK = '127.0.0.1';
const ENV_KEYS = ['AUTH_API_TARGET', 'VITE_AUTH_ACCOUNT_LIFECYCLE'];
const HOP_HEADERS = ['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'];

export function parseOptions(argv, { defaultPort = 5173 } = {}) {
  const command = argv[0] ?? 'dev';
  if (!['dev', 'build', 'preview'].includes(command)) throw new Error('unsupported frontend command');
  const options = { command, host: LOOPBACK, port: command === 'preview' ? 4173 : defaultPort,
    mode: command === 'dev' ? 'development' : 'production' };
  const seen = new Set();
  for (let index = 1; index < argv.length; index++) {
    const flag = argv[index];
    if (seen.has(flag)) throw new Error('unsupported repeated frontend option');
    seen.add(flag);
    if (flag === '--strictPort') continue; // Ports are always strict.
    if (!['--host', '--port', '--mode'].includes(flag) || index + 1 === argv.length) throw new Error('unsupported frontend option');
    const value = argv[++index];
    if (flag === '--host' && ![LOOPBACK, 'localhost'].includes(value)) throw new Error('frontend host must be loopback');
    if (flag === '--port') {
      if (!/^[1-9][0-9]{0,4}$/.test(value) || Number(value) > 65535) throw new Error('invalid frontend port');
      options.port = Number(value);
    }
    if (flag === '--mode') {
      if (!/^[A-Za-z0-9_-]+$/.test(value) || value === 'local') throw new Error('invalid frontend mode');
      options.mode = value;
    }
  }
  return options;
}

export function loadEnvironment(root, mode, inherited, { parse, expand }) {
  if (!/^[A-Za-z0-9_-]+$/.test(mode) || mode === 'local') throw new Error('invalid frontend mode');
  const parsed = {};
  for (const name of ['.env', '.env.local', `.env.${mode}`, `.env.${mode}.local`]) {
    const file = join(root, name);
    if (existsSync(file)) Object.assign(parsed, parse(readFileSync(file)));
  }
  // Expansion gets a copy: parsing demo settings never mutates the caller's environment.
  const expanded = expand({ parsed, processEnv: { ...inherited } }).parsed;
  return Object.fromEntries(ENV_KEYS.map(key => [key, inherited[key] ?? expanded[key]]));
}

function targetOrigin(value) {
  let url;
  try { url = new URL(value ?? 'http://127.0.0.1:8000'); } catch { throw new Error('invalid frontend API target'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('frontend API target must be an HTTP origin without credentials');
  }
  return url;
}

function outputStat(path) {
  try { return lstatSync(path); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function plainDirectory(path) {
  const stat = outputStat(path);
  if (stat && (!stat.isDirectory() || stat.isSymbolicLink())) throw new Error('linked frontend output is unsupported');
  mkdirSync(path, { recursive: true });
}

function writeHtml(root, output, development, cssBuilt) {
  const source = readFileSync(join(root, 'index.html'), 'utf8');
  if (source.split(ENTRY).length !== 2) throw new Error('unsupported frontend HTML entry');
  const css = cssBuilt ? '<link rel="stylesheet" href="/assets/app.css">' : '';
  const reload = development ? '<script type="module">new EventSource("/esbuild").addEventListener("change",()=>location.reload());</script>' : '';
  const destination = join(output, 'index.html');
  if (outputStat(destination)?.isSymbolicLink()) throw new Error('linked frontend output is unsupported');
  writeFileSync(destination, source.replace(ENTRY, `${css}<script type="module" src="/assets/app.js"></script>${reload}`));
}

function buildOptions({ root, output, environment, development }) {
  plainDirectory(output);
  plainDirectory(join(output, 'assets'));
  for (const name of ['app.js', 'app.css', 'app.js.map', 'app.css.map']) {
    const file = join(output, 'assets', name);
    if (outputStat(file)?.isSymbolicLink()) throw new Error('linked frontend output is unsupported');
  }
  return {
    absWorkingDir: root, entryPoints: ['src/main.tsx'], outfile: join(output, 'assets/app.js'),
    bundle: true, platform: 'browser', format: 'esm', target: 'es2022', jsx: 'automatic',
    minify: !development, sourcemap: development, logLevel: 'silent', metafile: true, legalComments: 'eof',
    define: { 'import.meta.env.VITE_AUTH_ACCOUNT_LIFECYCLE': JSON.stringify(environment.VITE_AUTH_ACCOUNT_LIFECYCLE === 'true' ? 'true' : 'false'),
      'process.env.NODE_ENV': JSON.stringify(development ? 'development' : 'production') },
    plugins: [{ name: 'demo-html', setup(build) {
      build.onEnd(result => {
        if (!result.errors.length) {
          const cssBuilt = Object.keys(result.metafile.outputs).some(path => resolve(root, path) === join(output, 'assets/app.css'));
          writeHtml(root, output, development, cssBuilt);
        }
      });
    } }],
  };
}

export async function buildFrontend({ root, esbuild, environment }) {
  const output = resolve(root, 'dist');
  await esbuild.build(buildOptions({ root, output, environment, development: false }));
  return output;
}

function forwardedHeaders(headers, host) {
  const result = { ...headers };
  const named = String(headers.connection ?? '').split(',').map(name => name.trim().toLowerCase());
  for (const name of [...HOP_HEADERS, ...named]) delete result[name];
  if (host) result.host = host;
  return result;
}

function proxy(req, res, target, { preserveHost, timeout }) {
  const headers = forwardedHeaders(req.headers, preserveHost ? undefined : target.host);
  const request = target.protocol === 'https:' ? httpsRequest : httpRequest;
  const upstream = request(target, { method: req.method, path: req.url, headers }, response => {
    if (!preserveHost && response.statusCode >= 500) {
      response.resume();
      res.writeHead(503, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
      res.end('Frontend build unavailable');
      return;
    }
    res.writeHead(response.statusCode, forwardedHeaders(response.headers));
    response.on('error', () => res.destroy());
    response.pipe(res);
  });
  const failure = () => {
    if (!res.headersSent) { res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' }); res.end('Frontend upstream unavailable'); }
    else res.destroy();
  };
  // EventSource remains open; API requests have a finite upstream inactivity bound.
  if (timeout) upstream.setTimeout(timeout, () => upstream.destroy());
  upstream.on('error', failure);
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => { if (!res.writableEnded) upstream.destroy(); });
  req.pipe(upstream);
}

function staticPathAllowed(output, pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname).replaceAll('\\', '/'); } catch { return false; }
  if (decoded.includes('\0')) return false;
  const candidate = resolve(output, '.' + decoded);
  const distance = relative(output, candidate);
  if (isAbsolute(distance) || distance === '..' || distance.startsWith('..' + sep)) return false;
  const inspect = path => {
    const components = relative(output, path).split(sep).filter(Boolean);
    let current = output;
    for (const part of ['', ...components]) {
      current = part ? join(current, part) : current;
      try { if (lstatSync(current).isSymbolicLink()) return false; }
      catch (error) { return error.code === 'ENOENT' || error.code === 'ENOTDIR'; }
    }
    return true;
  };
  // Recheck on every request so links introduced after startup are refused too.
  return inspect(candidate) && inspect(join(candidate, 'index.html')) && inspect(join(output, 'index.html'));
}

export async function startFrontend({ root, esbuild, environment, command = 'dev', port = 5173,
  routes = ['/auth', '/healthz'], apiTimeout = 15000 }) {
  if (!['dev', 'preview'].includes(command)) throw new Error('unsupported frontend server command');
  const target = targetOrigin(environment.AUTH_API_TARGET);
  const temporary = command === 'dev' ? mkdtempSync(join(tmpdir(), 'feature-react-')) : null;
  const output = temporary ?? resolve(root, 'dist');
  if (command === 'preview' && (!existsSync(join(output, 'index.html')) || lstatSync(output).isSymbolicLink())) throw new Error('build the frontend before preview');
  let context;
  let server;
  const sockets = new Set();
  let closed = false;
  const close = async () => {
    if (closed) return;
    closed = true;
    for (const socket of sockets) socket.destroy();
    if (server?.listening) await new Promise(resolveClose => server.close(resolveClose));
    await context?.dispose();
    if (temporary) rmSync(temporary, { recursive: true, force: true });
  };
  try {
    context = await esbuild.context(command === 'dev' ? buildOptions({ root, output, environment, development: true }) : {});
    if (command === 'dev') { await context.rebuild(); await context.watch(); }
    const internal = await context.serve({ host: LOOPBACK, port: 0, servedir: output, fallback: join(output, 'index.html') });
    const ui = new URL(`http://${LOOPBACK}:${internal.port}`);
    server = createServer((req, res) => {
      const host = String(req.headers.host ?? '').toLowerCase();
      const allowed = new Set([`${LOOPBACK}:${server.address().port}`, `localhost:${server.address().port}`]);
      if (!allowed.has(host)) { res.writeHead(403); res.end('Frontend host refused'); return; }
      let pathname;
      try { pathname = new URL(req.url, `http://${host}`).pathname; }
      catch { res.writeHead(400); res.end('Invalid frontend request'); return; }
      const api = routes.some(route => pathname === route || pathname.startsWith(`${route}/`));
      if (!api && req.headers.origin && req.headers.origin !== `http://${host}`) {
        res.writeHead(403); res.end('Frontend origin refused'); return;
      }
      if (!api && !staticPathAllowed(output, pathname)) {
        res.writeHead(403, { 'cache-control': 'no-store' }); res.end('Frontend path refused'); return;
      }
      proxy(req, res, api ? target : ui, { preserveHost: api, timeout: api ? apiTimeout : 0 });
    });
    server.on('connection', socket => { sockets.add(socket); socket.once('close', () => sockets.delete(socket)); });
    await new Promise((resolveListen, reject) => {
      server.once('error', reject);
      server.listen(port, LOOPBACK, resolveListen);
    });
    return { port: server.address().port, output, close };
  } catch (error) { await close(); throw error; }
}

export async function frontendMain({ root, esbuild, parse, expand, defaultPort = 5173, routes = ['/auth', '/healthz'], argv = process.argv.slice(2) }) {
  let options;
  try {
    options = parseOptions(argv, { defaultPort });
    const environment = loadEnvironment(root, options.mode, process.env, { parse, expand });
    if (options.command === 'build') { await buildFrontend({ root, esbuild, environment }); console.log('Frontend build complete'); return; }
    const frontend = await startFrontend({ root, esbuild, environment, ...options, routes });
    for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { frontend.close().then(() => process.exit(0)); });
    console.log(`Frontend ${options.command}: http://${LOOPBACK}:${frontend.port}`);
  } catch (error) {
    // Build/proxy inputs and environment values can contain credentials. Keep CLI errors generic.
    console.error(error.code === 'EADDRINUSE' ? 'Frontend port is already in use' : 'Frontend command failed; check options, environment and source');
    process.exitCode = 1;
  }
}
