import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { verifyNpmRelease } from './verify-npm-release.mjs';

const bytes = Buffer.from('reviewed npm tarball');
const integrity = `sha512-${createHash('sha512').update(bytes).digest('base64')}`;
const release = {name: '@example/auth', version: '1.2.3', integrity};
const tarballUrl = 'https://registry.npmjs.org/@example/auth/-/auth-1.2.3.tgz';
const metadata = () => ({...release, dist: {integrity, tarball: tarballUrl}});
const ready = () => Response.json(metadata());
const download = () => new Response(bytes);
const timeout = () => new DOMException('network timeout', 'TimeoutError');

function harness(handler, options = {}) {
  let elapsed = 0;
  const calls = [], sleeps = [], logs = [], requestTimeouts = [];
  const advance = milliseconds => { elapsed += milliseconds; };
  return {
    calls, sleeps, logs, requestTimeouts,
    get elapsed() { return elapsed; },
    dependencies: {
      now: () => elapsed,
      sleep: async milliseconds => { sleeps.push(milliseconds); advance(milliseconds); },
      log: message => logs.push({at: elapsed, message}),
      timeoutSignal: milliseconds => {
        requestTimeouts.push(milliseconds);
        return new AbortController().signal;
      },
      fetch: async (url, request) => {
        calls.push({url, request});
        return handler({url, elapsed, advance, request});
      },
      ...options,
    },
  };
}

test('waits beyond the old two-minute cap for metadata and then the public tarball', async () => {
  const state = harness(({url, elapsed}) => {
    if (url !== tarballUrl) return elapsed >= 330_000 ? ready() : new Response('pending scan', {status: 404});
    return elapsed >= 365_000 ? download() : new Response('pending replication', {status: 404});
  });
  const receipt = await verifyNpmRelease(release, state.dependencies);
  assert.deepEqual(receipt, {...release, registry_verified: true, public_download_verified: true});
  assert.equal(state.elapsed, 365_000);
  assert.equal(state.calls.filter(call => call.url !== tarballUrl).length, 67);
  assert.equal(state.calls.filter(call => call.url === tarballUrl).length, 8);
  assert.ok(state.calls.every(call => call.request.signal instanceof AbortSignal));
  assert.ok(state.requestTimeouts.every(milliseconds => milliseconds === 20_000));
  assert.ok(state.logs.length >= 11);
  assert.ok(state.logs.every((entry, index) => entry.at - (state.logs[index - 1]?.at ?? 0) >= 30_000));
  assert.ok(state.logs.every(entry => !/pending scan|pending replication/.test(entry.message)));
});

test('expires at the overall twenty-minute deadline while metadata stays unavailable', async () => {
  const state = harness(() => new Response('not available', {status: 404}));
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /availability deadline exceeded/);
  assert.equal(state.elapsed, 1_200_000);
  assert.equal(state.calls.length, 240);
});

test('tarball polling shares the metadata deadline instead of starting another twenty minutes', async () => {
  const state = harness(({url, elapsed}) => url !== tarballUrl && elapsed >= 1_195_000
    ? ready() : new Response('not available', {status: 404}));
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /availability deadline exceeded/);
  assert.equal(state.elapsed, 1_200_000);
  assert.equal(state.calls.filter(call => call.url === tarballUrl).length, 1);
});

test('retries only transient HTTP responses and genuine network timeouts in either stage', async () => {
  const registry = [404, 429, 500, 503, timeout(), new TypeError('fetch failed', {cause: {code: 'UND_ERR_CONNECT_TIMEOUT'}}), 'ready'];
  const tarball = [404, 429, 502, timeout(), 'download'];
  const state = harness(({url}) => {
    const next = (url === tarballUrl ? tarball : registry).shift();
    if (next instanceof Error) throw next;
    if (next === 'ready') return ready();
    if (next === 'download') return download();
    return new Response('private response body', {status: next});
  });
  await verifyNpmRelease(release, state.dependencies);
  assert.equal(state.elapsed, 50_000);
  assert.equal(state.sleeps.length, 10);
  assert.equal(state.calls.length, 12);
  assert.ok(state.logs.every(entry => !entry.message.includes('private response body')));
});

test('request timeouts are twenty seconds and shrink to the overall remaining time', async () => {
  let duration;
  const state = harness(({advance}) => {
    advance(duration);
    throw timeout();
  }, {
    timeoutMs: 27_000,
    timeoutSignal: milliseconds => {
      duration = milliseconds;
      state.requestTimeouts.push(milliseconds);
      return new AbortController().signal;
    },
  });
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /availability deadline exceeded/);
  assert.deepEqual(state.requestTimeouts, [20_000, 2_000]);
  assert.deepEqual(state.sleeps, [5_000]);
  assert.equal(state.elapsed, 27_000);
});

test('body-read timeouts retry, and a late successful body cannot exceed the deadline', async () => {
  let attempts = 0;
  const state = harness(({url}) => {
    if (url === tarballUrl) return download();
    if (attempts++ === 0) return {ok: true, json: async () => { throw timeout(); }};
    return ready();
  });
  await verifyNpmRelease(release, state.dependencies);
  assert.equal(state.elapsed, 5_000);

  const late = harness(({advance}) => ({
    ok: true,
    json: async () => { advance(25_000); return metadata(); },
  }), {timeoutMs: 20_000});
  await assert.rejects(verifyNpmRelease(release, late.dependencies), /availability deadline exceeded/);
  assert.equal(late.calls.length, 1);
});

test('authentication and other permanent HTTP errors fail immediately without retry', async t => {
  for (const status of [400, 401, 403, 408, 422, 600]) {
    await t.test(String(status), async () => {
      const state = harness(() => status === 600 ? {ok: false, status}
        : new Response('credentials must not be logged', {status}));
      await assert.rejects(verifyNpmRelease(release, state.dependencies), /rejected.*HTTP/);
      assert.equal(state.calls.length, 1);
      assert.equal(state.sleeps.length, 0);
      assert.equal(state.logs.length, 0);
    });
  }
  const state = harness(({url}) => url === tarballUrl ? new Response('forbidden', {status: 403}) : ready());
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /rejected.*HTTP/);
  assert.equal(state.calls.length, 2);
  assert.equal(state.sleeps.length, 0);
});

test('wrong or malformed metadata is rejected before attempting a tarball download', async t => {
  const cases = [
    {...metadata(), name: '@other/auth'},
    {...metadata(), version: '1.2.4'},
    {...metadata(), dist: {...metadata().dist, integrity: 'sha512-wrong'}},
    {...metadata(), dist: undefined},
    {...metadata(), dist: {...metadata().dist, tarball: 'invalid URL'}},
    {...metadata(), dist: {...metadata().dist, tarball: 'https://user:secret@example.com/file.tgz'}},
  ];
  for (const [index, body] of cases.entries()) {
    await t.test(String(index), async () => {
      const state = harness(() => Response.json(body));
      await assert.rejects(verifyNpmRelease(release, state.dependencies), /metadata|name|version|artifact|tarball/);
      assert.equal(state.calls.length, 1);
      assert.equal(state.sleeps.length, 0);
    });
  }
  const state = harness(() => new Response('not JSON: secret'));
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /metadata/);
  assert.equal(state.sleeps.length, 0);
});

test('a different public tarball fails its SHA-512 comparison immediately', async () => {
  const state = harness(({url}) => url === tarballUrl ? new Response('different bytes') : ready());
  await assert.rejects(verifyNpmRelease(release, state.dependencies), /tarball.*differs/);
  assert.equal(state.calls.length, 2);
  assert.equal(state.sleeps.length, 0);
});

test('non-timeout network failures and unrelated aborts are not retried', async t => {
  const errors = [
    new TypeError('fetch failed', {cause: {code: 'ENOTFOUND'}}),
    new TypeError('fetch failed', {cause: {code: 'ECONNREFUSED'}}),
    new DOMException('unrelated abort', 'AbortError'),
  ];
  for (const [index, error] of errors.entries()) {
    await t.test(String(index), async () => {
      const state = harness(() => { throw error; });
      await assert.rejects(verifyNpmRelease(release, state.dependencies), candidate => candidate === error);
      assert.equal(state.calls.length, 1);
      assert.equal(state.sleeps.length, 0);
    });
  }
});
