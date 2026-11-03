import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

export async function verifyNpmRelease({ name, version, integrity }, {
  fetch = globalThis.fetch,
  sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
  now = () => performance.now(),
  log = message => console.error(message),
  timeoutMs = 20 * 60 * 1000,
  timeoutSignal = milliseconds => AbortSignal.timeout(milliseconds),
} = {}) {
  const started = now();
  const deadline = started + timeoutMs;
  let lastProgress = started;
  const pending = Symbol('pending');
  const remaining = () => {
    const milliseconds = deadline - now();
    if (milliseconds <= 0) throw new Error('npm release availability deadline exceeded');
    return milliseconds;
  };
  const isTimeout = (error, signal) => {
    if (signal.aborted && signal.reason?.name === 'TimeoutError') return true;
    const codes = ['ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_HEADERS_TIMEOUT', 'UND_ERR_BODY_TIMEOUT'];
    for (let cause = error, depth = 0; cause && depth < 3; cause = cause.cause, depth++) {
      if (cause.name === 'TimeoutError' || codes.includes(cause.code)) return true;
    }
    return false;
  };
  const request = async (url, stage, consume) => {
    const signal = timeoutSignal(Math.max(1, Math.ceil(Math.min(20_000, remaining()))));
    try {
      const response = await fetch(url, {signal});
      remaining();
      if (!response.ok) {
        if (response.status === 404 || response.status === 429 || (response.status >= 500 && response.status <= 599)) {
          await response.body?.cancel();
          return pending;
        }
        throw new Error(`npm ${stage} request rejected (HTTP ${response.status})`);
      }
      const result = await consume(response);
      remaining();
      return result;
    } catch (error) {
      remaining();
      if (isTimeout(error, signal)) return pending;
      if (stage === 'metadata' && error instanceof SyntaxError) throw new Error('Registry metadata is invalid');
      throw error;
    }
  };
  const wait = async stage => {
    const milliseconds = remaining();
    if (now() - lastProgress >= 30_000) {
      log(`Waiting for npm ${stage} availability (${Math.floor((now() - started) / 1000)}s elapsed)`);
      lastProgress = now();
    }
    await sleep(Math.min(5000, milliseconds));
  };

  // npm scans accepted publishes before exposing them publicly. Both lookup and
  // download share one deadline, including time spent fetching response bodies.
  const registryUrl = `https://registry.npmjs.org/${encodeURIComponent(name)}/${encodeURIComponent(version)}`;
  let metadata;
  while (true) {
    metadata = await request(registryUrl, 'metadata', response => response.json());
    if (metadata !== pending) break;
    await wait('metadata');
  }
  if (!metadata || typeof metadata !== 'object' || !metadata.dist) throw new Error('Registry metadata is invalid');
  if (metadata.name !== name) throw new Error('Registry package name mismatch');
  if (metadata.version !== version) throw new Error('Registry package version mismatch');
  if (metadata.dist.integrity !== integrity) throw new Error('Registry artifact differs from reviewed tarball');
  let tarballUrl;
  try {
    tarballUrl = new URL(metadata.dist.tarball);
    if (tarballUrl.protocol !== 'https:' || tarballUrl.username || tarballUrl.password) throw new Error();
  } catch {
    throw new Error('Registry tarball metadata is invalid');
  }
  while (true) {
    const downloaded = await request(tarballUrl.href, 'tarball', response => response.arrayBuffer());
    if (downloaded !== pending) {
      const downloadedIntegrity = `sha512-${createHash('sha512').update(Buffer.from(downloaded)).digest('base64')}`;
      if (downloadedIntegrity !== integrity) throw new Error('Public tarball differs from reviewed tarball');
      remaining();
      break;
    }
    await wait('tarball');
  }
  return {name, version, integrity, registry_verified: true, public_download_verified: true};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [file, name, version] = process.argv.slice(2);
  assert(file && name && version, 'Expected tarball, package name and version');
  const integrity = `sha512-${createHash('sha512').update(await readFile(file)).digest('base64')}`;
  console.log(JSON.stringify(await verifyNpmRelease({name, version, integrity})));
}
