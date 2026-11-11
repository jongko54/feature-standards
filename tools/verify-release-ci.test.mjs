import assert from 'node:assert/strict';
import test from 'node:test';
import {verifyReleaseCi} from './verify-release-ci.mjs';

const sha = 'a'.repeat(40);
const now = Date.parse('2026-11-11T12:00:00Z');
const context = {sha, repository: 'jongko54/feature-standards', token: 'synthetic-test-token'};
const run = (workflow, overrides = {}) => ({id: workflow === 'ci.yml' ? 10 : 20, head_sha: sha, head_branch: 'main',
  event: 'push', status: 'completed', conclusion: 'success', run_attempt: 1,
  created_at: '2026-11-11T11:00:00Z', html_url: `https://github.com/jongko54/feature-standards/actions/runs/${workflow === 'ci.yml' ? 10 : 20}`,
  ...overrides});
const deps = (ci = [run('ci.yml')], security = [run('security.yml')]) => ({now: () => now,
  fetch: async url => Response.json({workflow_runs: url.includes('/security.yml/') ? security : ci})});

test('full functional CI alone is insufficient without exact source security evidence', async () => {
  await assert.rejects(verifyReleaseCi(context, deps(undefined, [])), /security/i);
});

test('requires successful, fresh security evidence for the exact main commit', async () => {
  for (const changed of [{head_sha: 'b'.repeat(40)}, {head_branch: 'other'}, {event: 'pull_request'},
    {conclusion: 'failure'}, {status: 'in_progress'}, {created_at: '2026-11-01T12:00:00Z'}]) {
    await assert.rejects(verifyReleaseCi(context, deps(undefined, [run('security.yml', changed)])), /security/i);
  }
});

test('a newer failed or pending run cannot be bypassed with an older successful result', async () => {
  await assert.rejects(verifyReleaseCi(context, deps(undefined, [run('security.yml', {id: 21, conclusion: 'failure'}), run('security.yml')])), /security/i);
});

test('returns source-bound run references without credentials', async () => {
  const receipt = await verifyReleaseCi(context, deps());
  assert.equal(receipt.sourceCommit, sha);
  assert.equal(receipt.checks.security.runId, 20);
  assert.equal(receipt.checks.functional.runId, 10);
  assert.equal(receipt.status, 'passed');
  assert.ok(!JSON.stringify(receipt).includes(context.token));
});

test('supports a fresh daily security run, and HTTP/invalid responses fail closed', async () => {
  await verifyReleaseCi(context, deps(undefined, [run('security.yml', {event: 'schedule'})]));
  await assert.rejects(verifyReleaseCi(context, {fetch: async () => new Response('', {status: 403})}), /verify/i);
  await assert.rejects(verifyReleaseCi(context, {fetch: async () => Response.json({workflow_runs: null})}));
});
