import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const [file, name, version] = process.argv.slice(2);
assert(file && name && version, 'Expected tarball, package name and version');
const integrity = `sha512-${createHash('sha512').update(await readFile(file)).digest('base64')}`;
let metadata;
for (let attempt = 0; attempt < 24; attempt++) {
  const response = await fetch(`https://registry.npmjs.org/${encodeURIComponent(name)}/${encodeURIComponent(version)}`);
  if (response.ok) {
    metadata = await response.json();
    break;
  }
  assert(response.status === 404 || response.status === 429 || response.status >= 500, 'Registry rejected lookup');
  await new Promise(resolve => setTimeout(resolve, 5000));
}
assert(metadata, 'Registry version did not become available');
assert.equal(metadata.name, name);
assert.equal(metadata.version, version);
assert.equal(metadata.dist.integrity, integrity, 'Registry artifact differs from reviewed tarball');
const tarball = await fetch(metadata.dist.tarball);
assert(tarball.ok, 'Public tarball download failed');
assert.equal(`sha512-${createHash('sha512').update(Buffer.from(await tarball.arrayBuffer())).digest('base64')}`, integrity);
console.log(JSON.stringify({name, version, integrity, registry_verified: true, public_download_verified: true}));
