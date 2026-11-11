import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export async function verifyReleaseCi(context, {fetch: request = fetch, now = Date.now} = {}) {
  const {sha, repository, token} = context;
  assert(repository === 'jongko54/feature-standards' && /^[a-f0-9]{40}$/.test(sha ?? '') && token, 'Missing trusted release context');
  const checkedAt = now();
  const checks = {};
  for (const [label, workflow] of [['functional', 'ci.yml'], ['security', 'security.yml']]) {
    const response = await request(`https://api.github.com/repos/${repository}/actions/workflows/${workflow}/runs?head_sha=${sha}&per_page=100`, {
      headers: {Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
      signal: AbortSignal.timeout(30_000),
    });
    assert(response.ok, `Could not verify source ${label} CI`);
    const runs = (await response.json()).workflow_runs;
    assert(Array.isArray(runs), `Malformed source ${label} CI response`);
    const events = label === 'security' ? ['push', 'schedule', 'workflow_dispatch'] : ['push'];
    const candidates = runs.filter(run => run.head_sha === sha && run.head_branch === 'main' && events.includes(run.event));
    candidates.sort((a, b) => b.id - a.id || b.run_attempt - a.run_attempt);
    const run = candidates[0];
    assert(run && Number.isSafeInteger(run.id) && run.id > 0 && run.status === 'completed' && run.conclusion === 'success',
      `Latest ${label} CI for this exact main source commit must succeed before publishing`);
    const age = checkedAt - Date.parse(run.created_at);
    assert(Number.isFinite(age) && age >= -300_000 && (label !== 'security' || age <= 72 * 3_600_000),
      `Source ${label} CI evidence is invalid or older than the 72-hour security window`);
    checks[label] = {workflow, runId: run.id, runAttempt: run.run_attempt, createdAt: run.created_at,
      url: `https://github.com/${repository}/actions/runs/${run.id}`, conclusion: 'success'};
  }
  return {schemaVersion: 1, kind: 'verified-source-workflow-references', status: 'passed', repository,
    sourceCommit: sha, verifiedAt: new Date(checkedAt).toISOString(), securityMaxAgeHours: 72, checks};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const receipt = await verifyReleaseCi({sha: process.env.GITHUB_SHA, repository: process.env.GITHUB_REPOSITORY, token: process.env.GH_TOKEN});
  const args = process.argv.slice(2);
  assert(args.length === 0 || (args.length === 2 && args[0] === '--receipt'), 'Unknown release verification arguments');
  if (args.length) writeFileSync(args[1], `${JSON.stringify(receipt, null, 2)}\n`, {flag: 'wx', mode: 0o600});
  console.log(`Verified source CI and security evidence for ${receipt.sourceCommit}`);
}
