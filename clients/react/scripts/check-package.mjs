import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Inspect the actual tarball, then resolve its exports without the source checkout.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const metadata = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const temporary = mkdtempSync(join(tmpdir(), 'feature-auth-npm-'));
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const run = (program, args, cwd = temporary) => execFileSync(program, args, {
  cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
});
try {
  const [packed] = JSON.parse(run(npm, ['pack', '--json', '--pack-destination', temporary], root));
  assert.deepEqual(packed.files.map(file => file.path).sort(), [
    'LICENSE', 'README.md', 'lib/api.d.ts', 'lib/api.js', 'package.json',
  ]);
  assert.equal(packed.name, metadata.name);
  assert.equal(packed.version, metadata.version);
  writeFileSync(join(temporary, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  run(npm, ['install', '--no-audit', '--no-fund', join(temporary, packed.filename)]);
  const specifier = JSON.stringify(metadata.name);
  const apiSpecifier = JSON.stringify(`${metadata.name}/api`);
  writeFileSync(join(temporary, 'smoke.mjs'), `
import assert from 'node:assert/strict';
import * as root from ${specifier};
import { createAuthApi, ApiError, authApi } from ${apiSpecifier};
assert.equal(root.createAuthApi, createAuthApi);
assert.equal(typeof authApi.me, 'function');
const session = { user: { id: 'demo-user', email: 'demo@example.com' }, csrfToken: 'csrf' };
const api = createAuthApi(async (path, options) => {
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.cache, 'no-store');
  if (path === '/auth/login') {
    assert.deepEqual(JSON.parse(options.body), { email: 'demo@example.com', password: ' unchanged ' });
    return Response.json(session);
  }
  if (path === '/auth/logout') {
    assert.equal(new Headers(options.headers).get('X-CSRF-Token'), 'csrf');
    return new Response(null, { status: 204 });
  }
  return Response.json({ error: { code: 'UNAUTHENTICATED' } }, { status: 401 });
});
assert.equal(await api.me(), null);
assert.deepEqual(await api.login('demo@example.com', ' unchanged '), session);
assert.equal(await api.logout('csrf'), undefined);
const failing = createAuthApi(async () => Response.json({ error: { code: 'CSRF_INVALID' } }, { status: 403 }));
await assert.rejects(failing.logout('bad'), error => error instanceof ApiError && error.status === 403);
`);
  run(process.execPath, ['smoke.mjs']);
  writeFileSync(join(temporary, 'usage.ts'), `
import { createAuthApi, ApiError, type AuthSession } from ${specifier};
import { authApi } from ${apiSpecifier};
const session: AuthSession | null = await createAuthApi().me();
const retry: number = new ApiError(429, 'RATE_LIMITED', 5).retryAfter;
void session; void retry; void authApi;
`);
  writeFileSync(join(temporary, 'tsconfig.json'), JSON.stringify({
    compilerOptions: { target: 'ES2022', module: 'NodeNext', moduleResolution: 'NodeNext',
      lib: ['ES2022', 'DOM'], strict: true, types: [], noEmit: true },
    include: ['usage.ts'],
  }));
  run(join(root, 'node_modules', '.bin', 'tsc'), ['-p', 'tsconfig.json']);
  console.log(`Package consumer: PASS (${packed.name}@${packed.version}; 5 allowed files; ESM exports, runtime and TypeScript)`);
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
